from __future__ import annotations

import asyncio
import logging
import time

from pytoniq_core import Transaction
from tonutils.clients import LiteBalancer
from tonutils.exceptions import BalancerError, ProviderResponseError

from .nonce import _parse_payment_nonce

logger = logging.getLogger(__name__)


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

    def consume(self, nonce: str) -> Transaction | None:
        """Atomically get and remove a cached transaction by nonce."""
        return self._by_nonce.pop(nonce.strip(), None)

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

        except (BalancerError, ProviderResponseError) as e:
            logger.warning("WalletMonitor: tx fetch interrupted (%s), partial results saved", e)

        except Exception:
            logger.exception("WalletMonitor poll failed")

        finally:
            if new_lt_watermark > self._last_processed_lt:
                self._last_processed_lt = new_lt_watermark

            # Evict stale entries
            for k, tx in list(self._by_nonce.items()):
                if tx.now < cutoff:
                    del self._by_nonce[k]

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
