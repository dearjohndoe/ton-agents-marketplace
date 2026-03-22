"""
Cleanup worker for expired TON Storage bags.
Run periodically via cron, e.g.: */30 * * * * cd /path/to/ton-storage && python cleanup.py
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DB_PATH = Path(__file__).parent / "storage.db"
STORAGE_API_URL = os.environ.get("STORAGE_API_URL", "http://127.0.0.1:9955").rstrip("/")
STORAGE_API_LOGIN = os.environ.get("STORAGE_API_LOGIN", "")
STORAGE_API_PASSWORD = os.environ.get("STORAGE_API_PASSWORD", "")


def _storage_auth():
    if STORAGE_API_LOGIN and STORAGE_API_PASSWORD:
        return (STORAGE_API_LOGIN, STORAGE_API_PASSWORD)
    return None


def _remove_bag(bag_id: str):
    import requests

    resp = requests.post(
        f"{STORAGE_API_URL}/api/v1/remove",
        json={"bag_id": bag_id, "with_files": True},
        auth=_storage_auth(),
        timeout=30,
    )
    resp.raise_for_status()


def main():
    if not DB_PATH.exists():
        return

    conn = sqlite3.connect(str(DB_PATH))
    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        "SELECT bag_id, path FROM bags WHERE expires_at <= ?", (now,)
    ).fetchall()

    if not rows:
        return

    removed = 0
    for bag_id, path in rows:
        try:
            _remove_bag(bag_id)
        except Exception as e:
            print(f"Failed to remove bag {bag_id} from storage: {e}", file=sys.stderr)

        if path and Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)

        conn.execute("DELETE FROM bags WHERE bag_id = ?", (bag_id,))
        conn.commit()
        removed += 1

    conn.close()

    if removed:
        print(f"Cleaned up {removed} expired bag(s)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
