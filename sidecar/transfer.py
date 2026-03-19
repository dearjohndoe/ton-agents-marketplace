from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from pytoniq_core import Cell, begin_cell
from tonutils.clients import LiteBalancer
from tonutils.contracts.wallet import WalletV4R2
from tonutils.types import NetworkGlobalID, PrivateKey

logger = logging.getLogger(__name__)

HEARTBEAT_OPCODE = 0xAC52AB67


def heartbeat_body(comment: str) -> Cell:
    return (
        begin_cell()
        .store_uint(HEARTBEAT_OPCODE, 32)
        .store_snake_string(comment)
        .end_cell()
    )


def text_comment_body(text: str) -> Cell:
    return (
        begin_cell()
        .store_uint(0, 32)
        .store_snake_string(text)
        .end_cell()
    )


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

    async def send(self, destination: str, amount: int, body: Cell) -> str:
        async with self._lock:
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

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._wallet = None


# Type alias for injection
TransferFn = Callable[[str, int, Cell], Awaitable[str]]
