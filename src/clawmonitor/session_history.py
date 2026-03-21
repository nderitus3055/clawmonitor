from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import hashlib
import json
import re

from .config import cache_dir
from .transcript_tail import (
    _clean_preview,
    _extract_inbound_from_internal_wrapper,
    _extract_text,
    _extract_thinking,
    _extract_tool_call_names,
    _is_internal_user_text,
)


PARSER_VERSION = 1
MAX_EVENT_SUMMARY_CHARS = 240
MAX_EVENT_TITLE_CHARS = 72
MAX_CACHE_EVENTS = 240
MAX_LOOKBACK_DAYS = 7

_DONE_PATTERNS = [
    re.compile(r"\b(done|completed|finished|resolved|success(?:ful|fully)?)\b", re.IGNORECASE),
    re.compile(r"(已完成|完成了|完成啦|搞定了|已经搞定|处理成功|测试通过)"),
]
_BLOCKED_PATTERNS = [
    re.compile(r"\b(blocked|timeout|timed out|rate limit|insufficient|forbidden|unauthorized|error|failed)\b", re.IGNORECASE),
    re.compile(r"(阻塞|超时|限流|余额不足|没额度|权限不足|失败了|失败啦|报错|错误)"),
]
_WORKING_PATTERNS = [
    re.compile(r"\b(in progress|working|starting|scanning|loading|reading|running|next step)\b", re.IGNORECASE),
    re.compile(r"(当前进度|进行中|处理中|正在|开始|下一步|步骤|排查|读取中|扫描中|运行中)"),
]


def _parse_iso(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(text: str, limit: int) -> str:
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    if limit <= 1:
        return raw[:limit]
    return raw[: limit - 1].rstrip() + "…"


def _title_from_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "-"
    line = raw.splitlines()[0].strip()
    return _truncate(line, MAX_EVENT_TITLE_CHARS)


def _summary_from_text(text: str) -> str:
    return _truncate((text or "").strip(), MAX_EVENT_SUMMARY_CHARS)


def _event_rank(kind: str) -> int:
    if kind == "blocked":
        return 4
    if kind == "done":
        return 3
    if kind == "working":
        return 2
    if kind == "started":
        return 1
    return 0


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@dataclass(frozen=True)
class TaskHistoryEvent:
    ts: Optional[datetime]
    kind: str
    title: str
    summary: str
    source: str
    confidence: str


@dataclass(frozen=True)
class SessionHistoryResult:
    session_key: str
    session_id: str
    session_file: Path
    events: List[TaskHistoryEvent]
    mode: str  # rebuild | incremental | hit
    generated_at: datetime
    file_size: int
    file_mtime: float
    file_inode: Optional[int]
    scan_offset: int
    header_session_id: Optional[str]
    stale: bool = False


def cache_path_for_session(*, session_key: str, session_id: str, session_file: Path) -> Path:
    digest = hashlib.sha256(f"{session_key}|{session_id}|{session_file}".encode("utf-8")).hexdigest()[:20]
    safe_session = re.sub(r"[^A-Za-z0-9._-]+", "_", session_id or "session")[:32]
    root = cache_dir() / "history"
    return root / f"{safe_session}-{digest}.json"


def filter_history_events(
    events: Sequence[TaskHistoryEvent],
    *,
    days: int,
    now: Optional[datetime] = None,
) -> List[TaskHistoryEvent]:
    now_dt = now or _now_utc()
    cutoff = now_dt - timedelta(days=max(1, days))
    out: List[TaskHistoryEvent] = []
    for event in events:
        if event.ts is None or event.ts >= cutoff:
            out.append(event)
    out.sort(key=lambda ev: ev.ts or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def history_is_stale(result: SessionHistoryResult) -> bool:
    try:
        st = result.session_file.stat()
    except Exception:
        return True
    inode = getattr(st, "st_ino", None)
    if st.st_size != result.file_size:
        return True
    if st.st_mtime != result.file_mtime:
        return True
    if inode != result.file_inode:
        return True
    return False


def load_session_history(
    *,
    session_key: str,
    session_id: str,
    session_file: Path,
    max_days: int = MAX_LOOKBACK_DAYS,
    now: Optional[datetime] = None,
) -> SessionHistoryResult:
    if not session_file.exists():
        raise FileNotFoundError(f"Session transcript missing: {session_file}")

    st = session_file.stat()
    inode = getattr(st, "st_ino", None)
    cache_path = cache_path_for_session(session_key=session_key, session_id=session_id, session_file=session_file)
    cache_doc = _safe_load_json(cache_path)
    cache_ok = bool(cache_doc)
    header_session_id = _read_header_session_id(session_file)
    mode = "rebuild"
    events: List[TaskHistoryEvent]
    scan_offset = 0

    if cache_ok and _cache_matches_identity(
        cache_doc,
        session_key=session_key,
        session_id=session_id,
        session_file=session_file,
        header_session_id=header_session_id,
        file_inode=inode,
        parser_version=PARSER_VERSION,
    ):
        cached_size = int(cache_doc.get("file_size") or 0)
        cached_offset = int(cache_doc.get("scan_offset") or 0)
        cached_events = _events_from_cache(cache_doc.get("events"))
        if cached_size == st.st_size and float(cache_doc.get("file_mtime") or 0.0) == st.st_mtime:
            mode = "hit"
            events = filter_history_events(cached_events, days=max_days, now=now)
            scan_offset = cached_offset
        elif cached_size <= st.st_size and cached_offset <= st.st_size:
            mode = "incremental"
            extra_events, scan_offset = _scan_transcript_for_events(
                session_file,
                start_offset=cached_offset,
                now=now,
                max_days=max_days,
            )
            events = _merge_history_events(cached_events, extra_events, now=now, max_days=max_days)
        else:
            extra_events, scan_offset = _scan_transcript_for_events(
                session_file,
                start_offset=0,
                now=now,
                max_days=max_days,
            )
            events = extra_events
    else:
        extra_events, scan_offset = _scan_transcript_for_events(
            session_file,
            start_offset=0,
            now=now,
            max_days=max_days,
        )
        events = extra_events

    generated_at = now or _now_utc()
    result = SessionHistoryResult(
        session_key=session_key,
        session_id=session_id,
        session_file=session_file,
        events=events,
        mode=mode,
        generated_at=generated_at,
        file_size=st.st_size,
        file_mtime=st.st_mtime,
        file_inode=inode,
        scan_offset=scan_offset,
        header_session_id=header_session_id,
        stale=False,
    )
    _write_cache(cache_path, result)
    return result


def _cache_matches_identity(
    cache_doc: Dict[str, Any],
    *,
    session_key: str,
    session_id: str,
    session_file: Path,
    header_session_id: Optional[str],
    file_inode: Optional[int],
    parser_version: int,
) -> bool:
    if int(cache_doc.get("parser_version") or 0) != parser_version:
        return False
    if str(cache_doc.get("session_key") or "") != session_key:
        return False
    if str(cache_doc.get("session_id") or "") != session_id:
        return False
    if str(cache_doc.get("session_file") or "") != str(session_file):
        return False
    if cache_doc.get("header_session_id") != header_session_id:
        return False
    if cache_doc.get("file_inode") != file_inode:
        return False
    return True


def _events_from_cache(raw_events: Any) -> List[TaskHistoryEvent]:
    if not isinstance(raw_events, list):
        return []
    out: List[TaskHistoryEvent] = []
    for entry in raw_events:
        if not isinstance(entry, dict):
            continue
        out.append(
            TaskHistoryEvent(
                ts=_parse_iso(entry.get("ts")),
                kind=str(entry.get("kind") or "note"),
                title=str(entry.get("title") or "-"),
                summary=str(entry.get("summary") or ""),
                source=str(entry.get("source") or "unknown"),
                confidence=str(entry.get("confidence") or "low"),
            )
        )
    return out


def _write_cache(path: Path, result: SessionHistoryResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "parser_version": PARSER_VERSION,
        "session_key": result.session_key,
        "session_id": result.session_id,
        "session_file": str(result.session_file),
        "generated_at": _dt_to_iso(result.generated_at),
        "file_size": result.file_size,
        "file_mtime": result.file_mtime,
        "file_inode": result.file_inode,
        "scan_offset": result.scan_offset,
        "header_session_id": result.header_session_id,
        "events": [
            {
                "ts": _dt_to_iso(event.ts),
                "kind": event.kind,
                "title": event.title,
                "summary": event.summary,
                "source": event.source,
                "confidence": event.confidence,
            }
            for event in result.events
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_header_session_id(path: Path) -> Optional[str]:
    try:
        with path.open("rb") as fh:
            first = fh.readline()
    except Exception:
        return None
    if not first:
        return None
    try:
        obj = json.loads(first.decode("utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("type") != "session":
        return None
    raw = obj.get("id")
    return str(raw) if isinstance(raw, str) and raw else None


def _scan_transcript_for_events(
    path: Path,
    *,
    start_offset: int,
    now: Optional[datetime],
    max_days: int,
) -> Tuple[List[TaskHistoryEvent], int]:
    now_dt = now or _now_utc()
    cutoff = now_dt - timedelta(days=max(1, max_days))
    out: List[TaskHistoryEvent] = []
    with path.open("rb") as fh:
        fh.seek(max(0, start_offset))
        while True:
            line = fh.readline()
            if not line:
                break
            scan_offset = fh.tell()
            if not line.strip():
                continue
            try:
                obj = json.loads(line.decode("utf-8", errors="replace"))
            except Exception:
                continue
            parsed = _events_from_entry(obj, cutoff=cutoff)
            if parsed:
                out.extend(parsed)
    out = _merge_history_events([], out, now=now_dt, max_days=max_days)
    return out, scan_offset if "scan_offset" in locals() else start_offset


def _events_from_entry(obj: Dict[str, Any], *, cutoff: datetime) -> List[TaskHistoryEvent]:
    if not isinstance(obj, dict):
        return []
    ts = _parse_iso(obj.get("timestamp"))
    if ts and ts < cutoff:
        return []

    entry_type = obj.get("type")
    if entry_type == "compaction":
        return [
            TaskHistoryEvent(
                ts=ts,
                kind="note",
                title="Session compacted",
                summary="Transcript compaction completed.",
                source="system",
                confidence="medium",
            )
        ]
    if entry_type != "message":
        return []

    msg = obj.get("message")
    if not isinstance(msg, dict):
        return []
    role = str(msg.get("role") or "")
    content = msg.get("content")

    if role == "user":
        raw = _extract_text(content, max_chars=8000)
        if _is_internal_user_text(raw):
            actual = _extract_inbound_from_internal_wrapper(raw)
            if actual:
                preview = _clean_preview(actual)
                return [
                    TaskHistoryEvent(
                        ts=ts,
                        kind="started",
                        title=_title_from_text(preview),
                        summary=_summary_from_text(preview),
                        source="user",
                        confidence="high",
                    )
                ]
            cleaned = _clean_preview(raw)
            if cleaned.startswith("System:"):
                return [
                    TaskHistoryEvent(
                        ts=ts,
                        kind="note",
                        title=_title_from_text(cleaned),
                        summary=_summary_from_text(cleaned),
                        source="system",
                        confidence="medium",
                    )
                ]
            return []
        preview = _clean_preview(raw)
        if not preview:
            return []
        return [
            TaskHistoryEvent(
                ts=ts,
                kind="started",
                title=_title_from_text(preview),
                summary=_summary_from_text(preview),
                source="user",
                confidence="high",
            )
        ]

    if role == "assistant":
        preview = _clean_preview(_extract_text(content, max_chars=800))
        thinking = _clean_preview(_extract_thinking(content, max_chars=300))
        tool_calls = _extract_tool_call_names(content)
        events: List[TaskHistoryEvent] = []
        if tool_calls:
            names = ", ".join(tool_calls[:3])
            events.append(
                TaskHistoryEvent(
                    ts=ts,
                    kind="working",
                    title=f"Tool call: {names}",
                    summary=_summary_from_text(preview or names),
                    source="tool_call",
                    confidence="high",
                )
            )
        if preview:
            kind, confidence = _classify_assistant_text(preview)
            events.append(
                TaskHistoryEvent(
                    ts=ts,
                    kind=kind,
                    title=_title_from_text(preview),
                    summary=_summary_from_text(preview),
                    source="assistant",
                    confidence=confidence,
                )
            )
        elif thinking:
            events.append(
                TaskHistoryEvent(
                    ts=ts,
                    kind="working",
                    title="Assistant reasoning",
                    summary=_summary_from_text(thinking),
                    source="thinking",
                    confidence="low",
                )
            )
        return events

    if role == "toolResult":
        preview = _clean_preview(_extract_text(content, max_chars=800))
        tool_name = str(msg.get("toolName") or "tool").strip() or "tool"
        is_error = bool(msg.get("isError", False))
        kind = "blocked" if is_error else "working"
        title = f"{'Tool error' if is_error else 'Tool result'}: {tool_name}"
        return [
            TaskHistoryEvent(
                ts=ts,
                kind=kind,
                title=title,
                summary=_summary_from_text(preview or tool_name),
                source="tool_result",
                confidence="high" if is_error else "medium",
            )
        ]

    return []


def _classify_assistant_text(text: str) -> Tuple[str, str]:
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(text):
            return "blocked", "high"
    for pattern in _DONE_PATTERNS:
        if pattern.search(text):
            return "done", "high"
    for pattern in _WORKING_PATTERNS:
        if pattern.search(text):
            return "working", "medium"
    return "note", "low"


def _merge_history_events(
    base: Sequence[TaskHistoryEvent],
    extra: Sequence[TaskHistoryEvent],
    *,
    now: Optional[datetime],
    max_days: int,
) -> List[TaskHistoryEvent]:
    now_dt = now or _now_utc()
    cutoff = now_dt - timedelta(days=max(1, max_days))
    merged = [event for event in list(base) + list(extra) if event.ts is None or event.ts >= cutoff]
    merged.sort(key=lambda ev: ev.ts or datetime.min.replace(tzinfo=timezone.utc))

    out: List[TaskHistoryEvent] = []
    for event in merged:
        if not out:
            out.append(event)
            continue
        prev = out[-1]
        if _should_fold(prev, event):
            out[-1] = _pick_better_event(prev, event)
        else:
            out.append(event)

    if len(out) > MAX_CACHE_EVENTS:
        out = out[-MAX_CACHE_EVENTS:]
    out.sort(key=lambda ev: ev.ts or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def _should_fold(left: TaskHistoryEvent, right: TaskHistoryEvent) -> bool:
    if left.kind != right.kind:
        return False
    if left.source != right.source:
        return False
    if left.ts and right.ts:
        delta = abs((right.ts - left.ts).total_seconds())
        if delta > 120:
            return False
    if left.title == right.title:
        return True
    if left.kind == "working" and left.source in ("tool_call", "tool_result", "thinking", "assistant"):
        return True
    return False


def _pick_better_event(left: TaskHistoryEvent, right: TaskHistoryEvent) -> TaskHistoryEvent:
    if _event_rank(right.kind) > _event_rank(left.kind):
        return right
    if len(right.summary or "") >= len(left.summary or ""):
        return right
    return left
