# MS Fleet AI Command Center

Local-first, read-only fleet repair dashboard for WAHA WhatsApp webhook events.

The system receives WAHA group-message webhooks after QR login, stores raw messages separately from AI summaries for the configured local retention window, extracts repair and payment signals, flags missing or conflicting information, and displays everything in one Streamlit operations dashboard.

Important safety rule shown in the dashboard:

> AI summary is not proof. Human verification required before closing jobs or approving payments.

## What It Does

- Receives WAHA events at `POST /api/waha/webhook`.
- Stores raw WhatsApp payloads in SQLite before summaries are used.
- Optionally mirrors records to Supabase for personal multi-device viewing.
- Can read dashboard data from SQLite or Supabase with `DASHBOARD_DATA_SOURCE`.
- Keeps local chat/message records for `CHAT_RETENTION_DAYS` days, default `30`.
- Normalizes messages into the requested `source/session/group/sender/message/media/raw_payload` shape.
- Extracts language, translation, unit number, technician, customer, location, complaint, diagnosis, repair, parts, part number, quantity, status, payment, missing information, confidence label, and confidence reason.
- Uses Ollama if available, with a deterministic local fallback when Ollama is offline.
- Tracks jobs, job events, parts, payments, media references, verification alerts, groups, technicians, settings, and audit log.
- Exports reports as CSV and PDF.

## Read-Only Boundaries

This app does not implement any WhatsApp send/reply endpoint. It only receives webhooks and writes local SQLite records first. If Supabase is enabled, the backend mirrors the same records to your Supabase project after local storage succeeds. It does not auto-approve payments and does not close jobs automatically. Completion-like messages are stored as `completed_unverified` and can trigger verification alerts.

The extractor is explicitly designed not to invent part numbers, prices, labor hours, customer names, or invoice numbers. Unknown fields stay blank.

## Project Structure

```text
app/
  ai.py          Local/Ollama extraction and translation fallback
  alerts.py      Verification alert rules
  config.py      Environment settings
  database.py    SQLite schema and helpers
  ingest.py      End-to-end webhook ingestion pipeline
  main.py        FastAPI app and API endpoints
  reports.py     CSV/PDF report builders
  supabase_store.py Optional Supabase REST sync and reads
  waha.py        WAHA payload normalizer
dashboard.py     Streamlit dashboard
docs/            Setup guides
samples/         Sample WAHA payloads and messages
scripts/         Database init, optional sample seeding, and data reset
supabase/        Supabase SQL schema
vercel.json      Optional FastAPI backend deployment config
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
python scripts\init_db.py
```

If `python` is not recognized on Windows, install Python 3.11 or newer, or try `py -3` in place of `python`.

## Run Commands

Run the FastAPI backend:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run the dashboard in another terminal:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run dashboard.py
```

Open:

- FastAPI health: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`
- Dashboard: `http://localhost:8501`

Optional: seed sample data for offline testing. Skip this when testing with your WAHA QR session.

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\seed_sample_data.py
```

Clear local records before live QR testing:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\clear_data.py
```

## Optional Supabase

Use Supabase when you want the same records available from different personal devices. SQLite stays enabled as the local first-write database.

1. Create a Supabase project.
2. Run `supabase/schema.sql` in the Supabase SQL Editor.
3. Add these values to `.env`:

```text
SUPABASE_ENABLED=1
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
DASHBOARD_DATA_SOURCE=supabase
```

4. Restart FastAPI and Streamlit.

To upload existing local records:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\sync_supabase.py
```

Full guide: `docs\supabase_setup_guide.md`.

## Optional Vercel Backend Deployment

Vercel can host the FastAPI webhook/backend. Supabase must be enabled for durable cloud storage because Vercel does not provide persistent SQLite storage for this app.

Use this for WAHA webhook delivery:

```text
https://YOUR-VERCEL-APP.vercel.app/api/waha/webhook
```

Keep Streamlit local unless you later convert the dashboard to a Vercel-friendly frontend.

Full guide: `docs\vercel_deployment_guide.md`.

## WAHA Webhook Endpoint

Set WAHA to post message events to:

```text
http://host.docker.internal:8000/api/waha/webhook
```

Use `http://localhost:8000/api/waha/webhook` only when WAHA is not running inside Docker.

The backend normalizes WAHA payloads into:

```json
{
  "source": "waha",
  "session": "",
  "group_id": "",
  "group_name": "",
  "sender_id": "",
  "sender_name": "",
  "message_id": "",
  "message_type": "text",
  "text": "",
  "timestamp": "",
  "has_media": false,
  "media_url": "",
  "raw_payload": {}
}
```

## Test The Webhook

PowerShell:

```powershell
$payload = Get-Content samples\waha_webhook_payload.json -Raw
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/waha/webhook -Body $payload -ContentType "application/json"
```

The production dashboard does not include a sample webhook button. Use this command only when you intentionally want to test with the sample payload.

## Ollama

Install and run Ollama separately, then pull or run your preferred local model:

```powershell
ollama run llama3.1:8b
```

Configuration:

```text
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_ENABLED=1
```

If Ollama is not available, ingestion still works using deterministic extraction rules.

## Reports

The Reports section generates:

- Daily shift summary
- Completed jobs report
- Ongoing jobs report
- Payment pending report
- Missing information report
- Technician activity report

Each report can be exported as CSV or PDF.
