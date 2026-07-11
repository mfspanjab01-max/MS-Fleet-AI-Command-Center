from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .config import CHAT_RETENTION_DAYS, DATA_DIR, DB_PATH


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) or {} for row in rows]


def init_db(db_path: str | Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                session TEXT,
                group_id TEXT,
                group_name TEXT,
                sender_id TEXT,
                sender_name TEXT,
                message_id TEXT NOT NULL,
                message_type TEXT,
                original_text TEXT,
                detected_language TEXT,
                english_translation TEXT,
                timestamp TEXT,
                has_media INTEGER NOT NULL DEFAULT 0,
                media_url TEXT,
                raw_payload TEXT NOT NULL,
                processed_status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, session, message_id)
            );

            CREATE TABLE IF NOT EXISTS groups (
                group_id TEXT PRIMARY KEY,
                group_name TEXT,
                source TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS technicians (
                sender_id TEXT PRIMARY KEY,
                sender_name TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                unit_number TEXT,
                customer_name TEXT,
                technician_name TEXT,
                group_name TEXT,
                complaint TEXT,
                diagnosis TEXT,
                repair_performed TEXT,
                parts_used TEXT,
                part_number TEXT,
                quantity REAL,
                status TEXT,
                payment_status TEXT,
                invoice_amount REAL,
                repair_category TEXT,
                confidence_level TEXT,
                confidence_reason TEXT,
                missing_information TEXT,
                last_update_time TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                raw_message_id INTEGER NOT NULL,
                event_type TEXT,
                summary TEXT,
                extraction_json TEXT NOT NULL,
                confidence_level TEXT,
                confidence_reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id),
                FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );

            CREATE TABLE IF NOT EXISTS parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                raw_message_id INTEGER NOT NULL,
                part_name TEXT,
                part_number TEXT,
                quantity REAL,
                confidence_level TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id),
                FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                raw_message_id INTEGER NOT NULL,
                unit_number TEXT,
                amount REAL,
                currency TEXT DEFAULT 'USD',
                status TEXT,
                payer_name TEXT,
                confidence_level TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id),
                FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );

            CREATE TABLE IF NOT EXISTS media_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_message_id INTEGER NOT NULL,
                job_id TEXT,
                media_type TEXT,
                media_url TEXT,
                local_path TEXT,
                ocr_text TEXT,
                processed_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id),
                FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                raw_message_id INTEGER,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                confidence_level TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id),
                FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_raw_messages_timestamp ON raw_messages(timestamp);
            CREATE INDEX IF NOT EXISTS idx_raw_messages_group ON raw_messages(group_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_unit ON jobs(unit_number);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_payment_status ON jobs(payment_status);
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
            CREATE INDEX IF NOT EXISTS idx_payments_unit ON payments(unit_number);
            """
        )


def apply_retention(days: int = CHAT_RETENTION_DAYS, db_path: str | Path | None = None) -> dict[str, int]:
    """Keep local WhatsApp/chat-derived records inside the configured retention window."""
    if days <= 0:
        return {"retention_days": days, "deleted_raw_messages": 0, "deleted_jobs": 0}

    cutoff_modifier = f"-{int(days)} days"
    old_raw_where = """
        id IN (
            SELECT id FROM raw_messages
            WHERE datetime(REPLACE(substr(COALESCE(timestamp, created_at), 1, 19), 'T', ' '))
                < datetime('now', ?)
        )
    """
    old_job_where = """
        job_id IN (
            SELECT job_id FROM jobs
            WHERE datetime(REPLACE(substr(COALESCE(last_update_time, updated_at, created_at), 1, 19), 'T', ' '))
                < datetime('now', ?)
        )
    """
    with get_connection(db_path) as conn:
        deleted_raw = int(
            conn.execute(
                f"SELECT COUNT(*) AS c FROM raw_messages WHERE {old_raw_where}",
                (cutoff_modifier,),
            ).fetchone()["c"]
        )
        deleted_jobs = int(
            conn.execute(
                f"SELECT COUNT(*) AS c FROM jobs WHERE {old_job_where}",
                (cutoff_modifier,),
            ).fetchone()["c"]
        )
        for table in ("alerts", "media_files", "payments", "parts", "job_events"):
            conn.execute(
                f"DELETE FROM {table} WHERE raw_message_id IN (SELECT id FROM raw_messages WHERE {old_raw_where})",
                (cutoff_modifier,),
            )
        for table in ("alerts", "media_files", "payments", "parts", "job_events"):
            conn.execute(
                f"DELETE FROM {table} WHERE job_id IN (SELECT job_id FROM jobs WHERE {old_job_where})",
                (cutoff_modifier,),
            )
        conn.execute(f"DELETE FROM jobs WHERE {old_job_where}", (cutoff_modifier,))
        conn.execute(f"DELETE FROM raw_messages WHERE {old_raw_where}", (cutoff_modifier,))
        conn.execute(
            """
            DELETE FROM audit_log
            WHERE datetime(REPLACE(substr(created_at, 1, 19), 'T', ' ')) < datetime('now', ?)
            """,
            (cutoff_modifier,),
        )
        conn.execute("DELETE FROM groups")
        conn.execute(
            """
            INSERT INTO groups(group_id, group_name, source, first_seen, last_seen, message_count)
            SELECT group_id, MAX(group_name), MAX(source), MIN(created_at), MAX(created_at), COUNT(*)
            FROM raw_messages
            WHERE group_id IS NOT NULL AND group_id != ''
            GROUP BY group_id
            """
        )
        conn.execute("DELETE FROM technicians")
        conn.execute(
            """
            INSERT INTO technicians(sender_id, sender_name, first_seen, last_seen, message_count)
            SELECT sender_id, MAX(sender_name), MIN(created_at), MAX(created_at), COUNT(*)
            FROM raw_messages
            WHERE sender_id IS NOT NULL AND sender_id != ''
            GROUP BY sender_id
            """
        )
    return {"retention_days": days, "deleted_raw_messages": deleted_raw, "deleted_jobs": deleted_jobs}


def execute_query(
    sql: str,
    params: tuple[Any, ...] = (),
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        return rows_to_dicts(conn.execute(sql, params).fetchall())
