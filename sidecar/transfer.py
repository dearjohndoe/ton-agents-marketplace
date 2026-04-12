from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import json

from pytoniq_core import Cell, begin_cell
from tonutils.clients import LiteBalancer
from tonutils.contracts.wallet import WalletV4R2
from tonutils.types import NetworkGlobalID, PrivateKey

logger = logging.getLogger(__name__)

HEARTBEAT_OPCODE = 0xAC52AB67
PAYMENT_OPCODE = 0x50415900
REFUND_OPCODE = 0x52464E44


def heartbeat_body(comment: str) -> Cell:
    return (
        begin_cell()
        .store_uint(HEARTBEAT_OPCODE, 32)
        .store_snake_string(comment)
        .end_cell()
    )


def payment_body(nonce: str) -> Cell:
    return (
        begin_cell()
        .store_uint(PAYMENT_OPCODE, 32)
        .store_snake_string(nonce)
        .end_cell()
    )


def refund_body(original_tx_hash: str, reason: str, sidecar_id: str) -> Cell:
    return (
        begin_cell()
        .store_uint(REFUND_OPCODE, 32)
        .store_snake_string(json.dumps({"tx": original_tx_hash, "reason": reason, "sidecar_id": sidecar_id}))
        .end_cell()
    )


def text_comment_body(text: str) -> Cell:
    return (
        begin_cell()
        .store_uint(0, 32)
        .store_snake_string(text)
        .end_cell()
    )


SEND_MAX_RETRIES = 3
SEND_RETRY_DELAYS = [0.5, 2, 5]  # seconds between retries


class TransferSender:
    def __init__(
        self,
        private_key_hex: str,
        testnet: bool = False,
    ) -> None:
        self._private_key_hex = private_key_hex
        self._network = NetworkGlobalID.TESTNET if testnet else NetworkGlobalID.MAINNET
        self._client: LiteBalancer | None = None
        self._wallet: WalletV4R2 | None = None
        self._lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        if self._client is not None:
            return
        self._client = LiteBalancer.from_network_config(self._network)
        await self._client.connect()
        pk = PrivateKey(bytes.fromhex(self._private_key_hex.removeprefix("0x")))
        self._wallet = WalletV4R2.from_private_key(self._client, pk)
        logger.info("Transfer sender initialized via liteserver (testnet=%s)", self._network == NetworkGlobalID.TESTNET)

    async def _reconnect(self) -> None:
        """Drop current liteserver connection and re-initialize."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
            self._wallet = None
        await self._ensure_initialized()

    async def send(self, destination: str, amount: int, body: Cell) -> str:
        async with self._lock:
            last_exc: Exception | None = None
            for attempt in range(SEND_MAX_RETRIES):
                try:
                    await self._ensure_initialized()
                    assert self._wallet is not None
                    msg = await self._wallet.transfer(
                        destination=destination,
                        amount=amount,
                        body=body,
                        bounce=False,
                    )
                    tx_hash = msg.normalized_hash
                    logger.info(
                        "Transfer sent: hash=%s dest=%s amount=%d",
                        tx_hash,
                        destination,
                        amount,
                    )
                    return tx_hash
                except Exception as exc:
                    last_exc = exc
                    if attempt >= SEND_MAX_RETRIES - 1:
                        logger.warning(
                            "Transfer attempt %d/%d failed (dest=%s amount=%d): %s",
                            attempt + 1, SEND_MAX_RETRIES, destination, amount, exc,
                        )
                        break
                    delay = SEND_RETRY_DELAYS[min(attempt, len(SEND_RETRY_DELAYS) - 1)]
                    logger.warning(
                        "Transfer attempt %d/%d failed (dest=%s amount=%d): %s. Retrying in %ds",
                        attempt + 1, SEND_MAX_RETRIES, destination, amount, exc, delay,
                    )
                    await self._reconnect()
                    await asyncio.sleep(delay)

            logger.error(
                "Transfer failed after %d attempts: dest=%s amount=%d",
                SEND_MAX_RETRIES, destination, amount,
            )
            raise last_exc  # type: ignore[misc]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._wallet = None


# Type alias for injection
TransferFn = Callable[[str, int, Cell], Awaitable[str]]
