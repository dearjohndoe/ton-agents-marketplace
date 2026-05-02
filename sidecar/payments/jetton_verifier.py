from __future__ import annotations

import asyncio
import logging
import time

from tonutils.clients import LiteBalancer
from tonutils.types import NetworkGlobalID

from .jetton_monitor import JettonWalletMonitor
from .nonce import parse_nonce
from .types import PaymentVerificationError, VerifiedPayment

logger = logging.getLogger(__name__)


class JettonPaymentVerifier:
    """Verifies incoming jetton (USDT) payments on the agent wallet."""

    VERIFY_TIMEOUT = 15
    VERIFY_POLL = 0.5

    def __init__(
        self,
        agent_wallet: str,
        usdt_master: str,
        min_amount: int,
        payment_timeout_seconds: int,
        testnet: bool = False,
    ) -> None:
        self._agent_wallet = agent_wallet
        self._usdt_master = usdt_master
        self._min_amount = min_amount
        self._payment_timeout = payment_timeout_seconds
        self._network = NetworkGlobalID.TESTNET if testnet else NetworkGlobalID.MAINNET
        self._client: LiteBalancer | None = None
        self._monitor: JettonWalletMonitor | None = None
        self.jetton_wallet_address: str = ""

    async def start(self) -> None:
        from tonutils.contracts.jetton.master import JettonMasterStablecoin

        self._client = LiteBalancer.from_network_config(self._network)
        await self._client.connect()

        master = await JettonMasterStablecoin.from_address(self._client, self._usdt_master)
        addr = await master.get_wallet_address(self._agent_wallet)
        self.jetton_wallet_address = addr.to_str(
            is_user_friendly=True, is_bounceable=False,
        )
        logger.info(
            "JettonPaymentVerifier started: jetton_wallet=%s (testnet=%s)",
            self.jetton_wallet_address,
            self._network == NetworkGlobalID.TESTNET,
        )

        self._monitor = JettonWalletMonitor(
            self._client, self._agent_wallet, self.jetton_wallet_address,
        )
        await self._monitor.start()

    async def close(self) -> None:
        if self._monitor:
            await self._monitor.stop()
            self._monitor = None
        if self._client:
            await self._client.close()
            self._client = None

    async def verify(self, tx_hash: str, raw_nonce: str, min_amount: int | None = None) -> VerifiedPayment:
        if self._monitor is None:
            raise RuntimeError("JettonPaymentVerifier not started")

        nonce = parse_nonce(raw_nonce)
        required_amount = min_amount if min_amount is not None else self._min_amount
        deadline = time.time() + self.VERIFY_TIMEOUT

        while True:
            entry = self._monitor.get(nonce.value)

            if entry is not None:
                now_ts = int(time.time())
                if now_ts - entry.tx.now > self._payment_timeout:
                    raise PaymentVerificationError("Payment session expired")

                if entry.amount < required_amount:
                    raise PaymentVerificationError("Transaction amount is lower than required price")

                if not entry.sender:
                    raise PaymentVerificationError("Transaction sender is missing")

                self._monitor.consume(nonce.value)
                real_tx_hash = entry.tx.cell.hash.hex()
                return VerifiedPayment(
                    tx_hash=real_tx_hash,
                    sender=entry.sender,
                    recipient=self._agent_wallet,
                    amount=entry.amount,
                    comment=entry.nonce,
                )

            if time.time() >= deadline:
                raise PaymentVerificationError("Transaction not found")

            self._monitor.force()
            await asyncio.sleep(self.VERIFY_POLL)
