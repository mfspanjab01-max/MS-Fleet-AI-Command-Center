from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from app.config import (
    APP_NAME,
    CHAT_RETENTION_DAYS,
    DASHBOARD_DATA_SOURCE,
    DASHBOARD_PASSWORD,
    DB_PATH,
    OLLAMA_ENABLED,
    OLLAMA_MODEL,
    OLLAMA_URL,
    READ_ONLY_WARNING,
    SUPABASE_ENABLED,
    SUPABASE_URL,
    WAHA_SERVER_URL,
)
from app.database import apply_retention, execute_query, init_db
from app.reports import REPORT_TITLES, rows_to_csv, rows_to_pdf
from app.supabase_store import get_supabase_status, select_rows, supabase_configured


st.set_page_config(page_title=APP_NAME, page_icon=None, layout="wide", initial_sidebar_state="collapsed")
init_db()
apply_retention()


ORDER_COLUMNS = {
    "raw_messages": "created_at",
    "groups": "last_seen",
    "technicians": "last_seen",
    "jobs": "updated_at",
    "job_events": "created_at",
    "parts": "created_at",
    "payments": "created_at",
    "media_files": "created_at",
    "alerts": "created_at",
    "settings": "updated_at",
    "audit_log": "created_at",
}


def use_supabase_source() -> bool:
    return DASHBOARD_DATA_SOURCE == "supabase" and supabase_configured()


def apply_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --surface: #0d1117;
            --panel: #161b22;
            --panel-2: #1f242c;
            --text: #e6edf3;
            --muted: #9ba7b4;
            --border: #30363d;
        }
        .stApp { background: var(--surface); color: var(--text); }
        [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none; }
        [data-testid="stMetric"] {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px;
        }
        div.stButton > button, div.stDownloadButton > button {
            min-height: 44px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background: var(--panel-2);
            color: var(--text);
        }
        .block-container { padding-top: 1.25rem; }
        h1, h2, h3 { letter-spacing: 0; }
        section[data-testid="stExpander"] {
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--panel);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=5)
def table_rows(table: str, limit: int = 2000, source: str = "sqlite") -> list[dict[str, Any]]:
    order_col = ORDER_COLUMNS.get(table)
    if source == "supabase":
        return select_rows(table, limit=limit, order=order_col)
    if order_col:
        return execute_query(f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT ?", (limit,))
    return execute_query(f"SELECT * FROM {table} LIMIT ?", (limit,))


def table_df(table: str, limit: int = 2000) -> pd.DataFrame:
    source = "supabase" if use_supabase_source() else "sqlite"
    try:
        return pd.DataFrame(table_rows(table, limit, source))
    except Exception as exc:
        st.error(f"Could not load {table} from {source}: {exc}")
        return pd.DataFrame()


def show_table(data: pd.DataFrame, empty: str = "No records yet.") -> None:
    if data.empty:
        st.info(empty)
    else:
        st.dataframe(data, use_container_width=True, hide_index=True)


def pick(data: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=columns)
    return data.reindex(columns=columns)


def text_col(data: pd.DataFrame, column: str) -> pd.Series:
    if column not in data:
        return pd.Series([""] * len(data), index=data.index, dtype="object")
    return data[column].fillna("").astype(str)


def numeric_col(data: pd.DataFrame, column: str) -> pd.Series:
    if column not in data:
        return pd.Series([0] * len(data), index=data.index)
    return pd.to_numeric(data[column], errors="coerce").fillna(0)


def sort_desc(data: pd.DataFrame, column: str) -> pd.DataFrame:
    if data.empty or column not in data:
        return data
    return data.sort_values(column, ascending=False)


def today_mask(data: pd.DataFrame, *columns: str) -> pd.Series:
    today = date.today().isoformat()
    mask = pd.Series([False] * len(data), index=data.index)
    for column in columns:
        if column in data:
            mask = mask | text_col(data, column).str.startswith(today)
    return mask


def require_login() -> bool:
    if not DASHBOARD_PASSWORD:
        st.session_state.authenticated = True
        return True
    return bool(st.session_state.get("authenticated"))


def dashboard_header() -> None:
    st.title(APP_NAME)
    st.warning(READ_ONLY_WARNING)
    data_source = "Supabase" if use_supabase_source() else "SQLite"
    if DASHBOARD_DATA_SOURCE == "supabase" and not use_supabase_source():
        st.error("DASHBOARD_DATA_SOURCE is set to supabase, but Supabase is not fully configured. Showing SQLite data.")
    st.caption(f"Data source: {data_source}. Local WhatsApp/chat retention: {CHAT_RETENTION_DAYS} days.")


def login_page() -> None:
    dashboard_header()
    password = st.text_input("Dashboard password", type="password")
    if st.button("Sign in", use_container_width=False):
        if password == DASHBOARD_PASSWORD:
            st.session_state.authenticated = True
            st.success("Signed in.")
        else:
            st.error("Incorrect password.")


def section(title: str) -> None:
    st.markdown(f"### {title}")


def load_dashboard_tables() -> dict[str, pd.DataFrame]:
    return {
        "raw_messages": table_df("raw_messages"),
        "groups": table_df("groups"),
        "technicians": table_df("technicians"),
        "jobs": table_df("jobs"),
        "parts": table_df("parts"),
        "payments": table_df("payments"),
        "media_files": table_df("media_files"),
        "alerts": table_df("alerts"),
    }


def summary_metrics(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    raw = tables["raw_messages"]
    jobs = tables["jobs"]
    alerts = tables["alerts"]
    groups = tables["groups"]
    status = text_col(jobs, "status")
    payment = text_col(jobs, "payment_status")
    missing = text_col(jobs, "missing_information")
    open_alert_status = text_col(alerts, "status")
    created = text_col(raw, "created_at")
    last_received = created.max() if not raw.empty and "created_at" in raw else "none"
    return {
        "messages_today": int(today_mask(raw, "timestamp", "created_at").sum()) if not raw.empty else 0,
        "stored_messages": len(raw),
        "groups_detected": len(groups),
        "completed_jobs": int(status.str.startswith("completed").sum()) if not jobs.empty else 0,
        "active_jobs": int(status.isin(["ongoing", "waiting_parts", "waiting_approval", "payment_pending"]).sum())
        if not jobs.empty
        else 0,
        "waiting_parts": int((status == "waiting_parts").sum()) if not jobs.empty else 0,
        "waiting_approval": int((status == "waiting_approval").sum()) if not jobs.empty else 0,
        "payment_pending": int((payment.isin(["pending", "unknown", "partial_unverified"]) | (status == "payment_pending")).sum())
        if not jobs.empty
        else 0,
        "missing_info": int(((missing != "") & (missing != "[]")).sum()) if not jobs.empty else 0,
        "open_alerts": int((open_alert_status == "open").sum()) if not alerts.empty else 0,
        "last_received_webhook": last_received,
    }


def job_table(jobs: pd.DataFrame, name: str) -> pd.DataFrame:
    if jobs.empty:
        return jobs
    status = text_col(jobs, "status")
    payment = text_col(jobs, "payment_status")
    missing = text_col(jobs, "missing_information")
    if name == "ongoing":
        filtered = jobs[status.isin(["ongoing", "payment_pending"])]
    elif name == "completed":
        filtered = jobs[status.str.startswith("completed")]
    elif name == "waiting_parts":
        filtered = jobs[status == "waiting_parts"]
    elif name == "waiting_approval":
        filtered = jobs[status == "waiting_approval"]
    elif name == "payment_pending":
        filtered = jobs[payment.isin(["pending", "unknown", "partial_unverified"]) | (status == "payment_pending")]
    elif name == "missing":
        filtered = jobs[(missing != "") & (missing != "[]")]
    else:
        filtered = jobs
    columns = [
        "job_id",
        "unit_number",
        "customer_name",
        "technician_name",
        "group_name",
        "complaint",
        "diagnosis",
        "repair_performed",
        "parts_used",
        "part_number",
        "quantity",
        "status",
        "payment_status",
        "invoice_amount",
        "repair_category",
        "confidence_level",
        "missing_information",
        "last_update_time",
    ]
    return pick(sort_desc(filtered, "last_update_time"), columns)


def open_alerts(alerts: pd.DataFrame) -> pd.DataFrame:
    if alerts.empty:
        return alerts
    filtered = alerts[text_col(alerts, "status") == "open"].copy()
    severity_order = {"high": 1, "medium": 2, "low": 3}
    filtered["_severity_sort"] = text_col(filtered, "severity").map(severity_order).fillna(4)
    filtered = filtered.sort_values(["_severity_sort", "created_at"], ascending=[True, False])
    return pick(
        filtered,
        ["severity", "alert_type", "message", "job_id", "raw_message_id", "confidence_level", "created_at"],
    )


def payments_table(payments: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    if payments.empty:
        return payments
    result = payments.copy()
    if not raw.empty and "id" in raw and "raw_message_id" in result:
        lookup = raw.reindex(columns=["id", "sender_name", "group_name"]).rename(columns={"id": "raw_message_id"})
        result = result.merge(lookup, on="raw_message_id", how="left")
    return pick(
        sort_desc(result, "created_at"),
        ["created_at", "job_id", "unit_number", "amount", "currency", "status", "confidence_level", "sender_name", "group_name"],
    )


def parts_table(parts: pd.DataFrame, jobs: pd.DataFrame) -> pd.DataFrame:
    if parts.empty:
        return parts
    result = parts.copy()
    if not jobs.empty and "job_id" in jobs and "job_id" in result:
        lookup = jobs.reindex(columns=["job_id", "unit_number"])
        result = result.merge(lookup, on="job_id", how="left")
    return pick(
        sort_desc(result, "created_at"),
        ["created_at", "job_id", "unit_number", "part_name", "part_number", "quantity", "confidence_level"],
    )


def media_table(media: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    if media.empty:
        return media
    result = media.copy()
    if not raw.empty and "id" in raw and "raw_message_id" in result:
        lookup = raw.reindex(columns=["id", "group_name", "sender_name"]).rename(columns={"id": "raw_message_id"})
        result = result.merge(lookup, on="raw_message_id", how="left")
    return pick(
        sort_desc(result, "created_at"),
        ["created_at", "group_name", "sender_name", "job_id", "media_type", "media_url", "local_path", "ocr_text", "processed_status"],
    )


def translations_table(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    lang = text_col(raw, "detected_language")
    filtered = raw[(lang != "") & (~lang.isin(["English", "Unknown"]))]
    return pick(
        sort_desc(filtered, "created_at"),
        ["timestamp", "group_name", "sender_name", "original_text", "detected_language", "english_translation", "processed_status"],
    )


def report_rows(report_name: str, report_date: str, tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    jobs = tables["jobs"].copy()
    if jobs.empty:
        return []
    status = text_col(jobs, "status")
    payment = text_col(jobs, "payment_status")
    missing = text_col(jobs, "missing_information")
    if report_name == "daily_shift_summary":
        data = jobs
    elif report_name == "completed_jobs_report":
        data = jobs[status.str.startswith("completed")]
    elif report_name == "ongoing_jobs_report":
        data = jobs[status.isin(["ongoing", "waiting_parts", "waiting_approval", "payment_pending"])]
    elif report_name == "payment_pending_report":
        data = jobs[payment.isin(["pending", "payment_pending", "unknown", "partial_unverified"]) | (status == "payment_pending")]
    elif report_name == "missing_information_report":
        data = jobs[(missing != "") & (missing != "[]")]
    elif report_name == "technician_activity_report":
        grouped = jobs.groupby("technician_name", dropna=False).agg(
            job_count=("job_id", "count"),
            completed_count=("status", lambda values: values.fillna("").astype(str).str.startswith("completed").sum()),
            last_update_time=("last_update_time", "max"),
        )
        return grouped.reset_index().to_dict("records")
    else:
        data = jobs
    if report_name == "daily_shift_summary":
        day = report_date
        data = data[
            text_col(data, "last_update_time").str.startswith(day)
            | text_col(data, "updated_at").str.startswith(day)
        ]
    return sort_desc(data, "last_update_time").to_dict("records")


def single_dashboard() -> None:
    dashboard_header()
    tables = load_dashboard_tables()
    metrics = summary_metrics(tables)
    supabase = get_supabase_status()

    top = st.columns(5)
    top[0].metric("Messages Today", metrics["messages_today"])
    top[1].metric(f"Stored Messages ({CHAT_RETENTION_DAYS}d)", metrics["stored_messages"])
    top[2].metric("Active Jobs", metrics["active_jobs"])
    top[3].metric("Open Alerts", metrics["open_alerts"])
    top[4].metric("Groups", metrics["groups_detected"])

    second = st.columns(5)
    second[0].metric("Completed Unverified", metrics["completed_jobs"])
    second[1].metric("Waiting Parts", metrics["waiting_parts"])
    second[2].metric("Waiting Approval", metrics["waiting_approval"])
    second[3].metric("Payment Pending", metrics["payment_pending"])
    second[4].metric("Missing Info", metrics["missing_info"])

    section("WAHA and Cloud Connection")
    connection = pd.DataFrame(
        [
            {"item": "WAHA server URL", "value": WAHA_SERVER_URL},
            {"item": "Webhook URL for WAHA Docker", "value": "http://host.docker.internal:8000/api/waha/webhook"},
            {"item": "Last received webhook", "value": metrics["last_received_webhook"] or "none"},
            {"item": "Dashboard data source", "value": "Supabase" if use_supabase_source() else "SQLite"},
            {"item": "Supabase mode", "value": supabase["mode"]},
            {"item": "Supabase URL", "value": SUPABASE_URL or "not set"},
            {"item": "Read-only mode", "value": "No WhatsApp replies or send endpoints are implemented."},
        ]
    )
    show_table(connection)

    section("Verification Required")
    show_table(open_alerts(tables["alerts"]), "No open verification alerts.")

    section("Live WhatsApp Feed")
    live_columns = [
        "timestamp",
        "group_name",
        "sender_name",
        "message_type",
        "original_text",
        "detected_language",
        "english_translation",
        "processed_status",
    ]
    show_table(pick(sort_desc(tables["raw_messages"], "created_at"), live_columns), "No WhatsApp messages received yet.")

    section("Job Workboard")
    st.caption("All job summaries are AI-assisted and remain unverified until a human checks the source message.")
    for title, name, empty in [
        ("Ongoing Jobs", "ongoing", "No ongoing jobs."),
        ("Completed Jobs", "completed", "No completed jobs."),
        ("Waiting for Parts", "waiting_parts", "No jobs waiting for parts."),
        ("Waiting for Approval", "waiting_approval", "No jobs waiting for approval."),
        ("Payment Pending", "payment_pending", "No payment-pending jobs."),
        ("Missing Information", "missing", "No missing information has been detected."),
    ]:
        with st.expander(title, expanded=title == "Ongoing Jobs"):
            show_table(job_table(tables["jobs"], name), empty)

    section("Payments")
    show_table(payments_table(tables["payments"], tables["raw_messages"]), "No payment updates received yet.")

    section("Parts")
    show_table(parts_table(tables["parts"], tables["jobs"]), "No parts have been extracted yet.")

    section("Translations")
    show_table(translations_table(tables["raw_messages"]), "No non-English messages have been detected yet.")

    section("Media / Images")
    show_table(media_table(tables["media_files"], tables["raw_messages"]), "No media records yet.")

    section("Groups and Technicians")
    left, right = st.columns(2)
    with left:
        st.subheader("Groups Detected")
        show_table(
            pick(sort_desc(tables["groups"], "last_seen"), ["group_id", "group_name", "last_seen", "message_count"]),
            "No groups detected yet.",
        )
    with right:
        st.subheader("Technician Activity")
        show_table(
            pick(sort_desc(tables["technicians"], "message_count"), ["sender_name", "sender_id", "message_count", "last_seen"]),
            "No technician messages received yet.",
        )

    section("Reports")
    report_name = st.selectbox("Report", list(REPORT_TITLES.keys()), format_func=lambda key: REPORT_TITLES[key])
    report_date = st.date_input("Report date", value=date.today())
    rows = report_rows(report_name, report_date.isoformat(), tables)
    show_table(pd.DataFrame(rows), "No rows for this report.")
    title = REPORT_TITLES[report_name]
    cols = st.columns(2)
    cols[0].download_button("Export CSV", data=rows_to_csv(rows), file_name=f"{report_name}.csv", mime="text/csv")
    cols[1].download_button("Export PDF", data=rows_to_pdf(title, rows), file_name=f"{report_name}.pdf", mime="application/pdf")

    section("Runtime Settings")
    settings = pd.DataFrame(
        [
            {"setting": "SQLite database path", "value": str(DB_PATH)},
            {"setting": "Dashboard data source", "value": DASHBOARD_DATA_SOURCE},
            {"setting": "Supabase enabled", "value": str(SUPABASE_ENABLED)},
            {"setting": "Supabase configured", "value": str(supabase_configured())},
            {"setting": "Chat/message retention", "value": f"{CHAT_RETENTION_DAYS} days"},
            {"setting": "Ollama enabled", "value": str(OLLAMA_ENABLED)},
            {"setting": "Ollama URL", "value": OLLAMA_URL},
            {"setting": "Ollama model", "value": OLLAMA_MODEL},
            {"setting": "Dashboard password configured", "value": str(bool(DASHBOARD_PASSWORD))},
        ]
    )
    show_table(settings)


def main() -> None:
    apply_style()
    if not require_login():
        login_page()
        return
    single_dashboard()


if __name__ == "__main__":
    main()
