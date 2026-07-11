from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from .ai import extract_message
from .alerts import build_alerts
from .database import apply_retention, get_connection, init_db, now_utc, row_to_dict
from .supabase_store import sync_message_bundle_to_supabase
from .waha import normalize_waha_payload


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _job_id(unit_number: str, timestamp: str) -> str:
    day = (timestamp or now_utc())[:10].replace("-", "")
    cleaned = re.sub(r"[^A-Za-z0-9-]", "", unit_number.upper())
    return f"JOB-{cleaned}-{day}"


def _event_type(extraction: dict[str, Any], normalized: dict[str, Any]) -> str:
    if extraction.get("payment_amount") is not None or extraction.get("payment_status"):
        return "payment_update"
    if extraction.get("part_used"):
        return "part_update"
    if extraction.get("job_status"):
        return "status_update"
    if normalized.get("has_media"):
        return "media_update"
    return "message"


def _summary(extraction: dict[str, Any], normalized: dict[str, Any]) -> str:
    pieces = []
    for key, label in [
        ("unit_number", "Unit"),
        ("complaint", "Complaint"),
        ("diagnosis", "Diagnosis"),
        ("repair_performed", "Repair"),
        ("part_used", "Part"),
        ("job_status", "Status"),
        ("payment_status", "Payment"),
    ]:
        value = extraction.get(key)
        if value:
            pieces.append(f"{label}: {value}")
    if extraction.get("payment_amount") is not None:
        pieces.append(f"Amount: ${float(extraction['payment_amount']):,.2f}")
    return " | ".join(pieces) or (normalized.get("text", "")[:160] or "No text content")


def _merge_text(existing: str | None, new: str | None) -> str | None:
    if not new:
        return existing
    if not existing:
        return new
    if new.lower() in existing.lower():
        return existing
    return f"{existing}; {new}"


def _upsert_group(conn, normalized: dict[str, Any], now: str) -> None:
    group_id = normalized.get("group_id")
    if not group_id:
        return
    conn.execute(
        """
        INSERT INTO groups(group_id, group_name, source, first_seen, last_seen, message_count)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(group_id) DO UPDATE SET
            group_name=COALESCE(NULLIF(excluded.group_name, ''), groups.group_name),
            last_seen=excluded.last_seen,
            message_count=groups.message_count + 1
        """,
        (group_id, normalized.get("group_name"), normalized.get("source"), now, now),
    )


def _upsert_technician(conn, normalized: dict[str, Any], now: str) -> None:
    sender_id = normalized.get("sender_id")
    if not sender_id:
        return
    conn.execute(
        """
        INSERT INTO technicians(sender_id, sender_name, first_seen, last_seen, message_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(sender_id) DO UPDATE SET
            sender_name=COALESCE(NULLIF(excluded.sender_name, ''), technicians.sender_name),
            last_seen=excluded.last_seen,
            message_count=technicians.message_count + 1
        """,
        (sender_id, normalized.get("sender_name"), now, now),
    )


def _insert_raw_message(conn, normalized: dict[str, Any]) -> tuple[int, bool]:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO raw_messages(
            source, session, group_id, group_name, sender_id, sender_name, message_id,
            message_type, original_text, timestamp, has_media, media_url, raw_payload,
            processed_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'received')
        """,
        (
            normalized["source"],
            normalized["session"],
            normalized["group_id"],
            normalized["group_name"],
            normalized["sender_id"],
            normalized["sender_name"],
            normalized["message_id"],
            normalized["message_type"],
            normalized["text"],
            normalized["timestamp"],
            1 if normalized["has_media"] else 0,
            normalized["media_url"],
            _json(normalized["raw_payload"]),
        ),
    )
    row = conn.execute(
        "SELECT id FROM raw_messages WHERE source=? AND session=? AND message_id=?",
        (normalized["source"], normalized["session"], normalized["message_id"]),
    ).fetchone()
    return int(row["id"]), cursor.rowcount == 1


def _existing_ingest_result(conn, raw_message_id: int, normalized: dict[str, Any]) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT job_id, extraction_json, confidence_level
        FROM job_events
        WHERE raw_message_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (raw_message_id,),
    ).fetchone()
    if not row:
        return None
    job_id = row["job_id"]
    try:
        extraction = json.loads(row["extraction_json"])
    except json.JSONDecodeError:
        extraction = {"confidence_label": row["confidence_level"] or "Unconfirmed"}
    return {
        "ok": True,
        "duplicate": True,
        "raw_message_id": raw_message_id,
        "job_id": job_id,
        "normalized": normalized,
        "extraction": extraction,
        "alerts_created": 0,
        "read_only": True,
    }


def _find_latest_job(conn, unit_number: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM jobs WHERE unit_number=? ORDER BY updated_at DESC LIMIT 1",
        (unit_number,),
    ).fetchone()
    return row_to_dict(row)


def _payment_amounts(conn, job_id: str | None, unit_number: str | None) -> list[float]:
    if job_id:
        rows = conn.execute("SELECT amount FROM payments WHERE job_id=? AND amount IS NOT NULL", (job_id,)).fetchall()
    elif unit_number:
        rows = conn.execute("SELECT amount FROM payments WHERE unit_number=? AND amount IS NOT NULL", (unit_number,)).fetchall()
    else:
        rows = []
    return [float(row["amount"]) for row in rows]


def _upsert_job(conn, extraction: dict[str, Any], normalized: dict[str, Any], now: str) -> tuple[str | None, dict[str, Any] | None]:
    unit_number = extraction.get("unit_number") or ""
    if not unit_number:
        return None, None
    existing = _find_latest_job(conn, unit_number)
    job_id = existing["job_id"] if existing else _job_id(unit_number, normalized.get("timestamp", now))
    if not existing:
        conn.execute(
            """
            INSERT INTO jobs(
                job_id, unit_number, customer_name, technician_name, group_name, complaint,
                diagnosis, repair_performed, parts_used, part_number, quantity, status,
                payment_status, invoice_amount, repair_category, confidence_level,
                confidence_reason, missing_information, last_update_time, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                unit_number,
                extraction.get("customer_name"),
                extraction.get("technician_name") or normalized.get("sender_name"),
                normalized.get("group_name"),
                extraction.get("complaint"),
                extraction.get("diagnosis"),
                extraction.get("repair_performed"),
                extraction.get("part_used"),
                extraction.get("part_number"),
                extraction.get("quantity"),
                extraction.get("job_status") or "ongoing",
                extraction.get("payment_status") or "unknown",
                extraction.get("payment_amount"),
                extraction.get("repair_category"),
                extraction.get("confidence_label"),
                extraction.get("confidence_reason"),
                _json(extraction.get("missing_information", [])),
                normalized.get("timestamp") or now,
                now,
                now,
            ),
        )
        return job_id, None

    conn.execute(
        """
        UPDATE jobs SET
            customer_name=COALESCE(NULLIF(?, ''), customer_name),
            technician_name=COALESCE(NULLIF(?, ''), technician_name),
            group_name=COALESCE(NULLIF(?, ''), group_name),
            complaint=?,
            diagnosis=?,
            repair_performed=?,
            parts_used=?,
            part_number=COALESCE(NULLIF(?, ''), part_number),
            quantity=COALESCE(?, quantity),
            status=COALESCE(NULLIF(?, ''), status),
            payment_status=COALESCE(NULLIF(?, ''), payment_status),
            invoice_amount=COALESCE(?, invoice_amount),
            repair_category=COALESCE(NULLIF(?, ''), repair_category),
            confidence_level=?,
            confidence_reason=?,
            missing_information=?,
            last_update_time=?,
            updated_at=?
        WHERE job_id=?
        """,
        (
            extraction.get("customer_name"),
            extraction.get("technician_name") or normalized.get("sender_name"),
            normalized.get("group_name"),
            _merge_text(existing.get("complaint"), extraction.get("complaint")),
            _merge_text(existing.get("diagnosis"), extraction.get("diagnosis")),
            _merge_text(existing.get("repair_performed"), extraction.get("repair_performed")),
            _merge_text(existing.get("parts_used"), extraction.get("part_used")),
            extraction.get("part_number"),
            extraction.get("quantity"),
            extraction.get("job_status"),
            extraction.get("payment_status"),
            extraction.get("payment_amount"),
            extraction.get("repair_category"),
            extraction.get("confidence_label"),
            extraction.get("confidence_reason"),
            _json(extraction.get("missing_information", [])),
            normalized.get("timestamp") or now,
            now,
            job_id,
        ),
    )
    return job_id, existing


def ingest_waha_payload(payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    apply_retention()
    normalized = normalize_waha_payload(payload)
    now = now_utc()
    with get_connection() as conn:
        raw_message_id, inserted = _insert_raw_message(conn, normalized)
        if not inserted:
            existing_result = _existing_ingest_result(conn, raw_message_id, normalized)
            if existing_result:
                existing_result["supabase_sync"] = sync_message_bundle_to_supabase(raw_message_id)
                return existing_result
        _upsert_group(conn, normalized, now)
        _upsert_technician(conn, normalized, now)
        extraction = extract_message(normalized)
        job_id, existing_job = _upsert_job(conn, extraction, normalized, now)
        existing_amounts = _payment_amounts(conn, job_id, extraction.get("unit_number"))
        alerts = build_alerts(normalized, extraction, existing_job, existing_amounts)

        if extraction.get("part_used"):
            conn.execute(
                """
                INSERT INTO parts(job_id, raw_message_id, part_name, part_number, quantity, confidence_level, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    raw_message_id,
                    extraction.get("part_used"),
                    extraction.get("part_number"),
                    extraction.get("quantity"),
                    extraction.get("confidence_label"),
                    now,
                ),
            )

        if extraction.get("payment_amount") is not None or extraction.get("payment_status"):
            conn.execute(
                """
                INSERT INTO payments(job_id, raw_message_id, unit_number, amount, currency, status, confidence_level, created_at)
                VALUES (?, ?, ?, ?, 'USD', ?, ?, ?)
                """,
                (
                    job_id,
                    raw_message_id,
                    extraction.get("unit_number"),
                    extraction.get("payment_amount"),
                    extraction.get("payment_status") or "mentioned_unverified",
                    extraction.get("confidence_label"),
                    now,
                ),
            )

        if normalized.get("has_media"):
            conn.execute(
                """
                INSERT INTO media_files(raw_message_id, job_id, media_type, media_url, processed_status, created_at)
                VALUES (?, ?, ?, ?, 'pending_ocr', ?)
                """,
                (
                    raw_message_id,
                    job_id,
                    normalized.get("message_type"),
                    normalized.get("media_url"),
                    now,
                ),
            )

        conn.execute(
            """
            INSERT INTO job_events(
                job_id, raw_message_id, event_type, summary, extraction_json,
                confidence_level, confidence_reason, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                raw_message_id,
                _event_type(extraction, normalized),
                _summary(extraction, normalized),
                _json(extraction),
                extraction.get("confidence_label"),
                extraction.get("confidence_reason"),
                now,
            ),
        )

        for alert in alerts:
            conn.execute(
                """
                INSERT INTO alerts(job_id, raw_message_id, alert_type, severity, message, confidence_level, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    raw_message_id,
                    alert["alert_type"],
                    alert["severity"],
                    alert["message"],
                    alert["confidence_level"],
                    now,
                ),
            )

        conn.execute(
            """
            UPDATE raw_messages
            SET detected_language=?, english_translation=?, processed_status='processed'
            WHERE id=?
            """,
            (
                extraction.get("original_language"),
                extraction.get("english_translation"),
                raw_message_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO audit_log(action, entity_type, entity_id, details, created_at)
            VALUES ('ingest', 'raw_message', ?, ?, ?)
            """,
            (str(raw_message_id), _json({"job_id": job_id, "message_id": normalized["message_id"]}), now),
        )

    supabase_sync = sync_message_bundle_to_supabase(raw_message_id)

    return {
        "ok": True,
        "raw_message_id": raw_message_id,
        "job_id": job_id,
        "normalized": normalized,
        "extraction": extraction,
        "alerts_created": len(alerts),
        "supabase_sync": supabase_sync,
        "read_only": True,
    }
