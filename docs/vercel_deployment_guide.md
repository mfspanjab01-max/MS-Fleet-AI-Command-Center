# Vercel Deployment Guide

This deploys the FastAPI webhook/backend to Vercel. The Streamlit dashboard is still a local dashboard and should be run with `streamlit run dashboard.py`, or converted later to a Vercel-friendly frontend such as Next.js.

## What Runs On Vercel

- FastAPI health endpoint
- WAHA webhook endpoint
- Supabase status endpoint
- Read-only API endpoints

## What Does Not Run On Vercel

- WAHA Docker
- Ollama local AI
- Streamlit dashboard
- Persistent SQLite storage

Vercel uses a temporary `/tmp` SQLite file only as a short-lived ingestion cache. Supabase must be enabled for durable cloud records.

## 1. Push The Vercel Files To GitHub

From your GitHub upload folder:

```powershell
cd "D:\MS-Fleet-AI-Command-Center-GitHub"
git add .
git commit -m "Add Vercel deployment config"
git push
```

## 2. Import The Repo In Vercel

1. Go to `https://vercel.com`.
2. Sign in with GitHub.
3. Click `Add New` > `Project`.
4. Select your `MS-Fleet-AI-Command-Center` GitHub repo.
5. Keep the root directory as the repository root.
6. Deploy after setting environment variables.

Vercel should install Python packages from `requirements.txt`. This repo does not need a `pyproject.toml` for Vercel deployment.

## 3. Add Environment Variables

In Vercel project settings, add these for Production:

```text
SUPABASE_ENABLED=1
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
DASHBOARD_DATA_SOURCE=supabase
OLLAMA_ENABLED=0
CHAT_RETENTION_DAYS=30
```

Do not put `SUPABASE_SERVICE_ROLE_KEY` in GitHub.

## 4. Deploy

Click `Deploy`. After deployment, open:

```text
https://YOUR-VERCEL-APP.vercel.app/health
```

You want Supabase to show:

```json
"enabled": true,
"configured": true
```

## 5. Point WAHA To Vercel

When WAHA runs in Docker, set the webhook URL to:

```text
https://YOUR-VERCEL-APP.vercel.app/api/waha/webhook
```

Example:

```powershell
docker run --rm -it --name waha -p 3000:3000 `
  -e WHATSAPP_HOOK_URL=https://YOUR-VERCEL-APP.vercel.app/api/waha/webhook `
  -e WHATSAPP_HOOK_EVENTS=message `
  devlikeapro/waha
```

## 6. Dashboard Access

Keep the Streamlit dashboard local:

```powershell
streamlit run dashboard.py
```

In local `.env`, use:

```text
DASHBOARD_DATA_SOURCE=supabase
SUPABASE_ENABLED=1
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
```

That lets the local dashboard read cloud data received by the Vercel webhook.
