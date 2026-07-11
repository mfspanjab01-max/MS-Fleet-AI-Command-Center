from __future__ import annotations

from datetime import date
from io import BytesIO, StringIO
import csv
from typing import Any

from .database import execute_query


REPORT_QUERIES = {
    "daily_shift_summary": """
        SELECT job_id, unit_number, technician_name, status, payment_status, repair_category,
               confidence_level, missing_information, last_update_time
        FROM jobs
        WHERE substr(COALESCE(last_update_time, updated_at), 1, 10)=?
        ORDER BY last_update_time DESC
    """,
    "completed_jobs_report": """
        SELECT job_id, unit_number, customer_name, technician_name, repair_performed, parts_used,
               status, payment_status, confidence_level, last_update_time
        FROM jobs
        WHERE status LIKE 'completed%'
        ORDER BY last_update_time DESC
    """,
    "ongoing_jobs_report": """
        SELECT job_id, unit_number, customer_name, technician_name, complaint, diagnosis,
               status, missing_information, last_update_time
        FROM jobs
        WHERE status IN ('ongoing', 'waiting_parts', 'waiting_approval', 'payment_pending')
        ORDER BY last_update_time DESC
    """,
    "payment_pending_report": """
        SELECT job_id, unit_number, customer_name, technician_name, invoice_amount,
               payment_status, confidence_level, last_update_time
        FROM jobs
        WHERE payment_status IN ('pending', 'payment_pending', 'unknown', 'partial_unverified')
           OR status='payment_pending'
        ORDER BY last_update_time DESC
    """,
    "missing_information_report": """
        SELECT job_id, unit_number, technician_name, status, missing_information,
               confidence_level, confidence_reason, last_update_time
        FROM jobs
        WHERE missing_information IS NOT NULL AND missing_information NOT IN ('[]', '')
        ORDER BY last_update_time DESC
    """,
    "technician_activity_report": """
        SELECT technician_name, COUNT(*) AS job_count,
               SUM(CASE WHEN status LIKE 'completed%' THEN 1 ELSE 0 END) AS completed_count,
               MAX(last_update_time) AS last_update_time
        FROM jobs
        GROUP BY technician_name
        ORDER BY job_count DESC, technician_name
    """,
}


REPORT_TITLES = {
    "daily_shift_summary": "Daily Shift Summary",
    "completed_jobs_report": "Completed Jobs Report",
    "ongoing_jobs_report": "Ongoing Jobs Report",
    "payment_pending_report": "Payment Pending Report",
    "missing_information_report": "Missing Information Report",
    "technician_activity_report": "Technician Activity Report",
}


def get_report_rows(report_name: str, report_date: str | None = None) -> list[dict[str, Any]]:
    if report_name not in REPORT_QUERIES:
        raise ValueError(f"Unknown report: {report_name}")
    params: tuple[Any, ...] = ()
    if report_name == "daily_shift_summary":
        params = (report_date or date.today().isoformat(),)
    return execute_query(REPORT_QUERIES[report_name], params)


def rows_to_csv(rows: list[dict[str, Any]]) -> bytes:
    output = StringIO()
    if not rows:
        output.write("No rows\n")
        return output.getvalue().encode("utf-8")
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def rows_to_pdf(title: str, rows: list[dict[str, Any]]) -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
    except ImportError:
        fallback = title + "\n\n" + "\n".join(str(row) for row in rows)
        return fallback.encode("utf-8")

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    x = 0.6 * inch
    y = height - 0.7 * inch
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(x, y, title)
    y -= 0.3 * inch
    pdf.setFont("Helvetica", 8)
    if not rows:
        pdf.drawString(x, y, "No rows.")
    for row in rows:
        line = " | ".join(f"{key}: {value}" for key, value in row.items() if value not in (None, ""))
        for chunk in [line[i : i + 115] for i in range(0, len(line), 115)]:
            if y < 0.7 * inch:
                pdf.showPage()
                y = height - 0.7 * inch
                pdf.setFont("Helvetica", 8)
            pdf.drawString(x, y, chunk)
            y -= 0.18 * inch
        y -= 0.08 * inch
    pdf.save()
    return buffer.getvalue()

