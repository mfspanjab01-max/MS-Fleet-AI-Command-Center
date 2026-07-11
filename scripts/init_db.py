from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import DB_PATH, init_db


if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {DB_PATH}")
