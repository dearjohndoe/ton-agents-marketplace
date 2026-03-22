from __future__ import annotations

import asyncio
import json
import logging
import aiosqlite
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pytoniq_core import Transaction
from tonutils.clients import LiteBalancer
from tonutils.types import NetworkGlobalID
from transfer import PAYMENT_OPCODE

logger = logging.getLogger(__name__)


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

        # Run in background. Store history for 30 days.
        # TODO: Move to worker
        asyncio.create_task(self.cleanup(older_than_seconds=30 * 24 * 3600))

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
    
    async def cleanup(self, older_than_seconds: int) -> None:
        if not self._conn:
            await self.init()
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        cutoff_iso = cutoff_time.isoformat()
        await self._conn.execute(
            "DELETE FROM processed_txs WHERE created_at < ?",
            (cutoff_iso,),
        )
        await self._conn.commit()


def parse_nonce(raw_nonce: str) -> NonceMeta:
    return NonceMeta(value=raw_nonce.strip())


def _parse_payment_nonce(body: Any) -> str:
    if body is None:
        return ""
    try:
        s = body.begin_parse()
        if s.remaining_bits < 32:
            return ""
        if s.load_uint(32) != PAYMENT_OPCODE:
            return ""
        return s.load_snake_string()
    except Exception:
        return ""


class WalletMonitor:
    """Background worker that polls the agent wallet and caches txs by comment nonce."""

    CACHE_TTL = 600  # seconds — evict transactions older than this

    def __init__(self, client: LiteBalancer, address: str, poll_interval: int = 10) -> None:
        self._client = client
        self._address = address
        self._poll_interval = poll_interval
        self._by_nonce: dict[str, Transaction] = {}
        self._force = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_processed_lt: int = 0

    async def start(self) -> None:
        await self._poll()  # populate cache immediately before accepting requests
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        self._force.set()  # wake up the loop so it exits promptly
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def force(self) -> None:
        """Wake the monitor to poll immediately."""
        self._force.set()

    def get(self, nonce: str) -> Transaction | None:
        return self._by_nonce.get(nonce.strip())

    async def _poll(self) -> None:
        try:
            cutoff = time.time() - self.CACHE_TTL
            current_lt = None
            new_lt_watermark = self._last_processed_lt
            
            while True:
                kwargs = {"limit": 50}
                if current_lt is not None:
                    kwargs["from_lt"] = current_lt
                    
                txs = await self._client.get_transactions(self._address, **kwargs)
                if not txs:
                    break

                batch_had_new = False
                for tx in txs:
                    if tx.lt <= self._last_processed_lt:
                        # Reached transactions we have already fully processed in previous polls
                        break
                    
                    if tx.now < cutoff:
                        # Reached transactions that are too old
                        break
                        
                    if tx.lt > new_lt_watermark:
                        new_lt_watermark = tx.lt
                        
                    if tx.in_msg is None:
                        continue
                        
                    comment = _parse_payment_nonce(tx.in_msg.body)
                    if comment:
                        self._by_nonce[comment.strip()] = tx
                        batch_had_new = True

                # Determine if we should fetch the next page
                last_tx = txs[-1]
                if last_tx.lt <= self._last_processed_lt or last_tx.now < cutoff:
                    break
                    
                # Continue fetching from the last seen transaction LT
                # Note: this will re-fetch the last_tx as the first element of next batch,
                # but duplicate handling (or just overwriting in dict dict) handles it safely.
                if current_lt == last_tx.lt:
                    break  # Avoid infinite loop if API behaves unexpectedly
                current_lt = last_tx.lt

            self._last_processed_lt = new_lt_watermark

            # Evict stale entries
            for k, tx in list(self._by_nonce.items()):
                if tx.now < cutoff:
                    del self._by_nonce[k]

        except Exception:
            logger.exception("WalletMonitor poll failed")

    async def _loop(self) -> None:
        cooldown = 2.0  # minimum seconds between polls to prevent LiteServer spam
        while not self._stop.is_set():
            self._force.clear()
            try:
                await asyncio.wait_for(self._force.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
                
            start_ts = time.time()
            await self._poll()
            
            elapsed = time.time() - start_ts
            if elapsed < cooldown:
                await asyncio.sleep(cooldown - elapsed)


class PaymentVerifier:
    VERIFY_TIMEOUT = 30   # seconds to wait for tx to appear on-chain
    VERIFY_POLL    = 3    # seconds between cache re-checks while waiting

    def __init__(
        self,
        agent_wallet: str,
        min_amount: int,
        payment_timeout_seconds: int,
        enforce_comment_nonce: bool = True,
        testnet: bool = False,
    ) -> None:
        self._agent_wallet = agent_wallet
        self._min_amount = min_amount
        self._payment_timeout = payment_timeout_seconds
        self._enforce_comment_nonce = enforce_comment_nonce
        self._network = NetworkGlobalID.TESTNET if testnet else NetworkGlobalID.MAINNET
        self._client: LiteBalancer | None = None
        self._monitor: WalletMonitor | None = None

    async def start(self) -> None:
        self._client = LiteBalancer.from_network_config(self._network)
        await self._client.connect()
        self._monitor = WalletMonitor(self._client, self._agent_wallet)
        await self._monitor.start()
        logger.info("PaymentVerifier started (testnet=%s)", self._network == NetworkGlobalID.TESTNET)

    async def close(self) -> None:
        if self._monitor:
            await self._monitor.stop()
            self._monitor = None
        if self._client:
            await self._client.close()
            self._client = None

    async def verify(self, tx_hash: str, raw_nonce: str, min_amount: int | None = None) -> VerifiedPayment:
        if self._monitor is None:
            raise RuntimeError("PaymentVerifier not started")

        nonce = parse_nonce(raw_nonce)
        required_amount = min_amount if min_amount is not None else self._min_amount
        deadline = time.time() + self.VERIFY_TIMEOUT

        while True:
            tx = self._monitor.get(nonce.value)

            if tx is not None:
                now_ts = int(time.time())
                if now_ts - tx.now > self._payment_timeout:
                    raise PaymentVerificationError("Payment session expired")

                try:
                    sender = str(tx.in_msg.info.src)
                except Exception:
                    sender = ""

                try:
                    amount = int(tx.in_msg.info.value.grams)
                except Exception:
                    amount = 0

                if amount < required_amount:
                    raise PaymentVerificationError("Transaction amount is lower than required price")

                if not sender:
                    raise PaymentVerificationError("Transaction sender is missing")

                comment = _parse_payment_nonce(tx.in_msg.body)
                return VerifiedPayment(
                    tx_hash=tx_hash,
                    sender=sender,
                    recipient=self._agent_wallet,
                    amount=amount,
                    comment=comment,
                )

            if time.time() >= deadline:
                raise PaymentVerificationError("Transaction not found")

            # Not in cache yet — force an immediate poll, then wait before retrying
            self._monitor.force()
            await asyncio.sleep(self.VERIFY_POLL)

