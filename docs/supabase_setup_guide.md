# Supabase Setup Guide

Supabase is optional. SQLite remains the local safety database. When Supabase is enabled, new WAHA webhook records are written to SQLite first, then mirrored to Supabase. The dashboard can read from Supabase so you can view the same data from another device.

Supabase does not replace hosting by itself. To view the dashboard from another device, run or host the FastAPI and Streamlit app somewhere that device can reach.

## 1. Create A Supabase Project

1. Sign in to Supabase.
2. Create a new personal project.
3. Open the project dashboard.
4. Go to `Project Settings` > `API`.
5. Copy the `Project URL`.
6. Copy the `service_role` key for this private local backend.

Do not commit the service role key. Keep it only in your local `.env`.

## 2. Create The Tables

Open Supabase SQL Editor and run:

```sql
-- Paste the contents of supabase/schema.sql here.
```

You can also open the local file:

```text
supabase/schema.sql
```

## 3. Configure `.env`

Edit `.env`:

```text
SUPABASE_ENABLED=1
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
DASHBOARD_DATA_SOURCE=supabase
```

Leave `DASHBOARD_DATA_SOURCE=sqlite` if you only want to mirror data to Supabase while keeping the dashboard on local SQLite.

## 4. Restart The App

Restart FastAPI:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Restart Streamlit:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run dashboard.py
```

## 5. Check Connection

Open:

```text
http://localhost:8000/api/supabase/status
```

The dashboard also shows Supabase mode in the `WAHA and Cloud Connection` section.

## 6. Sync Existing Local Records

If you already had local WhatsApp records before enabling Supabase, run:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\sync_supabase.py
```

Or call the API:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/supabase/sync
```

## 7. Personal Multi-Device Access

For personal access from another device:

- Keep WAHA and the FastAPI backend running where WhatsApp webhooks can reach them.
- Keep Streamlit running on a reachable host, or deploy the dashboard privately.
- Point every dashboard instance at the same Supabase project.
- Use a dashboard password if exposing Streamlit beyond your own machine.

The app remains read-only. It does not send WhatsApp replies, approve payments, or close jobs automatically.
