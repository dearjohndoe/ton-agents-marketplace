from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from aiohttp import web

import api  # late binding for monkeypatched run_agent_subprocess
from heartbeat import HeartbeatConfig, HeartbeatManager
from jobs import JobStore
from storage import StateStore
from transfer import TransferSender, refund_body
from payments import PaymentVerificationError, PaymentVerifier, JettonPaymentVerifier, ProcessedTxStore, parse_nonce
from jetton import USDT_MASTER_MAINNET, USDT_MASTER_TESTNET, USDT_REFUND_FEE
from settings import Settings, AgentSku, DEFAULT_SKU_ID  # noqa: F401 — re-exported via api package
from stock import StockStore

from api.constants import (
    DESCRIBE_TIMEOUT,
    DYNAMIC_PRICE_CACHE_TTL,
    DEFAULT_QUOTE_TTL,
    IMAGE_EXT_MIME,
)
from api.describe import fetch_describe
from api.validation import validate_body, validate_result_structure
from api.domain.result_processing import (
    is_out_of_stock_result,
    process_file_result,
    safe_extract_result,
)

logger = logging.getLogger("sidecar")


@dataclass
class QuoteEntry:
    price: int
    expires_at: float  # unix timestamp
    sku_id: str
    price_usdt: int | None = None
    locked: bool = False


class SidecarApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.args_schema: dict[str, Any] = {}
        self.result_schema: dict[str, Any] | None = None
        self._file_store: dict[str, dict[str, Any]] = {}
        self._file_store_dir = Path(settings.file_store_dir)
        self._file_store_ttl = settings.file_store_ttl
        self._images_dir = Path(settings.images_dir).resolve()
        self.jobs = JobStore(ttl_seconds=settings.jobs_ttl)
        self.tx_store = ProcessedTxStore(settings.tx_db_path)
        self.stock = StockStore(settings.stock_db_path)
        self._skus_by_id: dict[str, AgentSku] = {s.sku_id: s for s in settings.skus}
        self._single_sku: AgentSku | None = settings.skus[0] if len(settings.skus) == 1 else None
        self.verifier = PaymentVerifier(
            agent_wallet=settings.agent_wallet,
            min_amount=settings.agent_price,
            payment_timeout_seconds=settings.payment_timeout,
            enforce_comment_nonce=settings.enforce_comment_nonce,
            testnet=settings.testnet,
        )
        self.state_store = StateStore(settings.state_path)
        self.sender = TransferSender(
            private_key_hex=settings.agent_wallet_pk,
            testnet=settings.testnet,
        )
        self.jetton_verifier: JettonPaymentVerifier | None = None
        self._agent_jetton_wallet: str | None = None
        if any(s.price_usd is not None for s in settings.skus):
            usdt_master = USDT_MASTER_TESTNET if settings.testnet else USDT_MASTER_MAINNET
            self.jetton_verifier = JettonPaymentVerifier(
                agent_wallet=settings.agent_wallet,
                usdt_master=usdt_master,
                min_amount=settings.agent_price_usdt or 0,
                payment_timeout_seconds=settings.payment_timeout,
                testnet=settings.testnet,
            )
        self.stop_event = asyncio.Event()
        self.sidecar_id: str = ""
        # Dynamic pricing cache (populated via agent mode=prices when SKU price==0)
        self._dynamic_prices: dict[str, dict[str, int]] = {}
        self._dynamic_prices_ts: float = 0.0
        self._dynamic_prices_lock: asyncio.Lock | None = None
        self.heartbeat = HeartbeatManager(
            config=HeartbeatConfig(
                registry_address=settings.registry_address,
                endpoint=settings.agent_endpoint,
                price=settings.agent_price,
                capability=settings.capability,
                name=settings.agent_name,
                description=settings.agent_description,
                args_schema={},
                has_quote=settings.has_quote,
                price_usdt=settings.agent_price_usdt,
                result_schema=None,
                preview_url=settings.agent_preview_url,
                avatar_url=settings.agent_avatar_url,
                images=settings.agent_images,
            ),
            state_store=self.state_store,
            transfer_sender=self.sender.send,
        )
        self.background_tasks: list[asyncio.Task[Any]] = []
        self.quotes: dict[str, QuoteEntry] = {}
        # Rate Limiting state: ip -> list of timestamps
        self.rate_limits: dict[str, list[float]] = {}

    async def refund_user(
        self, recipient: str, payment_amount: int, original_tx_hash: str, reason: str, rail: str = "TON",
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
                fwd = refund_body(original_tx_hash, reason, self.sidecar_id)
                return await self.sender.send_jetton(
                    own_jetton_wallet=self._agent_jetton_wallet or "",
                    destination=recipient,
                    jetton_amount=refund_amount,
                    forward_payload=fwd,
                )
            except Exception:
                logger.exception("Failed to send USDT refund")
                return None

        refund_amount = max(payment_amount - self.settings.refund_fee_nanoton, 0)
        if refund_amount <= 0:
            logger.warning(
                "Refund skipped because amount is not enough after fee",
                extra={
                    "tx_hash": original_tx_hash,
                    "payment_amount": payment_amount,
                    "refund_fee": self.settings.refund_fee_nanoton,
                },
            )
            return None

        try:
            return await self.sender.send(recipient, refund_amount, refund_body(original_tx_hash, reason, self.sidecar_id))
        except Exception:
            logger.exception("Failed to send refund")
            return None

    async def startup(self) -> None:
        state = self.state_store.load()
        if state.sidecar_id is None:
            state.sidecar_id = str(uuid.uuid4())
            self.state_store.save(state)
        self.sidecar_id = state.sidecar_id

        self.args_schema, self.result_schema = await fetch_describe(
            self.settings.agent_command, DESCRIBE_TIMEOUT, self.sidecar_id,
        )
        if self.args_schema:
            logger.info("Agent args_schema loaded: %s", list(self.args_schema.keys()))
        else:
            logger.info("Agent returned no args_schema; validation disabled")
        if self.result_schema:
            logger.info("Agent result_schema loaded: %s", self.result_schema)

        self._file_store_dir.mkdir(parents=True, exist_ok=True)
        self._images_dir.mkdir(parents=True, exist_ok=True)

        await self.stock.init(self.settings.skus)

        self.heartbeat = HeartbeatManager(
            config=HeartbeatConfig(
                registry_address=self.settings.registry_address,
                endpoint=self.settings.agent_endpoint,
                price=self.settings.agent_price,
                capability=self.settings.capability,
                name=self.settings.agent_name,
                description=self.settings.agent_description,
                args_schema=self.args_schema,
                has_quote=self.settings.has_quote,
                price_usdt=self.settings.agent_price_usdt,
                sidecar_id=self.sidecar_id,
                result_schema=self.result_schema,
                preview_url=self.settings.agent_preview_url,
                avatar_url=self.settings.agent_avatar_url,
                images=self.settings.agent_images,
            ),
            state_store=self.state_store,
            transfer_sender=self.sender.send,
        )

        def _silent_exception_handler(task: asyncio.Task[Any]) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Background task failed unexpectedly")

        try:
            await self.verifier.start()
        except Exception:
            logger.exception("PaymentVerifier failed to start")

        if self.jetton_verifier:
            try:
                await self.jetton_verifier.start()
                self._agent_jetton_wallet = self.jetton_verifier.jetton_wallet_address
            except Exception:
                logger.exception("JettonPaymentVerifier failed to start")

        try:
            await self.heartbeat.send_if_needed(force=False)
        except Exception:
            logger.exception("Initial heartbeat failed")

        for task_coro in [self.heartbeat.loop(self.stop_event), self.cleanup_loop()]:
            task = asyncio.create_task(task_coro)
            task.add_done_callback(_silent_exception_handler)
            self.background_tasks.append(task)

    async def shutdown(self) -> None:
        self.stop_event.set()
        for task in self.background_tasks:
            task.cancel()
        await asyncio.gather(*self.background_tasks, return_exceptions=True)
        await self.sender.close()
        await self.verifier.close()
        if self.jetton_verifier:
            await self.jetton_verifier.close()
        await self.tx_store.close()
        await self.stock.close()

    async def cleanup_loop(self) -> None:
        while not self.stop_event.is_set():
            await self.jobs.cleanup()
            self._cleanup_expired_files()
            self._cleanup_rate_limits()
            try:
                await self.stock.sweep_expired()
            except Exception:
                logger.exception("Stock sweep failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    # ── Dynamic pricing ────────────────────────────────────────────────

    @property
    def _has_dynamic_skus(self) -> bool:
        return any(s.price_ton == 0 and s.price_usd == 0 for s in self.settings.skus)

    async def _fetch_dynamic_prices(self) -> dict[str, dict[str, int]]:
        """Call agent mode=prices and cache result for DYNAMIC_PRICE_CACHE_TTL seconds.

        Returns dict: sku_id -> {"ton": nanoton, "usd": microusd}.
        """
        if self._dynamic_prices_lock is None:
            self._dynamic_prices_lock = asyncio.Lock()
        now = time.time()
        async with self._dynamic_prices_lock:
            if self._dynamic_prices and now - self._dynamic_prices_ts < DYNAMIC_PRICE_CACHE_TTL:
                return self._dynamic_prices
            try:
                result = await api.run_agent_subprocess(
                    command=self.settings.agent_command,
                    payload={"mode": "prices"},
                    timeout_seconds=self.settings.sync_timeout,
                    env={"OWN_SIDECAR_ID": self.sidecar_id},
                )
                prices = result.get("prices")
                if isinstance(prices, dict):
                    self._dynamic_prices = {
                        k: v for k, v in prices.items() if isinstance(v, dict)
                    }
                    self._dynamic_prices_ts = now
                    logger.debug("Dynamic prices refreshed: %s", list(self._dynamic_prices.keys()))
            except Exception:
                logger.exception("Failed to fetch dynamic prices from agent")
        return self._dynamic_prices

    # ── SKU resolution ─────────────────────────────────────────────

    def _resolve_sku(self, sku_field: str | None) -> tuple[AgentSku | None, web.Response | None]:
        """Pick SKU from an explicit id. Falls back to single-SKU agent default.

        Returns (sku, None) on success, (None, error_response) on failure.
        """
        requested = (sku_field or "").strip()
        if requested:
            sku = self._skus_by_id.get(requested)
            if sku is None:
                return None, web.json_response(
                    {"error": "Unknown SKU", "sku": requested}, status=400,
                )
            return sku, None

        if self._single_sku is not None:
            return self._single_sku, None

        return None, web.json_response(
            {"error": "sku is required (multiple SKUs configured)",
             "available_skus": [s.sku_id for s in self.settings.skus]},
            status=400,
        )

    def _sku_price(self, sku: AgentSku, rail: str) -> int | None:
        if rail == "USDT":
            return sku.price_usd
        return sku.price_ton

    # ── File store helpers ──────────────────────────────────────────

    async def handle_image(self, request: web.Request) -> web.StreamResponse:
        name = request.match_info.get("name", "")
        # Defence in depth — aiohttp already strips path segments, but keep explicit check.
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return web.Response(status=404)

        ext = Path(name).suffix.lower()
        mime = IMAGE_EXT_MIME.get(ext)
        if mime is None:
            return web.Response(status=404)

        raw = self._images_dir / name
        if raw.is_symlink():
            return web.Response(status=404)
        path = raw.resolve()
        try:
            path.relative_to(self._images_dir)
        except ValueError:
            return web.Response(status=404)
        if not path.is_file():
            return web.Response(status=404)

        return web.FileResponse(
            path,
            headers={
                "Content-Type": mime,
                "Cache-Control": "public, max-age=86400",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def _process_file_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return process_file_result(result, self._file_store, self._file_store_dir, self._file_store_ttl)

    def _safe_extract_result(self, record_result: Any) -> tuple[dict[str, Any] | Any, str | None]:
        return safe_extract_result(record_result, self._file_store, self._file_store_dir, self._file_store_ttl)

    def _cleanup_file(self, file_id: str) -> None:
        entry = self._file_store.pop(file_id, None)
        if entry:
            try:
                Path(entry["path"]).unlink(missing_ok=True)
            except Exception:
                logger.warning("Failed to delete file %s", entry["path"])

    def _cleanup_expired_files(self) -> None:
        now = time.time()
        expired = [fid for fid, entry in self._file_store.items() if entry["expires_at"] <= now]
        for fid in expired:
            self._cleanup_file(fid)

    def _cleanup_uploaded_files(self, uploaded_files: dict[str, Path]) -> None:
        """Remove upload directories created by _parse_multipart_invoke.

        Called on every handle_invoke error path that runs before the agent
        subprocess takes ownership of the files — without this, multipart
        uploads that hit a validation/verification error would accumulate on
        disk forever.
        """
        for file_path in uploaded_files.values():
            try:
                shutil.rmtree(file_path.parent, ignore_errors=True)
            except Exception:
                logger.warning("Failed to cleanup uploaded file dir %s", file_path.parent)

    def _cleanup_rate_limits(self) -> None:
        """Drop rate-limit entries whose every timestamp is stale.

        Without this sweep, self.rate_limits grows unboundedly as new IPs
        connect — the middleware only filters a key's history when that same
        IP makes another request, so rotating source IPs is a slow-drip
        memory leak. Called from cleanup_loop on a timer.
        """
        cutoff = time.time() - self.settings.rate_limit_window
        stale = [
            ip
            for ip, history in self.rate_limits.items()
            if not history or all(ts <= cutoff for ts in history)
        ]
        for ip in stale:
            self.rate_limits.pop(ip, None)

    @staticmethod
    def _is_out_of_stock_result(raw: dict[str, Any]) -> bool:
        return is_out_of_stock_result(raw)

    @staticmethod
    def _validate_result_structure(raw: dict[str, Any]) -> None:
        validate_result_structure(raw)

    def _create_runner(
        self,
        agent_payload: dict[str, Any],
        sender: str,
        amount: int,
        tx_hash: str,
        uploaded_files: dict[str, Path] | None = None,
        rail: str = "TON",
        reservation_key: str | None = None,
    ):
        async def runner() -> dict[str, Any]:
            try:
                raw = await api.run_agent_subprocess(
                    command=self.settings.agent_command,
                    payload=agent_payload,
                    timeout_seconds=self.settings.final_timeout,
                    env={
                        "OWN_SIDECAR_ID": self.sidecar_id,
                        "CALLER_ADDRESS": sender,
                        "CALLER_TX_HASH": tx_hash,
                        "PAYMENT_RAIL": rail,
                    },
                )

                if is_out_of_stock_result(raw):
                    reason = str(raw.get("reason") or "agent reported out of stock")
                    refund_tx = await self.refund_user(
                        recipient=sender,
                        payment_amount=amount,
                        original_tx_hash=tx_hash,
                        reason="out_of_stock",
                        rail=rail,
                    )
                    if reservation_key:
                        try:
                            await self.stock.agent_out_of_stock(reservation_key)
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
                        await self.stock.commit_sold(reservation_key, tx_hash)
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
                    await self.refund_user(
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
                        await self.stock.release(reservation_key)
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

    async def _parse_multipart_invoke(
        self, request: web.Request
    ) -> tuple[str, str, str, str | None, str, str | None, dict[str, Any], dict[str, Path]]:
        """Parse multipart/form-data invoke request.

        Returns: (tx_hash, nonce, capability, quote_id, rail, sku, body_dict, uploaded_files)
        """
        reader = await request.multipart()
        tx_hash = nonce = capability = ""
        quote_id: str | None = None
        rail = "TON"
        sku: str | None = None
        body: dict[str, Any] = {}
        uploaded_files: dict[str, Path] = {}

        async for part in reader:
            name = part.name
            if name == "tx":
                tx_hash = (await part.text()).strip()
            elif name == "nonce":
                nonce = (await part.text()).strip()
            elif name == "capability":
                capability = (await part.text()).strip()
            elif name == "quote_id":
                quote_id = (await part.text()).strip() or None
            elif name == "rail":
                rail = (await part.text()).strip().upper() or "TON"
            elif name == "sku":
                sku = (await part.text()).strip() or None
            elif name == "body_json":
                body = json.loads(await part.text())
            elif name and name.startswith("file:"):
                field_name = name[5:]  # strip "file:" prefix
                file_data = await part.read(decode=False)
                original_name = Path(part.filename or "").name or f"{uuid.uuid4().hex}.bin"
                upload_dir = self._file_store_dir / "uploads" / uuid.uuid4().hex
                upload_dir.mkdir(parents=True, exist_ok=True)
                file_path = upload_dir / original_name
                file_path.write_bytes(file_data)
                uploaded_files[field_name] = file_path

        return tx_hash, nonce, capability, quote_id, rail, sku, body, uploaded_files

    def _cleanup_expired_quotes(self) -> None:
        now = time.time()
        expired = [qid for qid, entry in self.quotes.items() if entry.expires_at <= now]
        for qid in expired:
            del self.quotes[qid]

    async def handle_quote(self, request: web.Request) -> web.Response:
        if not self.settings.has_quote:
            return web.json_response({"error": "This agent does not support quotes"}, status=404)

        try:
            if request.content_type and "multipart/form-data" in request.content_type:
                _, _, capability, _, _, sku_field, body, _ = await self._parse_multipart_invoke(request)
            else:
                data = await request.json()
                capability = str(data.get("capability", "")).strip()
                sku_field = str(data.get("sku", "")).strip() or None
                body = data.get("body", {})
        except Exception:
            return web.json_response({"error": "Invalid request"}, status=400)

        if not capability:
            return web.json_response({"error": "capability is required"}, status=400)

        if capability != self.settings.capability:
            return web.json_response({"error": "Unsupported capability"}, status=400)

        sku, sku_err = self._resolve_sku(sku_field)
        if sku_err is not None:
            return sku_err
        assert sku is not None

        missing = validate_body({"body": body}, self.args_schema)
        if missing:
            return web.json_response({"error": "Missing required fields", "missing": missing}, status=400)

        # Pre-check stock before calling agent — cheap rejection path.
        view = await self.stock.get_view(sku.sku_id)
        if view.stock_left is not None and view.stock_left <= 0:
            return web.json_response(
                {"error": "out_of_stock", "sku": sku.sku_id}, status=409,
            )

        quote_payload = {
            "mode": "quote",
            "capability": capability,
            "sku": sku.sku_id,
            "body": body,
        }

        try:
            agent_result = await api.run_agent_subprocess(
                command=self.settings.agent_command,
                payload=quote_payload,
                timeout_seconds=self.settings.sync_timeout,
                env={"OWN_SIDECAR_ID": self.sidecar_id},
            )
        except Exception:
            logger.exception("Quote subprocess failed")
            return web.json_response({"error": "Quote generation failed"}, status=500)

        price = agent_result.get("price")
        plan = agent_result.get("plan", "")
        note = agent_result.get("note")
        ttl = int(agent_result.get("ttl", DEFAULT_QUOTE_TTL))

        if not isinstance(price, int) or price <= 0:
            return web.json_response({"error": "Agent returned invalid price"}, status=500)

        price_usdt = agent_result.get("price_usdt")
        if price_usdt is not None and (not isinstance(price_usdt, int) or price_usdt <= 0):
            price_usdt = None

        self._cleanup_expired_quotes()

        quote_id = str(uuid.uuid4())
        expires_at = time.time() + ttl

        # Reserve stock for this quote. Use payment_timeout as TTL — user has
        # that long to pay before the reservation is swept.
        reserve_ttl = max(ttl, self.settings.payment_timeout)
        try:
            ok = await self.stock.reserve(sku.sku_id, quote_id, reserve_ttl)
        except Exception:
            logger.exception("stock.reserve failed during quote")
            return web.json_response({"error": "Internal stock error"}, status=500)
        if not ok:
            return web.json_response(
                {"error": "out_of_stock", "sku": sku.sku_id}, status=409,
            )

        self.quotes[quote_id] = QuoteEntry(
            price=price, expires_at=expires_at, sku_id=sku.sku_id, price_usdt=price_usdt,
        )

        resp: dict[str, Any] = {
            "quote_id": quote_id,
            "price": price,
            "plan": plan,
            "sku": sku.sku_id,
            "expires_at": int(expires_at),
        }
        if price_usdt:
            resp["price_usdt"] = price_usdt
        if note:
            resp["note"] = note

        return web.json_response(resp)

    async def handle_invoke(self, request: web.Request) -> web.Response:
        uploaded_files: dict[str, Path] = {}
        # Flip to True once the runner takes ownership of uploaded_files —
        # until then, any early return must clean them up so validation /
        # verification failures don't leak multipart uploads on disk.
        ownership_transferred = False
        # Reservation keys we created in this request and must clean up on
        # early failure paths (unless handed off to the runner).
        created_reservation_keys: list[str] = []

        try:
            try:
                if request.content_type and "multipart/form-data" in request.content_type:
                    tx_hash, nonce, capability, quote_id, rail, sku_field, body, uploaded_files = \
                        await self._parse_multipart_invoke(request)
                    payload = {"body": body}
                else:
                    data = await request.json()
                    tx_hash = str(data.get("tx", "")).strip()
                    nonce = str(data.get("nonce", "")).strip()
                    capability = str(data.get("capability", "")).strip()
                    quote_id = str(data.get("quote_id", "")).strip() or None
                    rail = str(data.get("rail", "")).strip().upper() or "TON"
                    sku_field = str(data.get("sku", "")).strip() or None
                    body = data.get("body", {})
                    payload = data
            except Exception:
                return web.json_response({"error": "Invalid request"}, status=400)

            if not capability:
                return web.json_response({"error": "capability is required"}, status=400)

            if capability != self.settings.capability:
                return web.json_response({"error": "Unsupported capability"}, status=400)

            # Resolve SKU. Quote-bound calls derive SKU from the quote entry
            # instead (user doesn't need to repeat it). Direct calls must
            # either specify sku or rely on single-SKU default.
            sku: AgentSku | None = None
            quote_entry = self.quotes.get(quote_id) if quote_id else None
            if quote_entry is not None:
                sku = self._skus_by_id.get(quote_entry.sku_id)
                if sku is None:
                    return web.json_response({"error": "Quote references unknown SKU"}, status=500)
            else:
                sku, sku_err = self._resolve_sku(sku_field)
                if sku_err is not None:
                    return sku_err
            assert sku is not None

            # Reject requested rail if SKU doesn't support it.
            if rail == "TON" and sku.price_ton is None:
                return web.json_response({"error": "unsupported_rail_for_sku", "sku": sku.sku_id, "rail": rail}, status=400)
            if rail == "USDT" and sku.price_usd is None:
                return web.json_response({"error": "unsupported_rail_for_sku", "sku": sku.sku_id, "rail": rail}, status=400)

            # Determine payment amounts (quoted or static per-SKU).
            # For dynamic SKUs (price==0), resolve current price from agent cache.
            eff_ton = sku.price_ton  # may be 0 (dynamic sentinel when both rails are 0)
            eff_usd = sku.price_usd
            if eff_ton == 0 and eff_usd == 0:
                try:
                    dp = (await self._fetch_dynamic_prices()).get(sku.sku_id, {})
                    eff_ton = dp.get("ton") or 0
                    eff_usd = dp.get("usd") or 0
                except Exception:
                    logger.warning("Dynamic price fetch failed for SKU %s", sku.sku_id)

            min_amount = eff_ton or 0
            min_amount_usdt = eff_usd or 0
            if quote_id:
                self._cleanup_expired_quotes()
                quote_entry = self.quotes.get(quote_id)
                if quote_entry is None:
                    return web.json_response({"error": "Quote not found or expired"}, status=400)
                if quote_entry.locked and tx_hash:
                    return web.json_response({"error": "Quote is currently locked by another request"}, status=409)
                min_amount = quote_entry.price
                if quote_entry.price_usdt:
                    min_amount_usdt = quote_entry.price_usdt

            # HTTP 402 Payment Required flow — return price before validating body,
            # so preflight pings always get 402 with real price (not 400 for missing fields)
            if not tx_hash:
                # Preflight stock gate: if this SKU is tracked and sold out,
                # don't bother issuing a payment option the user can't redeem.
                view = await self.stock.get_view(sku.sku_id)
                if view.stock_left is not None and view.stock_left <= 0:
                    return web.json_response(
                        {"error": "out_of_stock", "sku": sku.sku_id}, status=409,
                    )

                if not nonce or not nonce.endswith(f":{self.sidecar_id}"):
                    nonce = f"{uuid.uuid4().hex[:16]}:{self.sidecar_id}"

                payment_options: list[dict[str, Any]] = []
                if eff_ton:
                    payment_options.append({
                        "rail": "TON",
                        "address": self.settings.agent_wallet,
                        "amount": str(min_amount),
                        "memo": nonce,
                        "sku": sku.sku_id,
                    })
                if eff_usd and min_amount_usdt:
                    usdt_master = USDT_MASTER_TESTNET if self.settings.testnet else USDT_MASTER_MAINNET
                    payment_options.append({
                        "rail": "USDT",
                        "address": self.settings.agent_wallet,
                        "amount": str(min_amount_usdt),
                        "memo": nonce,
                        "sku": sku.sku_id,
                        "token": {
                            "symbol": "USDT",
                            "master": usdt_master,
                            "decimals": 6,
                        },
                    })

                resp_body: dict[str, Any] = {
                    "error": "Payment required",
                    "payment_request": payment_options[0] if payment_options else {},
                    "payment_options": payment_options,
                }

                headers: dict[str, str] = {}
                if eff_ton:
                    headers["x-ton-pay-address"] = self.settings.agent_wallet
                    headers["x-ton-pay-amount"] = str(min_amount)
                    headers["x-ton-pay-nonce"] = nonce

                return web.json_response(resp_body, status=402, headers=headers)

            # Validate body only on execution (with tx) — preflight already returned above
            missing = validate_body(payload, self.args_schema, has_tx=True, uploaded_files=uploaded_files)
            if missing:
                return web.json_response({"error": "Missing required fields", "missing": missing}, status=400)

            if not nonce:
                return web.json_response({"error": "nonce is required with tx"}, status=400)

            if quote_id and quote_entry:
                quote_entry.locked = True

            nonce_meta = parse_nonce(nonce)
            if not nonce_meta.value.endswith(f":{self.sidecar_id}"):
                if quote_id and quote_id in self.quotes:
                    self.quotes[quote_id].locked = False
                return web.json_response({"error": "Nonce sidecar_id mismatch"}, status=402)

            if await self.tx_store.is_processed(tx_hash):
                if quote_id and quote_id in self.quotes:
                    self.quotes[quote_id].locked = False
                return web.json_response({"error": "Transaction already used"}, status=409)

            try:
                if rail == "USDT":
                    if not self.jetton_verifier:
                        if quote_id and quote_id in self.quotes:
                            self.quotes[quote_id].locked = False
                        logger.critical(
                            "USDT payment received but jetton_verifier is not configured — "
                            "tx=%s nonce=%s — payment requires manual refund",
                            tx_hash, nonce,
                        )
                        return web.json_response({"error": "USDT payments not configured"}, status=400)
                    if min_amount_usdt == 0:
                        if quote_id and quote_id in self.quotes:
                            self.quotes[quote_id].locked = False
                        return web.json_response(
                            {"error": "USDT price unavailable for this SKU", "sku": sku.sku_id},
                            status=503,
                        )
                    verified_payment = await self.jetton_verifier.verify(
                        tx_hash=tx_hash, raw_nonce=nonce, min_amount=min_amount_usdt,
                    )
                else:
                    verified_payment = await self.verifier.verify(
                        tx_hash=tx_hash, raw_nonce=nonce, min_amount=min_amount,
                    )
            except PaymentVerificationError as exc:
                if quote_id and quote_id in self.quotes:
                    self.quotes[quote_id].locked = False
                return web.json_response({"error": str(exc)}, status=402)
            except Exception:
                logger.exception("Payment verification error")
                if quote_id and quote_id in self.quotes:
                    self.quotes[quote_id].locked = False
                return web.json_response({"error": "Payment verification failed"}, status=502)

            # Dedup against the real on-chain hash (verify() now returns it, not the user-supplied one)
            if await self.tx_store.is_processed(verified_payment.tx_hash):
                if quote_id and quote_id in self.quotes:
                    self.quotes[quote_id].locked = False
                return web.json_response({"error": "Transaction already used"}, status=409)

            try:
                await self.tx_store.mark_processed(verified_payment.tx_hash)
            except Exception:
                if quote_id and quote_id in self.quotes:
                    self.quotes[quote_id].locked = False
                return web.json_response({"error": "Failed to persist transaction"}, status=500)

            # Resolve stock reservation. With a quote, reservation is already
            # in place under quote_id. Without a quote, claim one now.
            reservation_key: str | None = None
            if quote_id:
                reservation_key = quote_id
            elif self.stock.has_tracked_stock(sku.sku_id):
                reservation_key = verified_payment.tx_hash
                try:
                    reserved = await self.stock.reserve(
                        sku.sku_id, reservation_key, self.settings.final_timeout,
                    )
                except Exception:
                    logger.exception("stock.reserve (post-payment) failed")
                    reserved = False
                if not reserved:
                    # Race lost between preflight and payment. Refund the user.
                    try:
                        await self.refund_user(
                            recipient=verified_payment.sender,
                            payment_amount=verified_payment.amount,
                            original_tx_hash=verified_payment.tx_hash,
                            reason="out_of_stock",
                            rail=rail,
                        )
                    except Exception:
                        logger.exception("Refund after out_of_stock race failed")
                    return web.json_response(
                        {"error": "out_of_stock", "sku": sku.sku_id, "refunded": True},
                        status=409,
                    )
                created_reservation_keys.append(reservation_key)

            # Consume quote so it can't be reused
            if quote_id and quote_id in self.quotes:
                del self.quotes[quote_id]

            # Bind reservation to the job for lifecycle tracking.
            agent_body = dict(body)
            agent_body["sku"] = sku.sku_id
            for field_name, file_path in uploaded_files.items():
                agent_body[f"{field_name}_path"] = str(file_path)
                if f"{field_name}_name" not in agent_body:
                    agent_body[f"{field_name}_name"] = file_path.name

            agent_payload = {
                "capability": capability,
                "sku": sku.sku_id,
                "body": agent_body,
            }

            # From here on, the runner owns uploaded_files and the reservation:
            # its finally/except blocks clean them up after the subprocess
            # finishes. Stop the outer finally from double-cleanup.
            ownership_transferred = True
            job_id = await self.jobs.submit(
                self._create_runner(
                    agent_payload, verified_payment.sender, verified_payment.amount,
                    tx_hash, uploaded_files, rail, reservation_key,
                )
            )
            if reservation_key:
                try:
                    await self.stock.attach_job(
                        reservation_key, job_id, extend_ttl_seconds=self.settings.final_timeout,
                    )
                except Exception:
                    logger.exception("attach_job failed")
        finally:
            if not ownership_transferred:
                if uploaded_files:
                    self._cleanup_uploaded_files(uploaded_files)
                for key in created_reservation_keys:
                    try:
                        await self.stock.release(key)
                    except Exception:
                        logger.exception("Failed to release reservation on early exit")

        record = await self.jobs.wait_for_completion(job_id, timeout_seconds=self.settings.sync_timeout)

        if record is None:
            return web.json_response({"job_id": job_id, "status": "pending"})

        if record.status == "done":
            return self._render_done_response(job_id, record.result)

        if record.status == "error":
            return web.json_response({"job_id": job_id, "status": "error", "error": record.error}, status=500)

        return web.json_response({"job_id": job_id, "status": "pending"})

    def _render_done_response(self, job_id: str, record_result: Any) -> web.Response:
        """Translate a done job's payload into HTTP response, recognizing out_of_stock."""
        # Recognize runner-produced refund record without running it through
        # _process_file_result (it's already a plain dict, not an agent result).
        if isinstance(record_result, dict):
            inner = record_result.get("result") if isinstance(record_result.get("result"), dict) else None
            if isinstance(inner, dict) and inner.get("status") == "refunded_out_of_stock":
                return web.json_response({
                    "job_id": job_id,
                    "status": "refunded_out_of_stock",
                    "reason": inner.get("reason"),
                    "refund_tx": inner.get("refund_tx"),
                })

        final_res, extract_err = self._safe_extract_result(record_result)
        if extract_err:
            return web.json_response({"job_id": job_id, "status": "error", "error": extract_err}, status=500)
        return web.json_response({"job_id": job_id, "status": "done", "result": final_res})

    async def handle_result(self, request: web.Request) -> web.Response:
        job_id = request.match_info["job_id"]
        record = await self.jobs.get(job_id)
        if record is None:
            return web.json_response({"error": "Job not found"}, status=404)

        if record.status == "done":
            return self._render_done_response(job_id, record.result)

        response: dict[str, Any] = {"status": record.status}
        if record.error is not None:
            response["error"] = record.error
        return web.json_response(response)

    async def handle_download(self, request: web.Request) -> web.Response:
        file_id = request.match_info["file_id"]
        entry = self._file_store.get(file_id)

        if entry is None:
            return web.json_response({"error": "File not found"}, status=404)

        if time.time() > entry["expires_at"]:
            self._cleanup_file(file_id)
            return web.json_response({"error": "File expired"}, status=410)

        file_path = Path(entry["path"])
        if not file_path.exists():
            return web.json_response({"error": "File not found on disk"}, status=404)

        return web.Response(
            body=file_path.read_bytes(),
            content_type=entry["mime_type"],
            headers={
                "Content-Disposition": f'inline; filename="{entry["file_name"]}"',
            },
        )

    async def handle_info(self, _: web.Request) -> web.Response:
        rails = list(self.settings.payment_rails)

        info: dict[str, Any] = {
            "name": self.settings.agent_name,
            "description": self.settings.agent_description,
            "capabilities": [self.settings.capability],
            "price": self.settings.agent_price,
            "args_schema": self.args_schema,
            "result_schema": self.result_schema,
            "sidecar_id": self.sidecar_id,
            "endpoint": self.settings.agent_endpoint,
            "payment_rails": rails,
        }
        if self.settings.has_quote:
            info["has_quote"] = True
        if self.settings.agent_price_usdt:
            info["price_usdt"] = self.settings.agent_price_usdt

        # Always emit skus[] so clients can drive per-SKU UI. Legacy single-SKU
        # agents still see price/price_usdt top-level (populated from that SKU).
        try:
            views = await self.stock.list_views()
        except Exception:
            logger.exception("stock.list_views failed")
            views = []

        # Fetch dynamic prices if any SKU uses ton=0 and usd=0 as the dynamic sentinel.
        dynamic_prices: dict[str, dict[str, int]] = {}
        if self._has_dynamic_skus:
            try:
                dynamic_prices = await self._fetch_dynamic_prices()
            except Exception:
                logger.exception("Dynamic price fetch failed for /info")

        skus_payload: list[dict[str, Any]] = []
        for v in views:
            entry: dict[str, Any] = {
                "id": v.sku_id,
                "title": v.title,
            }
            sku_obj = self._skus_by_id.get(v.sku_id)
            dp = dynamic_prices.get(v.sku_id, {})
            is_dynamic = sku_obj is not None and sku_obj.price_ton == 0 and sku_obj.price_usd == 0

            price_ton = dp.get("ton", None if is_dynamic else v.price_ton)
            price_usd = dp.get("usd", None if is_dynamic else v.price_usd)

            if price_ton is not None:
                entry["price_ton"] = price_ton
            if price_usd is not None:
                entry["price_usd"] = price_usd
            if v.stock_left is not None:
                entry["stock_left"] = v.stock_left
            if v.total is not None:
                entry["total"] = v.total
                entry["sold"] = v.sold
            skus_payload.append(entry)
        if skus_payload:
            info["skus"] = skus_payload

        from heartbeat import _valid_image_url
        if self.settings.agent_preview_url and _valid_image_url(self.settings.agent_preview_url):
            info["preview_url"] = self.settings.agent_preview_url
        if self.settings.agent_avatar_url and _valid_image_url(self.settings.agent_avatar_url):
            info["avatar_url"] = self.settings.agent_avatar_url
        if self.settings.agent_images:
            from heartbeat import MAX_IMAGES
            images = [img for img in self.settings.agent_images if _valid_image_url(img)]
            if images:
                info["images"] = images[:MAX_IMAGES]
        return web.json_response(info)

    def build_web_app(self) -> web.Application:
        @web.middleware
        async def cors_middleware(request: web.Request, handler):
            cors_headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400",
            }
            if request.method == "OPTIONS":
                return web.Response(status=204, headers=cors_headers)
            response = await handler(request)
            response.headers.update(cors_headers)
            return response

        @web.middleware
        async def rate_limit_middleware(request: web.Request, handler):
            if request.method == "OPTIONS" or request.path == "/info" or request.path.startswith("/download/"):
                return await handler(request)

            remote = request.remote or ""
            if remote and self.settings.trusted_proxy_ips and remote in self.settings.trusted_proxy_ips:
                ip = (request.headers.get("X-Forwarded-For") or remote).split(",")[0].strip()
            else:
                ip = remote or "unknown"

            now = time.time()
            cutoff = now - self.settings.rate_limit_window

            # Fast cleanup and check
            history = self.rate_limits.get(ip, [])
            history = [ts for ts in history if ts > cutoff]

            if len(history) >= self.settings.rate_limit_requests:
                return web.json_response({
                    "error": "Too many requests",
                    "retry_after": int(history[0] - cutoff)
                }, status=429)

            history.append(now)
            self.rate_limits[ip] = history

            return await handler(request)

        max_upload_mb = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "150"))
        app = web.Application(
            client_max_size=1024 * 1024 * max_upload_mb,
            middlewares=[cors_middleware, rate_limit_middleware],
        )
        app.add_routes(
            [
                web.post("/invoke", self.handle_invoke),
                web.post("/quote", self.handle_quote),
                web.get("/result/{job_id}", self.handle_result),
                web.get("/download/{file_id}", self.handle_download),
                web.get("/images/{name}", self.handle_image),
                web.get("/info", self.handle_info),
            ]
        )
        app.on_startup.append(lambda _: self.startup())
        app.on_shutdown.append(lambda _: self.shutdown())
        return app
