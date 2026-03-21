from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clawmonitor.session_history import filter_history_events, load_session_history


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _header(session_id: str) -> dict:
    return {
        "type": "session",
        "version": 3,
        "id": session_id,
        "timestamp": "2026-03-18T00:00:00.000Z",
        "cwd": "/tmp",
    }


def _msg(role: str, ts: str, content: list[dict], **extra: object) -> dict:
    message = {"role": role, "content": content, **extra}
    return {
        "type": "message",
        "id": f"{role}-{ts}",
        "parentId": None,
        "timestamp": ts,
        "message": message,
    }


def test_load_session_history_rebuilds_and_incrementally_updates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    session_file = tmp_path / "sessions" / "sess-1.jsonl"
    _write_jsonl(
        session_file,
        [
            _header("sess-1"),
            _msg("user", "2026-03-18T01:00:00.000Z", [{"type": "text", "text": "Hello from user"}]),
            _msg(
                "assistant",
                "2026-03-18T01:00:10.000Z",
                [
                    {"type": "text", "text": "当前进度：正在处理，下一步会继续扫描。"},
                    {"type": "toolCall", "name": "read", "arguments": {"path": "/tmp/a"}},
                ],
            ),
        ],
    )

    first = load_session_history(session_key="agent:main:main", session_id="sess-1", session_file=session_file)
    assert first.mode == "rebuild"
    assert any(event.kind == "started" for event in first.events)
    assert any(event.kind == "working" and "Tool call" in event.title for event in first.events)

    _append_jsonl(
        session_file,
        [
            _msg(
                "assistant",
                "2026-03-18T01:01:00.000Z",
                [{"type": "text", "text": "已完成，处理成功。"}],
                stopReason="stop",
            )
        ],
    )
    os.utime(session_file, None)

    second = load_session_history(session_key="agent:main:main", session_id="sess-1", session_file=session_file)
    assert second.mode == "incremental"
    assert any(event.kind == "done" and "已完成" in event.summary for event in second.events)

    third = load_session_history(session_key="agent:main:main", session_id="sess-1", session_file=session_file)
    assert third.mode == "hit"


def test_load_session_history_rebuilds_when_transcript_identity_changes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    session_file = tmp_path / "sessions" / "sess-2.jsonl"
    _write_jsonl(
        session_file,
        [
            _header("sess-2"),
            _msg("user", "2026-03-18T02:00:00.000Z", [{"type": "text", "text": "Start task"}]),
        ],
    )

    first = load_session_history(session_key="agent:main:main", session_id="sess-2", session_file=session_file)
    assert first.mode == "rebuild"

    _write_jsonl(
        session_file,
        [
            _header("sess-2-replaced"),
            _msg("assistant", "2026-03-18T02:05:00.000Z", [{"type": "text", "text": "BLOCKED: timeout"}]),
        ],
    )
    os.utime(session_file, None)

    second = load_session_history(session_key="agent:main:main", session_id="sess-2", session_file=session_file)
    assert second.mode == "rebuild"
    assert any(event.kind == "blocked" for event in second.events)


def test_filter_history_events_limits_days() -> None:
    now = datetime(2026, 3, 18, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        type("E", (), {"ts": now - timedelta(hours=2)})(),
        type("E", (), {"ts": now - timedelta(days=2)})(),
        type("E", (), {"ts": None})(),
    ]
    filtered = filter_history_events(events, days=1, now=now)
    assert len(filtered) == 2
