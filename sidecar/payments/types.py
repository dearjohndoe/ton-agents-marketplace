from __future__ import annotations

from dataclasses import dataclass

from pytoniq_core import Transaction


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


@dataclass
class JettonPaymentTx:
    tx: Transaction
    amount: int       # jetton base units (e.g. micro-USDT)
    sender: str       # original sender from transfer_notification body
    nonce: str
