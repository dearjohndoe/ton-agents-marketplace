from __future__ import annotations

import asyncio
import logging
import time

from tonutils.clients import LiteBalancer

from jetton import parse_transfer_notification

from .nonce import _parse_payment_nonce
from .types import JettonPaymentTx

logger = logging.getLogger(__name__)


class JettonWalletMonitor:
    """Background worker that polls the agent wallet for incoming jetton
    transfer_notification messages and caches them by payment nonce."""

    CACHE_TTL = 600

    def __init__(
        self,
        client: LiteBalancer,
        agent_address: str,
        jetton_wallet_address: str,
        poll_interval: int = 10,
    ) -> None:
        self._client = client
        self._address = agent_address
        self._jetton_wallet = jetton_wallet_address
        self._poll_interval = poll_interval
        self._by_nonce: dict[str, JettonPaymentTx] = {}
        self._force = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_processed_lt: int = 0

    async def start(self) -> None:
        await self._poll()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        self._force.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def force(self) -> None:
        self._force.set()

    def get(self, nonce: str) -> JettonPaymentTx | None:
        return self._by_nonce.get(nonce.strip())

    def consume(self, nonce: str) -> JettonPaymentTx | None:
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

                for tx in txs:
                    if tx.lt <= self._last_processed_lt:
                        break
                    if tx.now < cutoff:
                        break
                    if tx.lt > new_lt_watermark:
                        new_lt_watermark = tx.lt
                    if tx.in_msg is None:
                        continue

                    # Only accept transfer_notifications from the expected jetton wallet
                    try:
                        src = tx.in_msg.info.src.to_str(
                            is_user_friendly=True, is_bounceable=False,
                        )
                    except Exception:
                        continue
                    if src != self._jetton_wallet:
                        continue

                    notification = parse_transfer_notification(tx.in_msg.body)
                    if notification is None:
                        continue

                    # Extract nonce from forward_payload using same parser as TON rail
                    nonce = _parse_payment_nonce(notification.forward_payload)
                    if not nonce:
                        continue

                    self._by_nonce[nonce.strip()] = JettonPaymentTx(
                        tx=tx,
                        amount=notification.amount,
                        sender=notification.sender,
                        nonce=nonce,
                    )

                last_tx = txs[-1]
                if last_tx.lt <= self._last_processed_lt or last_tx.now < cutoff:
                    break
                if current_lt == last_tx.lt:
                    break
                current_lt = last_tx.lt

            self._last_processed_lt = new_lt_watermark

            for k, entry in list(self._by_nonce.items()):
                if entry.tx.now < cutoff:
                    del self._by_nonce[k]

        except Exception:
            logger.exception("JettonWalletMonitor poll failed")

    async def _loop(self) -> None:
        cooldown = 2.0
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
