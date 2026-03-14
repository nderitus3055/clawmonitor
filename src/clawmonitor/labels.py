from __future__ import annotations

from typing import Optional

from .session_store import SessionMeta


def _id_from_key_tail(session_key: str) -> Optional[str]:
    key = (session_key or "").strip()
    if not key:
        return None
    parts = key.split(":")
    if parts:
        last = parts[-1].strip()
        return last or None
    return None


def _looks_like_external_id(channel: Optional[str], tail: str) -> bool:
    ch = (channel or "").strip()
    t = (tail or "").strip()
    if not t:
        return False
    if ch == "feishu":
        return t.startswith(("ou_", "oc_", "om_"))
    if ch == "telegram":
        return t.isdigit() and len(t) >= 5
    # Generic fallback: long opaque-ish ids.
    if len(t) >= 12 and any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
        return True
    return False


def session_display_label(label_map: dict[str, str], meta: SessionMeta) -> Optional[str]:
    """
    Resolve a human-friendly label for a session.

    Label lookup precedence:
      1) labels[\"sessionKey:<full sessionKey>\"] — exact mapping
      2) labels[\"target:<channel>:<to>\"] — delivery target mapping (meta.to)
      3) labels[\"id:<channel>:<id>\"] — id tail mapping (last key segment)
      4) meta.origin_label — if available (best-effort)
    """
    key = (meta.key or "").strip()
    if key:
        v = label_map.get(f"sessionKey:{key}")
        if v:
            return v

    chan = (meta.channel or "").strip() or None
    if chan and meta.to:
        v = label_map.get(f"target:{chan}:{meta.to}")
        if v:
            return v

    if chan and key:
        tail = _id_from_key_tail(key)
        if tail and _looks_like_external_id(chan, tail):
            v = label_map.get(f"id:{chan}:{tail}")
            if v:
                return v

    # Only use origin_label as a display name on channels where it is known to
    # be descriptive (Telegram often includes username + id). For other
    # channels this field is frequently just an opaque id or an internal label.
    if meta.origin_label and (meta.channel or "").strip() == "telegram":
        raw = meta.origin_label.strip()
        if not raw:
            return None
        if any(ch in raw for ch in (" ", "@")):
            return raw
    return None


def has_user_label(label_map: dict[str, str], meta: SessionMeta) -> bool:
    """
    True if the user configured a label that could match this session.

    This ignores channel-provided origin labels.
    """
    key = (meta.key or "").strip()
    if key and f"sessionKey:{key}" in label_map:
        return True
    chan = (meta.channel or "").strip() or None
    if chan and meta.to and f"target:{chan}:{meta.to}" in label_map:
        return True
    if chan and key:
        tail = _id_from_key_tail(key)
        if tail and _looks_like_external_id(chan, tail) and f"id:{chan}:{tail}" in label_map:
            return True
    return False
