from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import init_db
from app.supabase_store import get_supabase_status, sync_all_sqlite_to_supabase


if __name__ == "__main__":
    init_db()
    status = get_supabase_status()
    if not status["configured"]:
        print(f"Supabase is not configured: {status['mode']}")
        raise SystemExit(1)
    result = sync_all_sqlite_to_supabase()
    print(result)
