from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from jetton import USDT_MASTER_MAINNET, USDT_MASTER_TESTNET
from payments import PaymentVerificationError, parse_nonce
from settings import AgentSku

from api.domain.quoting import QuoteEntry, cleanup_expired_quotes
from api.domain.pricing import resolve_sku
from api.http.multipart import parse_multipart_invoke
from api.http.responses import render_done_response
from api.infra.files import cleanup_uploaded_files
from api.validation import validate_body

if TYPE_CHECKING:
    from api.app import SidecarApp

logger = logging.getLogger("sidecar")


@dataclass
class ParsedInvoke:
    tx_hash: str
    nonce: str
    capability: str
    quote_id: str | None
    rail: str
    sku_field: str | None
    body: dict[str, Any]
    payload: dict[str, Any]  # full request payload (for validate_body)
    uploaded_files: dict[str, Path] = field(default_factory=dict)


async def _parse_invoke_request(
    request: web.Request, file_store_dir: Path
) -> ParsedInvoke | web.Response:
    try:
        if request.content_type and "multipart/form-data" in request.content_type:
            tx_hash, nonce, capability, quote_id, rail, sku_field, body, uploaded_files = \
                await parse_multipart_invoke(request, file_store_dir)
            payload = {"body": body}
            return ParsedInvoke(
                tx_hash=tx_hash, nonce=nonce, capability=capability,
                quote_id=quote_id, rail=rail, sku_field=sku_field,
                body=body, payload=payload, uploaded_files=uploaded_files,
            )
        data = await request.json()
        return ParsedInvoke(
            tx_hash=str(data.get("tx", "")).strip(),
            nonce=str(data.get("nonce", "")).strip(),
            capability=str(data.get("capability", "")).strip(),
            quote_id=str(data.get("quote_id", "")).strip() or None,
            rail=str(data.get("rail", "")).strip().upper() or "TON",
            sku_field=str(data.get("sku", "")).strip() or None,
            body=data.get("body", {}),
            payload=data,
        )
    except Exception:
        return web.json_response({"error": "Invalid request"}, status=400)


def _resolve_sku_for_invoke(
    parsed: ParsedInvoke, sidecar: "SidecarApp"
) -> tuple[AgentSku | None, web.Response | None]:
    """Quote-bound calls derive SKU from the quote; direct calls use sku field."""
    quote_entry = sidecar.quotes.get(parsed.quote_id) if parsed.quote_id else None
    if quote_entry is not None:
        sku = sidecar._skus_by_id.get(quote_entry.sku_id)
        if sku is None:
            return None, web.json_response({"error": "Quote references unknown SKU"}, status=500)
        return sku, None
    return resolve_sku(parsed.sku_field, sidecar._skus_by_id, sidecar._single_sku, sidecar.settings.skus)


async def _resolve_amounts(
    sku: AgentSku, sidecar: "SidecarApp"
) -> tuple[int, int, int, int]:
    """Return (eff_ton, eff_usd, min_ton, min_usdt) for the SKU. Dynamic SKUs hit the agent."""
    eff_ton = sku.price_ton or 0
    eff_usd = sku.price_usd or 0
    if sku.price_ton == 0 and sku.price_usd == 0:
        try:
            dp = (await sidecar._fetch_dynamic_prices()).get(sku.sku_id, {})
            eff_ton = dp.get("ton") or 0
            eff_usd = dp.get("usd") or 0
        except Exception:
            logger.warning("Dynamic price fetch failed for SKU %s", sku.sku_id)
    return eff_ton, eff_usd, eff_ton or 0, eff_usd or 0


def _apply_quote_amounts(
    parsed: ParsedInvoke,
    sidecar: "SidecarApp",
    min_ton: int,
    min_usdt: int,
) -> tuple[QuoteEntry | None, int, int, web.Response | None]:
    """Override amounts from a quote entry; report quote errors."""
    if not parsed.quote_id:
        return None, min_ton, min_usdt, None
    cleanup_expired_quotes(sidecar.quotes)
    quote_entry = sidecar.quotes.get(parsed.quote_id)
    if quote_entry is None:
        return None, min_ton, min_usdt, web.json_response(
            {"error": "Quote not found or expired"}, status=400,
        )
    if quote_entry.locked and parsed.tx_hash:
        return None, min_ton, min_usdt, web.json_response(
            {"error": "Quote is currently locked by another request"}, status=409,
        )
    new_ton = quote_entry.price
    new_usdt = quote_entry.price_usdt or min_usdt
    return quote_entry, new_ton, new_usdt, None


async def _build_402_response(
    parsed: ParsedInvoke,
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


def _unlock_quote(quote_id: str | None, sidecar: "SidecarApp") -> None:
    if quote_id and quote_id in sidecar.quotes:
        sidecar.quotes[quote_id].locked = False


async def _verify_payment(
    parsed: ParsedInvoke,
    sku: AgentSku,
    sidecar: "SidecarApp",
    min_ton: int,
    min_usdt: int,
) -> Any | web.Response:
    """Run the right verifier (TON or USDT) and return the verified payment, or an error response.

    Unlocks the quote on every error path.
    """
    try:
        if parsed.rail == "USDT":
            if not sidecar.jetton_verifier:
                _unlock_quote(parsed.quote_id, sidecar)
                logger.critical(
                    "USDT payment received but jetton_verifier is not configured — "
                    "tx=%s nonce=%s — payment requires manual refund",
                    parsed.tx_hash, parsed.nonce,
                )
                return web.json_response({"error": "USDT payments not configured"}, status=400)
            if min_usdt == 0:
                _unlock_quote(parsed.quote_id, sidecar)
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
        _unlock_quote(parsed.quote_id, sidecar)
        return web.json_response({"error": str(exc)}, status=402)
    except Exception:
        logger.exception("Payment verification error")
        _unlock_quote(parsed.quote_id, sidecar)
        return web.json_response({"error": "Payment verification failed"}, status=502)


async def _claim_stock(
    parsed: ParsedInvoke,
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


def _build_agent_payload(
    parsed: ParsedInvoke, sku: AgentSku
) -> dict[str, Any]:
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


async def _wait_and_render(
    job_id: str, sidecar: "SidecarApp"
) -> web.Response:
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


async def handle_invoke(request: web.Request, sidecar: "SidecarApp") -> web.Response:
    parsed = await _parse_invoke_request(request, sidecar._file_store_dir)
    if isinstance(parsed, web.Response):
        return parsed

    uploaded_files = parsed.uploaded_files
    ownership_transferred = False
    created_reservation_keys: list[str] = []

    try:
        if not parsed.capability:
            return web.json_response({"error": "capability is required"}, status=400)
        if parsed.capability != sidecar.settings.capability:
            return web.json_response({"error": "Unsupported capability"}, status=400)

        sku, sku_err = _resolve_sku_for_invoke(parsed, sidecar)
        if sku_err is not None:
            return sku_err
        assert sku is not None

        if parsed.rail == "TON" and sku.price_ton is None:
            return web.json_response(
                {"error": "unsupported_rail_for_sku", "sku": sku.sku_id, "rail": parsed.rail}, status=400,
            )
        if parsed.rail == "USDT" and sku.price_usd is None:
            return web.json_response(
                {"error": "unsupported_rail_for_sku", "sku": sku.sku_id, "rail": parsed.rail}, status=400,
            )

        eff_ton, eff_usd, min_ton, min_usdt = await _resolve_amounts(sku, sidecar)
        quote_entry, min_ton, min_usdt, quote_err = _apply_quote_amounts(parsed, sidecar, min_ton, min_usdt)
        if quote_err is not None:
            return quote_err

        if not parsed.tx_hash:
            return await _build_402_response(parsed, sku, sidecar, eff_ton, eff_usd, min_ton, min_usdt)

        missing = validate_body(parsed.payload, sidecar.args_schema, has_tx=True, uploaded_files=uploaded_files)
        if missing:
            return web.json_response({"error": "Missing required fields", "missing": missing}, status=400)
        if not parsed.nonce:
            return web.json_response({"error": "nonce is required with tx"}, status=400)

        if parsed.quote_id and quote_entry:
            quote_entry.locked = True

        nonce_meta = parse_nonce(parsed.nonce)
        if not nonce_meta.value.endswith(f":{sidecar.sidecar_id}"):
            _unlock_quote(parsed.quote_id, sidecar)
            return web.json_response({"error": "Nonce sidecar_id mismatch"}, status=402)

        if await sidecar.tx_store.is_processed(parsed.tx_hash):
            _unlock_quote(parsed.quote_id, sidecar)
            return web.json_response({"error": "Transaction already used"}, status=409)

        verified = await _verify_payment(parsed, sku, sidecar, min_ton, min_usdt)
        if isinstance(verified, web.Response):
            return verified

        if await sidecar.tx_store.is_processed(verified.tx_hash):
            _unlock_quote(parsed.quote_id, sidecar)
            return web.json_response({"error": "Transaction already used"}, status=409)

        try:
            await sidecar.tx_store.mark_processed(verified.tx_hash)
        except Exception:
            _unlock_quote(parsed.quote_id, sidecar)
            return web.json_response({"error": "Failed to persist transaction"}, status=500)

        reservation_key, created_reservation_keys, stock_err = await _claim_stock(parsed, sku, sidecar, verified)
        if stock_err is not None:
            return stock_err

        if parsed.quote_id and parsed.quote_id in sidecar.quotes:
            del sidecar.quotes[parsed.quote_id]

        agent_payload = _build_agent_payload(parsed, sku)

        # Runner takes ownership of uploaded_files and the reservation; outer
        # finally must not double-clean.
        ownership_transferred = True
        job_id = await sidecar.jobs.submit(
            sidecar._create_runner(
                agent_payload, verified.sender, verified.amount,
                parsed.tx_hash, uploaded_files, parsed.rail, reservation_key,
            )
        )
        if reservation_key:
            try:
                await sidecar.stock.attach_job(
                    reservation_key, job_id, extend_ttl_seconds=sidecar.settings.final_timeout,
                )
            except Exception:
                logger.exception("attach_job failed")
    finally:
        if not ownership_transferred:
            if uploaded_files:
                cleanup_uploaded_files(uploaded_files)
            for key in created_reservation_keys:
                try:
                    await sidecar.stock.release(key)
                except Exception:
                    logger.exception("Failed to release reservation on early exit")

    return await _wait_and_render(job_id, sidecar)
