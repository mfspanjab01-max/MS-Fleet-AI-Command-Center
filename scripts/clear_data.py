from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import get_connection, init_db


TABLES = [
    "audit_log",
    "alerts",
    "media_files",
    "payments",
    "parts",
    "job_events",
    "jobs",
    "technicians",
    "groups",
    "raw_messages",
]


def main() -> None:
    init_db()
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        conn.execute("VACUUM")
    print("Cleared all local dashboard records. Schema and sample files were left in place.")


if __name__ == "__main__":
    main()
