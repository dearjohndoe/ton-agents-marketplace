from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
from aiohttp import web

from heartbeat import HeartbeatConfig, HeartbeatManager
from jobs import JobStore, run_agent_subprocess
from storage import StateStore, TonStorageClient, parse_storage_expiry, should_extend_storage
from verify import PaymentVerificationError, PaymentVerifier, ProcessedTxStore
from settings import ArgSchema, Settings

logger = logging.getLogger("sidecar")

def generate_docs(settings: Settings) -> dict[str, Any]:
    input_schema: dict[str, Any] = {}
    for item in settings.args_schema:
        input_schema[item.name] = {
            "type": item.type,
            "description": item.description,
            "required": item.required,
        }

    return {
        "name": settings.agent_name,
        "description": settings.agent_description,
        "capabilities": {
            settings.capability: {
                "input": input_schema,
            }
        },
    }


def write_docs_file(docs_path: str, docs_payload: dict[str, Any]) -> None:
    Path(docs_path).write_text(json.dumps(docs_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_body(payload: dict[str, Any], args_schema: list[ArgSchema]) -> list[str]:
    body = payload.get("body")
    if not isinstance(body, dict):
        return ["body"]

    missing: list[str] = []
    for item in args_schema:
        if item.required and item.name not in body:
            missing.append(item.name)
    return missing


async def send_transfer_stub(destination: str, amount: int, comment: str) -> str:
    if os.getenv("SIDECAR_DRY_RUN", "true").lower() in {"1", "true", "yes", "on"}:
        logger.info(
            "SIDECAR_DRY_RUN enabled, transfer skipped",
            extra={"destination": destination, "amount": amount, "comment": comment},
        )
        return "dry_run_tx"

    raise RuntimeError(
        "Real TON transfer sender is not configured. Set SIDECAR_DRY_RUN=true for MVP mode."
    )


class SidecarApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jobs = JobStore(ttl_seconds=settings.jobs_ttl)
        self.tx_store = ProcessedTxStore(settings.tx_db_path)
        self.verifier = PaymentVerifier(
            toncenter_base_url=settings.toncenter_base_url,
            toncenter_api_key=settings.toncenter_api_key,
            agent_wallet=settings.agent_wallet,
            min_amount=settings.agent_price,
            payment_timeout_seconds=settings.payment_timeout,
            enforce_comment_nonce=settings.enforce_comment_nonce,
        )
        self.state_store = StateStore(settings.state_path)
        self.storage = TonStorageClient(settings.ton_storage_base_url, settings.ton_storage_session)
        self.stop_event = asyncio.Event()
        self.heartbeat = HeartbeatManager(
            config=HeartbeatConfig(
                registry_address=settings.registry_address,
                endpoint=settings.agent_endpoint,
                price=settings.agent_price,
                capability=settings.capability,
                docs_bag_id=self.state_store.load().bag_id,
            ),
            state_store=self.state_store,
            transfer_sender=send_transfer_stub,
        )
        self.background_tasks: list[asyncio.Task[Any]] = []

    async def refund_user(self, recipient: str, payment_amount: int, original_tx_hash: str, reason: str) -> None:
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
            return

        comment = f"refund_tx:{original_tx_hash} reason:{reason[:80]}"
        try:
            await send_transfer_stub(recipient, refund_amount, comment)
        except Exception:
            logger.exception("Failed to send refund")

    async def startup(self) -> None:
        docs_payload = generate_docs(self.settings)
        write_docs_file(self.settings.docs_path, docs_payload)

        state = self.state_store.load()
        if not state.bag_id and self.settings.ton_storage_session:
            bag_id = await self.storage.upload_docs(self.settings.docs_path, description=self.settings.agent_name)
            state.bag_id = bag_id
            self.state_store.save(state)

        self.heartbeat = HeartbeatManager(
            config=HeartbeatConfig(
                registry_address=self.settings.registry_address,
                endpoint=self.settings.agent_endpoint,
                price=self.settings.agent_price,
                capability=self.settings.capability,
                docs_bag_id=state.bag_id,
            ),
            state_store=self.state_store,
            transfer_sender=send_transfer_stub,
        )


        def _silent_exception_handler(task: asyncio.Task[Any]) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Background task failed unexpectedly")

        for task_coro in [self.heartbeat.loop(self.stop_event), self.cleanup_loop(), self.storage_loop()]:
            task = asyncio.create_task(task_coro)
            task.add_done_callback(_silent_exception_handler)
            self.background_tasks.append(task)


        try:
            await self.heartbeat.send_if_needed(force=False)
        except Exception:
            logger.exception("Initial heartbeat failed")

    async def shutdown(self) -> None:
        self.stop_event.set()
        for task in self.background_tasks:
            task.cancel()
        await asyncio.gather(*self.background_tasks, return_exceptions=True)
        await self.storage.close()
        await self.verifier.close()
        await self.tx_store.close()

    async def cleanup_loop(self) -> None:
        while not self.stop_event.is_set():
            await self.jobs.cleanup()
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    async def storage_loop(self) -> None:
        if not self.settings.ton_storage_session:
            return

        while not self.stop_event.is_set():
            try:
                state = self.state_store.load()
                if state.bag_id:
                    details = await self.storage.get_details(state.bag_id)
                    expires_at = parse_storage_expiry(details)
                    if expires_at:
                        state.storage_expires = expires_at
                        self.state_store.save(state)
                        if should_extend_storage(expires_at, threshold_days=self.settings.storage_extend_threshold_days):
                            logger.info(
                                "Storage for bag %s expires at %s, extending...", state.bag_id, expires_at
                            )
                            await self.storage.extend_storage(state.bag_id)
                            logger.info("Storage extended successfully")
            except Exception:
                logger.exception("Storage extension failed")

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=3600)
            except asyncio.TimeoutError:
                pass



    def _create_runner(self, agent_payload: dict[str, Any], sender: str, amount: int, tx_hash: str):
        async def runner() -> dict[str, Any]:
            try:
                return await run_agent_subprocess(
                    command=self.settings.agent_command,
                    payload=agent_payload,
                    timeout_seconds=self.settings.final_timeout,
                )
            except Exception as exc:
                try:
                    await self.refund_user(
                        recipient=sender,
                        payment_amount=amount,
                        original_tx_hash=tx_hash,
                        reason=str(exc),
                    )
                except Exception:
                    logger.exception("Refund sub-task failed inside runner")
                raise
        return runner

    async def handle_invoke(self, request: web.Request) -> web.Response:
        from aiohttp import web

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        tx_hash = str(payload.get("tx", "")).strip()
        nonce = str(payload.get("nonce", "")).strip()
        capability = str(payload.get("capability", "")).strip()

        if not tx_hash or not nonce or not capability:
            return web.json_response({"error": "tx, nonce, capability are required"}, status=400)

        if capability != self.settings.capability:
            return web.json_response({"error": "Unsupported capability"}, status=400)

        missing = validate_body(payload, self.settings.args_schema)
        if missing:
            return web.json_response({"error": "Missing required fields", "missing": missing}, status=400)

        if await self.tx_store.is_processed(tx_hash):
            return web.json_response({"error": "Transaction already used"}, status=409)

        try:
            verified_payment = await self.verifier.verify(tx_hash=tx_hash, raw_nonce=nonce)
        except PaymentVerificationError as exc:
            return web.json_response({"error": str(exc)}, status=402)
        except Exception:
            logger.exception("Payment verification error")
            return web.json_response({"error": "Payment verification failed"}, status=502)

        try:
            await self.tx_store.mark_processed(tx_hash)
        except Exception:
            return web.json_response({"error": "Failed to persist transaction"}, status=500)

        agent_payload = {
            "capability": capability,
            "body": payload["body"],
        }

        job_id = await self.jobs.submit(
            self._create_runner(agent_payload, verified_payment.sender, verified_payment.amount, tx_hash)
        )

        record = await self.jobs.wait_for_completion(job_id, timeout_seconds=self.settings.sync_timeout)

        if record is None:
            return web.json_response({"job_id": job_id, "status": "pending"})

        if record.status == "done":
            return web.json_response({"job_id": job_id, "status": "done", "result": record.result})

        if record.status == "error":
            return web.json_response({"job_id": job_id, "status": "error", "error": record.error}, status=500)

        return web.json_response({"job_id": job_id, "status": "pending"})

    async def handle_result(self, request: web.Request) -> web.Response:
        from aiohttp import web

        job_id = request.match_info["job_id"]
        record = await self.jobs.get(job_id)
        if record is None:
            return web.json_response({"error": "Job not found"}, status=404)

        response: dict[str, Any] = {"status": record.status}
        if record.result is not None:
            response["result"] = record.result
        if record.error is not None:
            response["error"] = record.error
        return web.json_response(response)

    async def handle_info(self, _: web.Request) -> web.Response:
        from aiohttp import web

        state = self.state_store.load()
        return web.json_response(
            {
                "capabilities": [self.settings.capability],
                "price": self.settings.agent_price,
                "docs_bag_id": state.bag_id,
            }
        )

    def build_web_app(self) -> web.Application:
        from aiohttp import web

        app = web.Application(client_max_size=1024 * 1024 * 2)  # Limit 2MB
        app.add_routes(
            [
                web.post("/invoke", self.handle_invoke),
                web.get("/result/{job_id}", self.handle_result),
                web.get("/info", self.handle_info),
            ]
        )
        app.on_startup.append(lambda _: self.startup())
        app.on_shutdown.append(lambda _: self.shutdown())
        return app


