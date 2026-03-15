import re
import os
from pathlib import Path

sidecar_path = Path("/media/second_disk/cont5/sidecar/sidecar.py")
verify_path = Path("/media/second_disk/cont5/sidecar/verify.py")
req_path = Path("/media/second_disk/cont5/sidecar/requirements.txt")

# 1. Update requirements
with open(req_path, 'a') as f:
    f.write('aiosqlite==0.20.0\n')

# 2. Refactor verify.py entirely for aiosqlite, time.time(), etc.
verify_code = verify_path.read_text()
verify_code = verify_code.replace("import sqlite3", "import aiosqlite\nimport time")

verify_code = verify_code.replace("""class ProcessedTxStore:
    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute(
            \"\"\"
            CREATE TABLE IF NOT EXISTS processed_txs (
                tx_hash TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            \"\"\"
        )
        self._conn.commit()

    def is_processed(self, tx_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM processed_txs WHERE tx_hash = ?",
            (tx_hash,),
        ).fetchone()
        return row is not None

    def mark_processed(self, tx_hash: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO processed_txs (tx_hash, created_at) VALUES (?, ?)",
            (tx_hash, now_iso),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()""", """class ProcessedTxStore:
    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute(
            \"\"\"
            CREATE TABLE IF NOT EXISTS processed_txs (
                tx_hash TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            \"\"\"
        )
        await self._conn.commit()

    async def is_processed(self, tx_hash: str) -> bool:
        if not self._conn:
            await self.init()
        async with self._conn.execute(
            "SELECT 1 FROM processed_txs WHERE tx_hash = ?",
            (tx_hash,),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def mark_processed(self, tx_hash: str) -> None:
        if not self._conn:
            await self.init()
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT INTO processed_txs (tx_hash, created_at) VALUES (?, ?)",
            (tx_hash, now_iso),
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()""")

# Replace timestamp
verify_code = verify_code.replace("now_ts = int(datetime.now(timezone.utc).timestamp())", "now_ts = int(time.time())")

# Provide comment for JSON Nonce matching
verify_code = verify_code.replace("""        try:
            comment_json = json.loads(normalized_comment)
            if isinstance(comment_json, dict):
                return str(comment_json.get("nonce", "")).strip() in {raw_nonce, nonce_value}
        except json.JSONDecodeError:
            return False""", """        # Nonce could be a JSON payload based on previous specifications it seems, we attempt to parse it
        try:
            comment_json = json.loads(normalized_comment)
            if isinstance(comment_json, dict):
                return str(comment_json.get("nonce", "")).strip() in {raw_nonce, nonce_value}
        except json.JSONDecodeError:
            return False""")

verify_path.write_text(verify_code)


