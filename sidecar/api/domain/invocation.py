from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable

import api  # late binding for monkeypatched run_agent_subprocess
from api.domain.result_processing import is_out_of_stock_result
from api.validation import validate_result_structure

logger = logging.getLogger("sidecar")


def create_runner(
    *,
    refund_user: Callable[..., Awaitable[str | None]],
    stock,
    agent_command: str,
    final_timeout: int,
    sidecar_id: str,
    agent_payload: dict[str, Any],
    sender: str,
    amount: int,
    tx_hash: str,
    uploaded_files: dict[str, Path] | None = None,
    rail: str = "TON",
    reservation_key: str | None = None,
) -> Callable[[], Awaitable[dict[str, Any]]]:
    async def runner() -> dict[str, Any]:
        try:
            raw = await api.run_agent_subprocess(
                command=agent_command,
                payload=agent_payload,
                timeout_seconds=final_timeout,
                env={
                    "OWN_SIDECAR_ID": sidecar_id,
                    "CALLER_ADDRESS": sender,
                    "CALLER_TX_HASH": tx_hash,
                    "PAYMENT_RAIL": rail,
                },
            )

            if is_out_of_stock_result(raw):
                reason = str(raw.get("reason") or "agent reported out of stock")
                refund_tx = await refund_user(
                    recipient=sender,
                    payment_amount=amount,
                    original_tx_hash=tx_hash,
                    reason="out_of_stock",
                    rail=rail,
                )
                if reservation_key:
                    try:
                        await stock.agent_out_of_stock(reservation_key)
                    except Exception:
                        logger.exception("agent_out_of_stock bookkeeping failed")
                # Return a special "done" record — handle_invoke / handle_result
                # render it as refunded_out_of_stock to the caller.
                return {
                    "result": {
                        "status": "refunded_out_of_stock",
                        "reason": reason,
                        "refund_tx": refund_tx,
                    }
                }

            validate_result_structure(raw)
            if reservation_key:
                try:
                    await stock.commit_sold(reservation_key, tx_hash)
                except Exception:
                    logger.exception("commit_sold failed (agent succeeded but stock bookkeeping broke)")
            return raw
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                short_reason = "timeout"
            elif isinstance(exc, ValueError):
                short_reason = "invalid_response"
            elif isinstance(exc, RuntimeError):
                short_reason = "execution_failed"
            else:
                short_reason = "internal_error"

            try:
                await refund_user(
                    recipient=sender,
                    payment_amount=amount,
                    original_tx_hash=tx_hash,
                    reason=short_reason,
                    rail=rail,
                )
            except Exception:
                logger.exception("Refund sub-task failed inside runner")
            if reservation_key:
                try:
                    await stock.release(reservation_key)
                except Exception:
                    logger.exception("stock.release failed inside runner")
            raise
        finally:
            if uploaded_files:
                for file_path in uploaded_files.values():
                    try:
                        shutil.rmtree(file_path.parent, ignore_errors=True)
                    except Exception:
                        logger.warning("Failed to cleanup uploaded file dir %s", file_path.parent)
    return runner
