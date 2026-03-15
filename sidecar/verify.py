from __future__ import annotations

import json
import aiosqlite
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


class PaymentVerificationError(Exception):
    pass


@dataclass
class VerifiedPayment:
    tx_hash: str
    sender: str
    recipient: str
    amount: int
    comment: str


@dataclass
class NonceMeta:
    value: str
    created_at: int


class ProcessedTxStore:
    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_txs (
                tx_hash TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """
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
            await self._conn.close()


def parse_nonce(raw_nonce: str) -> NonceMeta:
    nonce = raw_nonce.strip()
    try:
        maybe_json = json.loads(nonce)
        if isinstance(maybe_json, dict) and "created_at" in maybe_json:
            created_at = int(maybe_json["created_at"])
            return NonceMeta(value=str(maybe_json.get("nonce", nonce)), created_at=created_at)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    for sep in (":", "|", "."):
        if sep in nonce:
            prefix, suffix = nonce.rsplit(sep, 1)
            if suffix.isdigit():
                return NonceMeta(value=prefix, created_at=int(suffix))

    raise PaymentVerificationError(
        "Nonce must include created_at timestamp, e.g. '<nonce>:<unix_ts>' or JSON with created_at"
    )


class PaymentVerifier:
    def __init__(
        self,
        toncenter_base_url: str,
        toncenter_api_key: str | None,
        agent_wallet: str,
        min_amount: int,
        payment_timeout_seconds: int,
        enforce_comment_nonce: bool = True,
    ) -> None:
        self._base_url = toncenter_base_url.rstrip("/")
        self._agent_wallet = agent_wallet
        self._min_amount = min_amount
        self._payment_timeout = payment_timeout_seconds
        self._enforce_comment_nonce = enforce_comment_nonce
        headers: dict[str, str] = {}
        if toncenter_api_key:
            headers["X-API-Key"] = toncenter_api_key
        self._client = httpx.AsyncClient(timeout=20, headers=headers)

    async def close(self) -> None:
        await self._client.aclose()

    async def verify(self, tx_hash: str, raw_nonce: str) -> VerifiedPayment:
        nonce = parse_nonce(raw_nonce)
        now_ts = int(time.time())
        if now_ts - nonce.created_at > self._payment_timeout:
            raise PaymentVerificationError("Payment session expired")

        tx = await self._fetch_transaction(tx_hash)
        sender = self._extract_sender(tx)
        recipient = self._extract_recipient(tx)
        amount = self._extract_amount(tx)
        comment = self._extract_comment(tx)

        if recipient != self._agent_wallet:
            raise PaymentVerificationError("Transaction recipient does not match agent wallet")

        if amount < self._min_amount:
            raise PaymentVerificationError("Transaction amount is lower than agent price")

        if self._enforce_comment_nonce and not self._comment_matches_nonce(comment, raw_nonce, nonce.value):
            raise PaymentVerificationError("Transaction comment nonce mismatch")

        if not sender:
            raise PaymentVerificationError("Transaction sender is missing")

        return VerifiedPayment(
            tx_hash=tx_hash,
            sender=sender,
            recipient=recipient,
            amount=amount,
            comment=comment,
        )

    @staticmethod
    def _extract_sender(tx: dict[str, Any]) -> str:
        msg = tx.get("in_msg") or {}
        sender = msg.get("source") or msg.get("src") or tx.get("sender")
        return str(sender or "")

    async def _fetch_transaction(self, tx_hash: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self._base_url}/transactions",
            params={"hash": tx_hash, "limit": 1},
        )
        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, list):
            txs = payload
        elif isinstance(payload, dict):
            txs = payload.get("transactions") or payload.get("result") or []
        else:
            txs = []

        if not txs:
            raise PaymentVerificationError("Transaction not found")

        tx = txs[0]
        if not isinstance(tx, dict):
            raise PaymentVerificationError("Invalid transaction payload")
        return tx

    @staticmethod
    def _extract_recipient(tx: dict[str, Any]) -> str:
        msg = tx.get("in_msg") or {}
        recipient = msg.get("destination") or msg.get("dest") or tx.get("account")
        return str(recipient or "")

    @staticmethod
    def _extract_amount(tx: dict[str, Any]) -> int:
        msg = tx.get("in_msg") or {}
        value = msg.get("value") or msg.get("value_extra") or tx.get("amount") or 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _extract_comment(tx: dict[str, Any]) -> str:
        msg = tx.get("in_msg") or {}
        comment = msg.get("message") or msg.get("comment") or tx.get("comment") or ""
        return str(comment)

    @staticmethod
    def _comment_matches_nonce(comment: str, raw_nonce: str, nonce_value: str) -> bool:
        if not comment:
            return False
        normalized_comment = comment.strip()
        if normalized_comment == raw_nonce or normalized_comment == nonce_value:
            return True
        # Nonce could be a JSON payload based on previous specifications it seems, we attempt to parse it
        # Nonce could be a JSON payload based on previous specifications it seems, we attempt to parse it
        try:
            comment_json = json.loads(normalized_comment)
            if isinstance(comment_json, dict):
                return str(comment_json.get("nonce", "")).strip() in {raw_nonce, nonce_value}
        except json.JSONDecodeError:
            return False
        return False
