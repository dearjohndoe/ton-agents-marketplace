from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any
from aiohttp import web

from heartbeat import HeartbeatConfig, HeartbeatManager
from jobs import JobStore
from storage import StateStore
from transfer import TransferSender
from payments import PaymentVerificationError, PaymentVerifier, JettonPaymentVerifier, ProcessedTxStore, parse_nonce
from jetton import USDT_MASTER_MAINNET, USDT_MASTER_TESTNET
from settings import Settings, AgentSku, DEFAULT_SKU_ID  # noqa: F401 — re-exported via api package
from stock import StockStore

import api  # late binding for monkeypatched run_agent_subprocess
from api.constants import (
    DESCRIBE_TIMEOUT,
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
from api.domain.quoting import (
    DynamicPriceCache,
    QuoteEntry,
    cleanup_expired_quotes,
    fetch_dynamic_prices,
    has_dynamic_skus,
)
from api.domain.pricing import resolve_sku, sku_price
from api.domain.refund import refund_user as _refund_user
from api.domain.invocation import create_runner
from api.infra.cleanup import cleanup_loop as _cleanup_loop
from api.infra.files import (
    cleanup_expired_files,
    cleanup_file,
    cleanup_uploaded_files,
)
from api.infra.rate_limit import cleanup_rate_limits
from api.http.middleware import make_cors_middleware, make_rate_limit_middleware
from api.http.multipart import parse_multipart_invoke
from api.http.responses import render_done_response
from api.http.routes import register_routes
from api.http.handlers.image import handle_image as _handle_image
from api.http.handlers.info import handle_info as _handle_info
from api.http.handlers.invoke import handle_invoke as _handle_invoke
from api.http.handlers.quote import handle_quote as _handle_quote
from api.http.handlers.result import handle_download as _handle_download
from api.http.handlers.result import handle_result as _handle_result

logger = logging.getLogger("sidecar")


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
        self._dynamic_prices_cache = DynamicPriceCache()
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
        return await _refund_user(
            sender=self.sender,
            agent_jetton_wallet=self._agent_jetton_wallet,
            sidecar_id=self.sidecar_id,
            refund_fee_nanoton=self.settings.refund_fee_nanoton,
            recipient=recipient,
            payment_amount=payment_amount,
            original_tx_hash=original_tx_hash,
            reason=reason,
            rail=rail,
        )

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
        await _cleanup_loop(self)

    # ── Dynamic pricing ────────────────────────────────────────────────

    @property
    def _has_dynamic_skus(self) -> bool:
        return has_dynamic_skus(self.settings.skus)

    async def _fetch_dynamic_prices(self) -> dict[str, dict[str, int]]:
        return await fetch_dynamic_prices(
            self._dynamic_prices_cache,
            agent_command=self.settings.agent_command,
            sync_timeout=self.settings.sync_timeout,
            sidecar_id=self.sidecar_id,
        )

    # ── SKU resolution ─────────────────────────────────────────────

    def _resolve_sku(self, sku_field: str | None) -> tuple[AgentSku | None, web.Response | None]:
        return resolve_sku(sku_field, self._skus_by_id, self._single_sku, self.settings.skus)

    def _sku_price(self, sku: AgentSku, rail: str) -> int | None:
        return sku_price(sku, rail)

    # ── File store helpers ──────────────────────────────────────────

    async def handle_image(self, request: web.Request) -> web.StreamResponse:
        return await _handle_image(request, self._images_dir)

    def _process_file_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return process_file_result(result, self._file_store, self._file_store_dir, self._file_store_ttl)

    def _safe_extract_result(self, record_result: Any) -> tuple[dict[str, Any] | Any, str | None]:
        return safe_extract_result(record_result, self._file_store, self._file_store_dir, self._file_store_ttl)

    def _cleanup_file(self, file_id: str) -> None:
        cleanup_file(self._file_store, file_id)

    def _cleanup_expired_files(self) -> None:
        cleanup_expired_files(self._file_store)

    def _cleanup_uploaded_files(self, uploaded_files: dict[str, Path]) -> None:
        cleanup_uploaded_files(uploaded_files)

    def _cleanup_rate_limits(self) -> None:
        cleanup_rate_limits(self.rate_limits, self.settings.rate_limit_window)

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
        return create_runner(
            refund_user=self.refund_user,
            stock=self.stock,
            agent_command=self.settings.agent_command,
            final_timeout=self.settings.final_timeout,
            sidecar_id=self.sidecar_id,
            agent_payload=agent_payload,
            sender=sender,
            amount=amount,
            tx_hash=tx_hash,
            uploaded_files=uploaded_files,
            rail=rail,
            reservation_key=reservation_key,
        )

    async def _parse_multipart_invoke(
        self, request: web.Request
    ) -> tuple[str, str, str, str | None, str, str | None, dict[str, Any], dict[str, Path]]:
        return await parse_multipart_invoke(request, self._file_store_dir)

    def _cleanup_expired_quotes(self) -> None:
        cleanup_expired_quotes(self.quotes)

    async def handle_quote(self, request: web.Request) -> web.Response:
        return await _handle_quote(request, self)

    async def handle_invoke(self, request: web.Request) -> web.Response:
        return await _handle_invoke(request, self)

    def _render_done_response(self, job_id: str, record_result: Any) -> web.Response:
        return render_done_response(
            job_id, record_result, self._file_store, self._file_store_dir, self._file_store_ttl,
        )

    async def handle_result(self, request: web.Request) -> web.Response:
        return await _handle_result(request, self)

    async def handle_download(self, request: web.Request) -> web.Response:
        return await _handle_download(request, self._file_store)

    async def handle_info(self, request: web.Request) -> web.Response:
        return await _handle_info(request, self)

    def build_web_app(self) -> web.Application:
        max_upload_mb = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "150"))
        app = web.Application(
            client_max_size=1024 * 1024 * max_upload_mb,
            middlewares=[
                make_cors_middleware(),
                make_rate_limit_middleware(self.settings, self.rate_limits),
            ],
        )
        register_routes(app, self)
        app.on_startup.append(lambda _: self.startup())
        app.on_shutdown.append(lambda _: self.shutdown())
        return app
