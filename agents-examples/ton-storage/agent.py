import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DB_PATH = Path(__file__).parent / "storage.db"
UPLOAD_DIR = Path(os.environ.get("STORAGE_UPLOAD_DIR", "/tmp/ton-storage-uploads"))
STORAGE_API_URL = os.environ.get("STORAGE_API_URL", "http://127.0.0.1:9955").rstrip("/")
STORAGE_API_LOGIN = os.environ.get("STORAGE_API_LOGIN", "")
STORAGE_API_PASSWORD = os.environ.get("STORAGE_API_PASSWORD", "")
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "100"))
BASE_PRICE_NANOTON = int(os.environ.get("AGENT_PRICE", "10000000"))

ARGS_SCHEMA = {
    "file": {
        "type": "file",
        "description": "File to upload to TON Storage",
        "required": True,
    },
    "duration_months": {
        "type": "number",
        "description": "Storage duration in months (1-12)",
        "required": True,
    },
}


def _init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS bags (
            bag_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn


def _storage_auth():
    if STORAGE_API_LOGIN and STORAGE_API_PASSWORD:
        return (STORAGE_API_LOGIN, STORAGE_API_PASSWORD)
    return None


def _create_bag(dir_path: str, description: str) -> str:
    import requests

    try:
        resp = requests.post(
            f"{STORAGE_API_URL}/api/v1/create",
            json={"path": dir_path, "description": description},
            auth=_storage_auth(),
            timeout=120,
        )
        resp.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise RuntimeError(f"Storage API error (HTTP {status})") from exc
    except requests.ConnectionError:
        raise RuntimeError("Storage API is unavailable")
    except requests.Timeout:
        raise RuntimeError("Storage API timed out")

    data = resp.json()
    bag_id = data.get("bag_id")
    if not bag_id:
        raise RuntimeError("Storage API returned no bag_id")
    return bag_id


def main():
    task = json.load(sys.stdin)

    if task.get("mode") == "describe":
        print(json.dumps({"args_schema": ARGS_SCHEMA, "result_schema": {"type": "bagid"}}))
        return

    if task.get("mode") == "quote":
        body = task.get("body") or {}
        duration_months = int(body.get("duration_months", 1))
        if not 1 <= duration_months <= 12:
            raise ValueError("duration_months must be between 1 and 12")
        price = BASE_PRICE_NANOTON * duration_months
        print(json.dumps({"price": price, "plan": f"{duration_months} month(s) of storage", "ttl": 120}))
        return

    body = task.get("body") or {}

    file_path_str = body.get("file_path", "")
    if not file_path_str:
        raise ValueError("body.file_path is required")

    file_path = Path(file_path_str)
    if not file_path.exists():
        raise ValueError(f"File not found: {file_path}")

    file_name = body.get("file_name") or file_path.name

    duration_months = body.get("duration_months")
    if duration_months is None:
        raise ValueError("body.duration_months is required")
    duration_months = int(duration_months)
    if not 1 <= duration_months <= 12:
        raise ValueError("duration_months must be between 1 and 12")

    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"File size {file_size_mb:.1f} MB exceeds limit of {MAX_FILE_SIZE_MB} MB"
        )

    upload_id = str(uuid.uuid4())
    upload_dir = UPLOAD_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest_path = upload_dir / file_name
    shutil.copy2(str(file_path), str(dest_path))

    try:
        bag_id = _create_bag(str(upload_dir), f"Upload: {file_name}")
    except Exception:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    now = datetime.now(timezone.utc)
    expires_at = now + relativedelta(months=duration_months)

    conn = _init_db()
    try:
        conn.execute(
            "INSERT INTO bags (bag_id, path, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (bag_id, str(upload_dir), expires_at.isoformat(), now.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"result": {"type": "bagid", "data": bag_id}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
