# Beginner Setup Guide

This guide assumes Windows PowerShell and a local machine.

## 1. Install Prerequisites

Install these first:

- Python 3.11 or newer
- Docker Desktop, for WAHA
- Ollama, optional but recommended for local AI extraction

Restart PowerShell after installing Python if the `python` command is not found.

## 2. Create The Python Environment

From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
python scripts\init_db.py
```

If activation is blocked by PowerShell policy, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again.

## 3. Start The Backend

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Check it:

```text
http://localhost:8000/health
```

## 4. Start The Dashboard

Open another PowerShell window:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run dashboard.py
```

Open:

```text
http://localhost:8501
```

## 5. Optional Sample Data

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\seed_sample_data.py
```

Use this only for offline testing. Skip it when testing with your WAHA QR session.

To clear all local records before QR testing:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\clear_data.py
```

## 6. Optional Ollama Setup

Run a local model:

```powershell
ollama run llama3.1:8b
```

The app will try Ollama first and fall back to local rules if Ollama is unavailable.

## 7. Optional Dashboard Password

Edit `.env` or set an environment variable:

```powershell
$env:DASHBOARD_PASSWORD="choose-a-local-password"
streamlit run dashboard.py
```

This protects the dashboard locally. It does not add internet hosting security.

## 8. Optional Supabase For Personal Multi-Device Viewing

SQLite works by default. Add Supabase only when you want the dashboard data available from another device.

1. Create a Supabase project.
2. Run `supabase/schema.sql` in the Supabase SQL Editor.
3. Edit `.env`:

```text
SUPABASE_ENABLED=1
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
DASHBOARD_DATA_SOURCE=supabase
```

4. Restart FastAPI and Streamlit.

If you already have local records, sync them:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\sync_supabase.py
```

See `docs\supabase_setup_guide.md` for the full guide.
