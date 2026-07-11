from __future__ import annotations

from typing import Any

from .config import EXPENSIVE_PART_KEYWORDS, SAFETY_CRITICAL_KEYWORDS


def _clean_text(text: str) -> str:
    return " ".join(text.lower().replace(".", "").replace("!", "").strip().split())


def _has_test_confirmation(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ["tested", "road test", "verified", "confirmed", "test result", "torqued"])


def _is_conflicting_status(current_status: str, new_status: str) -> bool:
    if not current_status or not new_status:
        return False
    open_statuses = {"ongoing", "waiting_parts", "waiting_approval", "payment_pending"}
    done_statuses = {"completed_unverified"}
    return (current_status in open_statuses and new_status in done_statuses) or (
        current_status in done_statuses and new_status in open_statuses
    )


def build_alerts(
    normalized: dict[str, Any],
    extraction: dict[str, Any],
    existing_job: dict[str, Any] | None = None,
    existing_payment_amounts: list[float] | None = None,
) -> list[dict[str, Any]]:
    text = normalized.get("text", "") or ""
    cleaned = _clean_text(text)
    alerts: list[dict[str, Any]] = []

    def add(alert_type: str, severity: str, message: str) -> None:
        alerts.append(
            {
                "alert_type": alert_type,
                "severity": severity,
                "message": message,
                "confidence_level": extraction.get("confidence_label", "Unconfirmed"),
            }
        )

    if cleaned in {"done", "fixed", "complete", "completed", "truck ready", "unit ready"}:
        add("vague_completion", "high", "Completion message is too vague to verify the repair.")

    if normalized.get("has_media") and not cleaned:
        add("image_only_update", "medium", "Image-only update needs OCR or human review.")

    if extraction.get("payment_amount") is not None and not extraction.get("unit_number"):
        add("payment_without_unit", "high", "Payment was mentioned without a unit or job number.")

    if extraction.get("part_used") and not extraction.get("unit_number"):
        add("part_without_unit", "high", "Part change was mentioned without a unit number.")

    if extraction.get("job_status") == "completed_unverified" and not _has_test_confirmation(text):
        add("completed_without_test", "high", "Repair was marked complete without a test result.")

    part = (extraction.get("part_used") or "").lower()
    if part and any(keyword in part for keyword in EXPENSIVE_PART_KEYWORDS) and not extraction.get("part_number"):
        add("expensive_part_no_number", "high", "Expensive part was mentioned without a part number.")

    if extraction.get("translation_uncertain"):
        add("translation_uncertain", "medium", "Non-English translation is uncertain and needs verification.")

    if existing_job and _is_conflicting_status(existing_job.get("status", ""), extraction.get("job_status", "")):
        extraction["confidence_label"] = "Conflicting"
        add("conflicting_status", "high", "Same unit has conflicting job status updates.")

    payment_amount = extraction.get("payment_amount")
    if payment_amount is not None and existing_payment_amounts:
        for amount in existing_payment_amounts:
            if abs(float(amount) - float(payment_amount)) > 0.01:
                extraction["confidence_label"] = "Conflicting"
                add("payment_amount_conflict", "high", "Payment amount conflicts with a prior update for this job.")
                break

    safety_text = " ".join([text.lower(), part])
    if any(keyword in safety_text for keyword in SAFETY_CRITICAL_KEYWORDS) and not _has_test_confirmation(text):
        add("safety_confirmation_missing", "high", "Safety-critical repair lacks test or confirmation detail.")

    return alerts

