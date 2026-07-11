from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from urllib import error, parse, request

from .config import (
    SUPABASE_ENABLED,
    SUPABASE_KEY,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from .database import execute_query, get_connection


UPSERT_CONFLICTS = {
    "raw_messages": "source,session,message_id",
    "groups": "group_id",
    "technicians": "sender_id",
    "jobs": "job_id",
    "job_events": "id",
    "parts": "id",
    "payments": "id",
    "media_files": "id",
    "alerts": "id",
    "settings": "key",
    "audit_log": "id",
}


def supabase_configured() -> bool:
    return bool(SUPABASE_ENABLED and SUPABASE_URL and SUPABASE_KEY)


def supabase_mode_label() -> str:
    if not SUPABASE_ENABLED:
        return "disabled"
    if not SUPABASE_URL:
        return "missing SUPABASE_URL"
    if not SUPABASE_KEY:
        return "missing Supabase key"
    return "enabled"


def _headers(prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _url(table: str, params: dict[str, str] | None = None) -> str:
    base = f"{SUPABASE_URL}/rest/v1/{parse.quote(table)}"
    if not params:
        return base
    return f"{base}?{parse.urlencode(params)}"


def _request_json(
    method: str,
    table: str,
    payload: Any | None = None,
    params: dict[str, str] | None = None,
    prefer: str | None = None,
    timeout: int = 15,
) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req = request.Request(_url(table, params), data=data, headers=_headers(prefer), method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else []
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase {method} {table} failed: {exc.code} {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase connection failed: {exc.reason}") from exc


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: _clean_value(value) for key, value in row.items()}
    if "has_media" in cleaned and cleaned["has_media"] is not None:
        cleaned["has_media"] = bool(cleaned["has_media"])
    return cleaned


def upsert_rows(table: str, rows: list[dict[str, Any]]) -> None:
    if not supabase_configured() or not rows:
        return
    params: dict[str, str] = {}
    conflict = UPSERT_CONFLICTS.get(table)
    if conflict:
        params["on_conflict"] = conflict
    payload = [_clean_row(row) for row in rows]
    _request_json(
        "POST",
        table,
        payload=payload,
        params=params,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def select_rows(table: str, limit: int = 1000, order: str | None = None, desc: bool = True) -> list[dict[str, Any]]:
    if not supabase_configured():
        return []
    params = {"select": "*", "limit": str(limit)}
    if order:
        direction = "desc" if desc else "asc"
        params["order"] = f"{order}.{direction}"
    return _request_json("GET", table, params=params)


def count_rows(table: str) -> int | None:
    if not supabase_configured():
        return None
    req = request.Request(
        _url(table, {"select": "id", "limit": "0"}),
        headers=_headers("count=exact"),
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            content_range = response.headers.get("content-range", "")
    except OSError:
        return None
    if "/" not in content_range:
        return None
    total = content_range.rsplit("/", 1)[-1]
    return int(total) if total.isdigit() else None


def get_supabase_status() -> dict[str, Any]:
    total = count_rows("raw_messages") if supabase_configured() else None
    return {
        "enabled": SUPABASE_ENABLED,
        "configured": supabase_configured(),
        "mode": supabase_mode_label(),
        "url": SUPABASE_URL,
        "uses_service_role_key": bool(SUPABASE_SERVICE_ROLE_KEY),
        "raw_messages_count": total,
    }


def _sqlite_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return execute_query(sql, params)


def sync_message_bundle_to_supabase(raw_message_id: int) -> dict[str, Any]:
    if not supabase_configured():
        return {"enabled": SUPABASE_ENABLED, "configured": False, "synced": False}

    raw_rows = _sqlite_rows("SELECT * FROM raw_messages WHERE id=?", (raw_message_id,))
    if not raw_rows:
        return {"enabled": True, "configured": True, "synced": False, "reason": "raw message missing"}

    raw = raw_rows[0]
    job_event_rows = _sqlite_rows("SELECT * FROM job_events WHERE raw_message_id=?", (raw_message_id,))
    job_ids = sorted({row["job_id"] for row in job_event_rows if row.get("job_id")})
    if job_ids:
        placeholders = ",".join("?" for _ in job_ids)
        jobs = _sqlite_rows(f"SELECT * FROM jobs WHERE job_id IN ({placeholders})", tuple(job_ids))
    else:
        jobs = []

    group_id = raw.get("group_id") or ""
    sender_id = raw.get("sender_id") or ""
    groups = _sqlite_rows("SELECT * FROM groups WHERE group_id=?", (group_id,)) if group_id else []
    technicians = _sqlite_rows("SELECT * FROM technicians WHERE sender_id=?", (sender_id,)) if sender_id else []
    parts = _sqlite_rows("SELECT * FROM parts WHERE raw_message_id=?", (raw_message_id,))
    payments = _sqlite_rows("SELECT * FROM payments WHERE raw_message_id=?", (raw_message_id,))
    media = _sqlite_rows("SELECT * FROM media_files WHERE raw_message_id=?", (raw_message_id,))
    alerts = _sqlite_rows("SELECT * FROM alerts WHERE raw_message_id=?", (raw_message_id,))
    audit = _sqlite_rows(
        "SELECT * FROM audit_log WHERE entity_type='raw_message' AND entity_id=?",
        (str(raw_message_id),),
    )

    synced_tables: list[str] = []
    try:
        for table, rows in [
            ("groups", groups),
            ("technicians", technicians),
            ("raw_messages", raw_rows),
            ("jobs", jobs),
            ("job_events", job_event_rows),
            ("parts", parts),
            ("payments", payments),
            ("media_files", media),
            ("alerts", alerts),
            ("audit_log", audit),
        ]:
            upsert_rows(table, rows)
            if rows:
                synced_tables.append(table)
    except Exception as exc:
        return {
            "enabled": True,
            "configured": True,
            "synced": False,
            "error": str(exc),
            "tables_attempted": synced_tables,
        }

    return {
        "enabled": True,
        "configured": True,
        "synced": True,
        "tables": synced_tables,
        "synced_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def sync_all_sqlite_to_supabase() -> dict[str, Any]:
    if not supabase_configured():
        return {"enabled": SUPABASE_ENABLED, "configured": False, "synced": False}
    table_order = [
        "groups",
        "technicians",
        "raw_messages",
        "jobs",
        "job_events",
        "parts",
        "payments",
        "media_files",
        "alerts",
        "settings",
        "audit_log",
    ]
    counts: dict[str, int] = {}
    try:
        with get_connection() as conn:
            for table in table_order:
                rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
                upsert_rows(table, rows)
                counts[table] = len(rows)
    except Exception as exc:
        return {"enabled": True, "configured": True, "synced": False, "error": str(exc), "counts": counts}
    return {"enabled": True, "configured": True, "synced": True, "counts": counts}
