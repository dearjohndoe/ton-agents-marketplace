from __future__ import annotations

import logging

from jetton import USDT_REFUND_FEE
from transfer import TransferSender, refund_body

logger = logging.getLogger("sidecar")


async def refund_user(
    *,
    sender: TransferSender,
    agent_jetton_wallet: str | None,
    sidecar_id: str,
    refund_fee_nanoton: int,
    recipient: str,
    payment_amount: int,
    original_tx_hash: str,
    reason: str,
    rail: str = "TON",
) -> str | None:
    """Send refund back to `recipient`. Returns refund tx hash on success, None otherwise."""
    if rail == "USDT":
        refund_amount = max(payment_amount - USDT_REFUND_FEE, 0)
        if refund_amount <= 0:
            logger.warning(
                "USDT refund skipped: amount too small after fee",
                extra={"tx_hash": original_tx_hash, "payment_amount": payment_amount},
            )
            return None
        try:
            fwd = refund_body(original_tx_hash, reason, sidecar_id)
            return await sender.send_jetton(
                own_jetton_wallet=agent_jetton_wallet or "",
                destination=recipient,
                jetton_amount=refund_amount,
                forward_payload=fwd,
            )
        except Exception:
            logger.exception("Failed to send USDT refund")
            return None

    refund_amount = max(payment_amount - refund_fee_nanoton, 0)
    if refund_amount <= 0:
        logger.warning(
            "Refund skipped because amount is not enough after fee",
            extra={
                "tx_hash": original_tx_hash,
                "payment_amount": payment_amount,
                "refund_fee": refund_fee_nanoton,
            },
        )
        return None

    try:
        return await sender.send(recipient, refund_amount, refund_body(original_tx_hash, reason, sidecar_id))
    except Exception:
        logger.exception("Failed to send refund")
        return None
