from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any


MESSAGE_TYPE_MAP = {
    "chat": "text",
    "text": "text",
    "image": "image",
    "ptt": "audio",
    "audio": "audio",
    "voice": "audio",
    "document": "document",
    "video": "video",
    "sticker": "image",
}


def _dig(data: dict[str, Any], *path: str) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first(*values: Any, default: str = "") -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _as_iso_timestamp(value: Any) -> str:
    if value in (None, ""):
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds = seconds / 1000
        return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return _as_iso_timestamp(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        except ValueError:
            return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _message_id(payload: dict[str, Any], message: dict[str, Any], normalized_seed: dict[str, Any]) -> str:
    value = _first(
        message.get("id"),
        _dig(message, "_data", "id", "id"),
        _dig(message, "key", "id"),
        _dig(payload, "id"),
        default="",
    )
    if isinstance(value, dict):
        value = _first(value.get("id"), value.get("_serialized"), default="")
    if value:
        return str(value)
    raw = json.dumps(normalized_seed, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def normalize_waha_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize common WAHA webhook shapes into the platform message contract."""
    message = payload.get("payload") or payload.get("message") or payload.get("data") or payload
    if not isinstance(message, dict):
        message = {}

    session = str(_first(payload.get("session"), message.get("session"), default=""))
    chat_id = _first(
        message.get("chatId"),
        message.get("from"),
        _dig(message, "chat", "id"),
        _dig(message, "key", "remoteJid"),
        default="",
    )
    author = _first(
        message.get("author"),
        message.get("participant"),
        _dig(message, "_data", "author"),
        _dig(message, "sender", "id"),
        _dig(message, "key", "participant"),
        default="",
    )
    sender_id = str(_first(author, message.get("from"), default=""))
    group_id = str(chat_id if str(chat_id).endswith("@g.us") else _first(message.get("groupId"), default=""))
    if group_id and sender_id == group_id and author:
        sender_id = str(author)

    group_name = str(
        _first(
            message.get("chatName"),
            message.get("groupName"),
            _dig(message, "chat", "name"),
            _dig(message, "_data", "chatName"),
            default="",
        )
    )
    sender_name = str(
        _first(
            message.get("senderName"),
            message.get("pushName"),
            message.get("notifyName"),
            _dig(message, "sender", "name"),
            _dig(message, "_data", "notifyName"),
            default="",
        )
    )

    raw_type = str(_first(message.get("type"), message.get("messageType"), default="text")).lower()
    message_type = MESSAGE_TYPE_MAP.get(raw_type, raw_type or "text")
    text = str(_first(message.get("body"), message.get("text"), message.get("caption"), default=""))
    media = message.get("media") if isinstance(message.get("media"), dict) else {}
    media_url = str(
        _first(
            message.get("mediaUrl"),
            message.get("downloadUrl"),
            media.get("url") if media else "",
            media.get("downloadUrl") if media else "",
            default="",
        )
    )
    has_media = bool(_first(message.get("hasMedia"), media_url, default=False))
    timestamp = _as_iso_timestamp(_first(message.get("timestamp"), message.get("t"), payload.get("timestamp"), default=""))

    seed = {
        "source": "waha",
        "session": session,
        "group_id": group_id,
        "sender_id": sender_id,
        "text": text,
        "timestamp": timestamp,
    }

    return {
        "source": "waha",
        "session": session,
        "group_id": group_id,
        "group_name": group_name,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "message_id": _message_id(payload, message, seed),
        "message_type": message_type,
        "text": text,
        "timestamp": timestamp,
        "has_media": has_media,
        "media_url": media_url,
        "raw_payload": payload,
    }

