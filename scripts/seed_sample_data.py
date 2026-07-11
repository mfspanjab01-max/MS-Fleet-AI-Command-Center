from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import BASE_DIR
from app.ingest import ingest_waha_payload


def main() -> None:
    payload_path = Path(BASE_DIR / "samples" / "waha_webhook_payload.json")
    messages_path = Path(BASE_DIR / "samples" / "sample_whatsapp_messages.jsonl")
    count = 0
    if payload_path.exists():
        ingest_waha_payload(json.loads(payload_path.read_text(encoding="utf-8")))
        count += 1
    if messages_path.exists():
        for line in messages_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ingest_waha_payload(json.loads(line))
                count += 1
    print(f"Seeded {count} sample webhook payloads.")


if __name__ == "__main__":
    main()
