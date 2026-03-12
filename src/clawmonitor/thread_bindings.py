from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class TelegramThreadBinding:
    account_id: str
    conversation_id: str
    target_session_key: str
    target_kind: Optional[str]
    agent_id: Optional[str]
    label: Optional[str]
    bound_at_ms: Optional[int]
    last_activity_at_ms: Optional[int]


def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def load_telegram_thread_bindings(openclaw_root: Path, account_id: str = "default") -> Dict[str, TelegramThreadBinding]:
    """
    Load Telegram thread bindings (conversation -> target session) stored by OpenClaw.

    File: <openclaw_root>/telegram/thread-bindings-<accountId>.json
    """
    path = openclaw_root / "telegram" / f"thread-bindings-{account_id}.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(doc, dict):
        return {}
    bindings = doc.get("bindings")
    if not isinstance(bindings, list):
        return {}

    out: Dict[str, TelegramThreadBinding] = {}
    for b in bindings:
        if not isinstance(b, dict):
            continue
        conv = b.get("conversationId")
        target = b.get("targetSessionKey")
        if not isinstance(conv, str) or not isinstance(target, str) or not conv.strip() or not target.strip():
            continue
        out[conv] = TelegramThreadBinding(
            account_id=str(b.get("accountId") or account_id),
            conversation_id=conv,
            target_session_key=target,
            target_kind=str(b.get("targetKind")) if b.get("targetKind") is not None else None,
            agent_id=str(b.get("agentId")) if b.get("agentId") is not None else None,
            label=str(b.get("label")) if b.get("label") is not None else None,
            bound_at_ms=_safe_int(b.get("boundAt")),
            last_activity_at_ms=_safe_int(b.get("lastActivityAt")),
        )
    return out

