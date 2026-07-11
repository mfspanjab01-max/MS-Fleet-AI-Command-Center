# WAHA Setup Guide

WAHA runs separately in Docker. This project only receives WAHA webhook events. It does not send WhatsApp messages.

## 1. Start The FastAPI Backend

WAHA needs a reachable webhook URL.

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend webhook URL from a Docker container:

```text
http://host.docker.internal:8000/api/waha/webhook
```

Backend webhook URL if WAHA is not in Docker:

```text
http://localhost:8000/api/waha/webhook
```

## 2. Run WAHA In Docker

Use your installed WAHA image and version. A typical local command is:

```powershell
docker run --rm -it --name waha -p 3000:3000 devlikeapro/waha
```

If your WAHA version supports webhook environment variables, point them to this app:

```powershell
docker run --rm -it --name waha -p 3000:3000 `
  -e WHATSAPP_HOOK_URL=http://host.docker.internal:8000/api/waha/webhook `
  -e WHATSAPP_HOOK_EVENTS=message `
  devlikeapro/waha
```

WAHA versions can differ. If your version uses a dashboard or API call to configure webhooks, use the same webhook URL above.

## 3. Login With QR

Open WAHA:

```text
http://localhost:3000
```

Start or open the `default` session, then scan the QR code with WhatsApp. After login, send a message in a WhatsApp group that the logged-in account can read.

## 4. Confirm Webhook Delivery

Open:

```text
http://localhost:8501
```

On the single dashboard, check the `WAHA and Cloud Connection` section. Confirm:

- Last received webhook
- Total messages received today
- Groups detected
- Webhook health status
- Supabase mode, if you enabled Supabase

You can also test locally without WAHA:

```powershell
$payload = Get-Content samples\waha_webhook_payload.json -Raw
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/waha/webhook -Body $payload -ContentType "application/json"
```

## 5. Read-Only WAHA Policy

Do not configure reply bots, auto-send actions, or WAHA send-message calls for this project. The app intentionally has no WhatsApp send endpoint.
