from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import APP_NAME, CHAT_RETENTION_DAYS, READ_ONLY_WARNING, WAHA_SERVER_URL
from .database import apply_retention, execute_query, get_connection, init_db
from .ingest import ingest_waha_payload
from .supabase_store import get_supabase_status, sync_all_sqlite_to_supabase


app = FastAPI(title=APP_NAME, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()
    apply_retention()


@app.get("/health")
def health() -> dict[str, object]:
    init_db()
    apply_retention()
    return {
        "ok": True,
        "app": APP_NAME,
        "read_only": True,
        "chat_retention_days": CHAT_RETENTION_DAYS,
        "supabase": get_supabase_status(),
        "warning": READ_ONLY_WARNING,
    }


@app.post("/api/waha/webhook")
async def waha_webhook(payload: dict) -> dict[str, object]:
    try:
        result = ingest_waha_payload(payload)
    except Exception as exc:  # pragma: no cover - returned for webhook operator visibility
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "accepted": True,
        "read_only": True,
        "raw_message_id": result["raw_message_id"],
        "job_id": result["job_id"],
        "alerts_created": result["alerts_created"],
        "normalized": result["normalized"],
        "confidence": result["extraction"].get("confidence_label"),
        "supabase_sync": result.get("supabase_sync"),
    }


@app.get("/api/waha/status")
def waha_status() -> dict[str, object]:
    init_db()
    apply_retention()
    rows = execute_query(
        """
        SELECT
          (SELECT COUNT(*) FROM raw_messages WHERE substr(COALESCE(timestamp, created_at), 1, 10)=date('now')) AS total_today,
          (SELECT MAX(created_at) FROM raw_messages) AS last_received_webhook,
          (SELECT COUNT(*) FROM groups) AS groups_detected,
          (SELECT COUNT(*) FROM raw_messages) AS total_messages
        """
    )
    groups = execute_query("SELECT group_id, group_name, last_seen, message_count FROM groups ORDER BY last_seen DESC")
    metrics = rows[0] if rows else {}
    return {
        "waha_server_url": WAHA_SERVER_URL,
        "session_status": "configured_in_waha",
        "webhook_health_status": "healthy" if metrics.get("total_messages", 0) is not None else "unknown",
        "last_received_webhook": metrics.get("last_received_webhook"),
        "total_messages_received_today": metrics.get("total_today", 0),
        "groups_detected": groups,
        "chat_retention_days": CHAT_RETENTION_DAYS,
        "supabase": get_supabase_status(),
        "read_only": True,
        "warning": READ_ONLY_WARNING,
    }


@app.get("/api/supabase/status")
def supabase_status() -> dict[str, object]:
    return get_supabase_status()


@app.post("/api/supabase/sync")
def supabase_sync() -> dict[str, object]:
    return sync_all_sqlite_to_supabase()


@app.get("/api/messages")
def messages(limit: int = 200) -> list[dict[str, object]]:
    return execute_query(
        "SELECT * FROM raw_messages ORDER BY COALESCE(timestamp, created_at) DESC LIMIT ?",
        (min(limit, 1000),),
    )


@app.get("/api/jobs")
def jobs() -> list[dict[str, object]]:
    return execute_query("SELECT * FROM jobs ORDER BY updated_at DESC")


@app.get("/api/alerts")
def alerts(status: str = "open") -> list[dict[str, object]]:
    if status == "all":
        return execute_query("SELECT * FROM alerts ORDER BY created_at DESC")
    return execute_query("SELECT * FROM alerts WHERE status=? ORDER BY created_at DESC", (status,))


@app.get("/api/db/stats")
def db_stats() -> dict[str, int]:
    init_db()
    tables = [
        "raw_messages",
        "groups",
        "technicians",
        "jobs",
        "job_events",
        "parts",
        "payments",
        "media_files",
        "alerts",
        "audit_log",
    ]
    stats: dict[str, int] = {}
    with get_connection() as conn:
        for table in tables:
            stats[table] = int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])
    return stats
