from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Optional

from .openclaw_cli import gateway_call


@dataclass(frozen=True)
class SessionUsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    message_count: int = 0
    error_count: int = 0


@dataclass(frozen=True)
class SessionUsageRangeEntry:
    session_key: str
    agent_id: Optional[str]
    model_provider: Optional[str]
    model_name: Optional[str]
    totals: SessionUsageTotals
    updated_at_ms: Optional[int]


@dataclass(frozen=True)
class SessionUsageRangeResult:
    range_days: int
    start_date: str
    end_date: str
    generated_at: datetime
    sessions_by_key: Dict[str, SessionUsageRangeEntry]
    agent_totals: Dict[str, SessionUsageTotals]
    updated_at_ms: Optional[int]


def _safe_int(value: object) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except Exception:
        return 0


def _safe_float(value: object) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def usage_range_dates(days: int, *, today: Optional[date] = None) -> tuple[str, str]:
    end = today or date.today()
    start = end - timedelta(days=max(1, days) - 1)
    return start.isoformat(), end.isoformat()


def history_usage_is_stale(last_loaded_at: Optional[float], *, now_ts: Optional[float] = None, ttl_seconds: float = 300.0) -> bool:
    if last_loaded_at is None:
        return True
    now_value = now_ts if now_ts is not None else datetime.now().timestamp()
    return max(0.0, now_value - last_loaded_at) > ttl_seconds


def fetch_sessions_usage_range(openclaw_bin: str, *, days: int, limit: int = 1000, timeout_ms: int = 20000) -> SessionUsageRangeResult:
    start_date, end_date = usage_range_dates(days)
    res = gateway_call(
        openclaw_bin,
        "sessions.usage",
        params={
            "startDate": start_date,
            "endDate": end_date,
            "limit": limit,
            "includeContextWeight": False,
        },
        timeout_ms=timeout_ms,
    )
    if not res.ok or not isinstance(res.data, dict):
        detail = res.raw_stderr.strip() or res.raw_stdout.strip() or f"rc={res.returncode}"
        raise RuntimeError(f"sessions.usage failed: {detail[:240]}")

    doc = res.data
    rows = doc.get("sessions")
    if not isinstance(rows, list):
        raise RuntimeError("sessions.usage returned invalid payload")

    sessions_by_key: Dict[str, SessionUsageRangeEntry] = {}
    agent_totals: Dict[str, SessionUsageTotals] = {}

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        key = raw.get("key")
        if not isinstance(key, str) or not key:
            continue
        agent_id = raw.get("agentId") if isinstance(raw.get("agentId"), str) else None
        model_provider = raw.get("modelProvider") if isinstance(raw.get("modelProvider"), str) else None
        model_name = raw.get("model") if isinstance(raw.get("model"), str) else None
        updated_at_ms = _safe_int(raw.get("updatedAt")) or None
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        msg = usage.get("messageCounts") if isinstance(usage.get("messageCounts"), dict) else {}
        totals = SessionUsageTotals(
            input_tokens=_safe_int(usage.get("input")),
            output_tokens=_safe_int(usage.get("output")),
            cache_read_tokens=_safe_int(usage.get("cacheRead")),
            cache_write_tokens=_safe_int(usage.get("cacheWrite")),
            total_tokens=_safe_int(usage.get("totalTokens")),
            total_cost=_safe_float(usage.get("totalCost")),
            message_count=_safe_int(msg.get("total")),
            error_count=_safe_int(msg.get("errors")),
        )
        sessions_by_key[key] = SessionUsageRangeEntry(
            session_key=key,
            agent_id=agent_id,
            model_provider=model_provider,
            model_name=model_name,
            totals=totals,
            updated_at_ms=updated_at_ms,
        )
        if agent_id:
            cur = agent_totals.get(agent_id)
            if cur is None:
                agent_totals[agent_id] = totals
            else:
                agent_totals[agent_id] = SessionUsageTotals(
                    input_tokens=cur.input_tokens + totals.input_tokens,
                    output_tokens=cur.output_tokens + totals.output_tokens,
                    cache_read_tokens=cur.cache_read_tokens + totals.cache_read_tokens,
                    cache_write_tokens=cur.cache_write_tokens + totals.cache_write_tokens,
                    total_tokens=cur.total_tokens + totals.total_tokens,
                    total_cost=cur.total_cost + totals.total_cost,
                    message_count=cur.message_count + totals.message_count,
                    error_count=cur.error_count + totals.error_count,
                )

    updated_at_raw = doc.get("updatedAt")
    updated_at_ms = _safe_int(updated_at_raw) or None
    return SessionUsageRangeResult(
        range_days=max(1, int(days)),
        start_date=start_date,
        end_date=end_date,
        generated_at=datetime.now(),
        sessions_by_key=sessions_by_key,
        agent_totals=agent_totals,
        updated_at_ms=updated_at_ms,
    )
