from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from aiohttp import web

from jetton import USDT_MASTER_MAINNET, USDT_MASTER_TESTNET
from payments import PaymentVerificationError
from settings import AgentSku

from api.http.responses import render_done_response

if TYPE_CHECKING:
    from api.http.handlers.invoke import ParsedInvoke
    from api.app import SidecarApp

logger = logging.getLogger("sidecar")


def unlock_quote(quote_id: str | None, sidecar: "SidecarApp") -> None:
    if quote_id and quote_id in sidecar.quotes:
        sidecar.quotes[quote_id].locked = False


async def build_402_response(
    parsed: "ParsedInvoke",
    sku: AgentSku,
    sidecar: "SidecarApp",
    eff_ton: int,
    eff_usd: int,
    min_ton: int,
    min_usdt: int,
) -> web.Response:
    """Preflight response: stock gate + 402 Payment Required."""
    view = await sidecar.stock.get_view(sku.sku_id)
    if view.stock_left is not None and view.stock_left <= 0:
        return web.json_response({"error": "out_of_stock", "sku": sku.sku_id}, status=409)

    nonce = parsed.nonce
    if not nonce or not nonce.endswith(f":{sidecar.sidecar_id}"):
        nonce = f"{uuid.uuid4().hex[:16]}:{sidecar.sidecar_id}"

    payment_options: list[dict[str, Any]] = []
    if eff_ton:
        payment_options.append({
            "rail": "TON",
            "address": sidecar.settings.agent_wallet,
            "amount": str(min_ton),
            "memo": nonce,
            "sku": sku.sku_id,
        })
    if eff_usd and min_usdt:
        usdt_master = USDT_MASTER_TESTNET if sidecar.settings.testnet else USDT_MASTER_MAINNET
        payment_options.append({
            "rail": "USDT",
            "address": sidecar.settings.agent_wallet,
            "amount": str(min_usdt),
            "memo": nonce,
            "sku": sku.sku_id,
            "token": {"symbol": "USDT", "master": usdt_master, "decimals": 6},
        })

    resp_body: dict[str, Any] = {
        "error": "Payment required",
        "payment_request": payment_options[0] if payment_options else {},
        "payment_options": payment_options,
    }

    headers: dict[str, str] = {}
    if eff_ton:
        headers["x-ton-pay-address"] = sidecar.settings.agent_wallet
        headers["x-ton-pay-amount"] = str(min_ton)
        headers["x-ton-pay-nonce"] = nonce

    return web.json_response(resp_body, status=402, headers=headers)


async def verify_payment(
    parsed: "ParsedInvoke",
    sku: AgentSku,
    sidecar: "SidecarApp",
    min_ton: int,
    min_usdt: int,
) -> Any | web.Response:
    """Run the right verifier (TON or USDT). Unlocks the quote on every error path."""
    try:
        if parsed.rail == "USDT":
            if not sidecar.jetton_verifier:
                unlock_quote(parsed.quote_id, sidecar)
                logger.critical(
                    "USDT payment received but jetton_verifier is not configured — "
                    "tx=%s nonce=%s — payment requires manual refund",
                    parsed.tx_hash, parsed.nonce,
                )
                return web.json_response({"error": "USDT payments not configured"}, status=400)
            if min_usdt == 0:
                unlock_quote(parsed.quote_id, sidecar)
                return web.json_response(
                    {"error": "USDT price unavailable for this SKU", "sku": sku.sku_id},
                    status=503,
                )
            return await sidecar.jetton_verifier.verify(
                tx_hash=parsed.tx_hash, raw_nonce=parsed.nonce, min_amount=min_usdt,
            )
        return await sidecar.verifier.verify(
            tx_hash=parsed.tx_hash, raw_nonce=parsed.nonce, min_amount=min_ton,
        )
    except PaymentVerificationError as exc:
        unlock_quote(parsed.quote_id, sidecar)
        return web.json_response({"error": str(exc)}, status=402)
    except Exception:
        logger.exception("Payment verification error")
        unlock_quote(parsed.quote_id, sidecar)
        return web.json_response({"error": "Payment verification failed"}, status=502)


async def claim_stock(
    parsed: "ParsedInvoke",
    sku: AgentSku,
    sidecar: "SidecarApp",
    verified_payment: Any,
) -> tuple[str | None, list[str], web.Response | None]:
    """Reserve stock for direct calls (quote calls already reserved at quote time).

    Returns (reservation_key, created_keys, error_response).
    """
    created: list[str] = []
    if parsed.quote_id:
        return parsed.quote_id, created, None
    if not sidecar.stock.has_tracked_stock(sku.sku_id):
        return None, created, None

    reservation_key = verified_payment.tx_hash
    try:
        reserved = await sidecar.stock.reserve(
            sku.sku_id, reservation_key, sidecar.settings.final_timeout,
        )
    except Exception:
        logger.exception("stock.reserve (post-payment) failed")
        reserved = False
    if not reserved:
        # Race lost between preflight and payment. Refund the user.
        try:
            await sidecar.refund_user(
                recipient=verified_payment.sender,
                payment_amount=verified_payment.amount,
                original_tx_hash=verified_payment.tx_hash,
                reason="out_of_stock",
                rail=parsed.rail,
            )
        except Exception:
            logger.exception("Refund after out_of_stock race failed")
        return None, created, web.json_response(
            {"error": "out_of_stock", "sku": sku.sku_id, "refunded": True}, status=409,
        )
    created.append(reservation_key)
    return reservation_key, created, None


def build_agent_payload(parsed: "ParsedInvoke", sku: AgentSku) -> dict[str, Any]:
    agent_body = dict(parsed.body)
    agent_body["sku"] = sku.sku_id
    for field_name, file_path in parsed.uploaded_files.items():
        agent_body[f"{field_name}_path"] = str(file_path)
        if f"{field_name}_name" not in agent_body:
            agent_body[f"{field_name}_name"] = file_path.name
    return {
        "capability": parsed.capability,
        "sku": sku.sku_id,
        "body": agent_body,
    }


async def wait_and_render(job_id: str, sidecar: "SidecarApp") -> web.Response:
    record = await sidecar.jobs.wait_for_completion(job_id, timeout_seconds=sidecar.settings.sync_timeout)
    if record is None:
        return web.json_response({"job_id": job_id, "status": "pending"})
    if record.status == "done":
        return render_done_response(
            job_id, record.result,
            sidecar._file_store, sidecar._file_store_dir, sidecar._file_store_ttl,
        )
    if record.status == "error":
        return web.json_response({"job_id": job_id, "status": "error", "error": record.error}, status=500)
    return web.json_response({"job_id": job_id, "status": "pending"})
