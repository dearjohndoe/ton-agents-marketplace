from __future__ import annotations

import asyncio
import base64
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

from heartbeat import HeartbeatConfig, HeartbeatManager
from jobs import JobStore, run_agent_subprocess
from storage import StateStore
from transfer import TransferSender, refund_body
from verify import PaymentVerificationError, PaymentVerifier, ProcessedTxStore, parse_nonce
from settings import Settings

logger = logging.getLogger("sidecar")

DESCRIBE_TIMEOUT = 10  # seconds


@dataclass
class QuoteEntry:
    price: int
    expires_at: float  # unix timestamp
    locked: bool = False


DEFAULT_QUOTE_TTL = 120  # seconds


async def fetch_describe(command: str, timeout: int, sidecar_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Call the agent with mode=describe and return (args_schema, result_schema)."""
    try:
        result = await run_agent_subprocess(
            command=command,
            payload={"mode": "describe"},
            timeout_seconds=timeout,
            env={"OWN_SIDECAR_ID": sidecar_id},
        )
        args_schema = result.get("args_schema")
        if not isinstance(args_schema, dict):
            raise RuntimeError("Agent describe response missing valid args_schema")
        result_schema = result.get("result_schema")
        if result_schema is not None and not isinstance(result_schema, dict):
            result_schema = None
        return args_schema, result_schema
    except Exception as exc:
        logger.critical("Critical error: Agent failed to respond to describe mode: %s", exc)
        raise RuntimeError(f"Agent must return valid args_schema on startup. Error: {exc}")


def validate_body(
    payload: dict[str, Any],
    args_schema: dict[str, Any],
    has_tx: bool = False,
    uploaded_files: dict[str, Path] | None = None,
) -> list[str]:
    body = payload.get("body")
    if not isinstance(body, dict):
        body = {}

    missing: list[str] = []
    for field, spec in args_schema.items():
        if not spec.get("required"):
            continue
        if spec.get("type") == "file":
            # Skip file validation on preflight (no tx) — file not sent yet
            if not has_tx:
                continue
            if uploaded_files and field in uploaded_files:
                continue
            missing.append(field)
        elif field not in body:
            missing.append(field)
    return missing


class SidecarApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.args_schema: dict[str, Any] = {}
        self.result_schema: dict[str, Any] | None = None
        self._file_store: dict[str, dict[str, Any]] = {}
        self._file_store_dir = Path(settings.file_store_dir)
        self._file_store_ttl = settings.file_store_ttl
        self.jobs = JobStore(ttl_seconds=settings.jobs_ttl)
        self.tx_store = ProcessedTxStore(settings.tx_db_path)
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
        self.stop_event = asyncio.Event()
        self.sidecar_id: str = ""
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
                result_schema=None,
            ),
            state_store=self.state_store,
            transfer_sender=self.sender.send,
        )
        self.background_tasks: list[asyncio.Task[Any]] = []
        self.quotes: dict[str, QuoteEntry] = {}
        # Rate Limiting state: ip -> list of timestamps
        self.rate_limits: dict[str, list[float]] = {}

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

        try:
            await self.sender.send(recipient, refund_amount, refund_body(original_tx_hash, reason, self.sidecar_id))
        except Exception:
            logger.exception("Failed to send refund")

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
                sidecar_id=self.sidecar_id,
                result_schema=self.result_schema,
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
        await self.tx_store.close()

    async def cleanup_loop(self) -> None:
        while not self.stop_event.is_set():
            await self.jobs.cleanup()
            self._cleanup_expired_files()
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    # ── File store helpers ──────────────────────────────────────────

    _MIME_EXT: dict[str, str] = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp", "audio/wav": ".wav", "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg", "video/mp4": ".mp4", "video/webm": ".webm",
        "application/pdf": ".pdf",
    }

    def _process_file_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """If result is type=file with base64 data, store to disk and replace with download URL."""
        if result.get("type") != "file" or "data" not in result:
            return result

        raw_data = result["data"]
        if not isinstance(raw_data, str) or not raw_data:
            raise ValueError("File result 'data' must be a non-empty base64 string")

        file_id = uuid.uuid4().hex
        mime_type = result.get("mime_type", "application/octet-stream")
        ext = self._MIME_EXT.get(mime_type, "")
        file_name = result.get("file_name") or f"{file_id[:12]}{ext}"

        try:
            file_bytes = base64.b64decode(raw_data)
        except Exception as exc:
            raise ValueError(f"File result contains invalid base64 data: {exc}") from exc

        if not file_bytes:
            raise ValueError("File result decoded to empty bytes")

        file_path = self._file_store_dir / f"{file_id}{ext}"
        file_path.write_bytes(file_bytes)

        expires_at = time.time() + self._file_store_ttl
        self._file_store[file_id] = {
            "path": str(file_path),
            "mime_type": mime_type,
            "file_name": file_name,
            "expires_at": expires_at,
        }

        return {
            "type": "file",
            "url": f"/download/{file_id}",
            "mime_type": mime_type,
            "file_name": file_name,
            "expires_in": self._file_store_ttl,
        }

    def _safe_extract_result(self, record_result: Any) -> tuple[dict[str, Any] | Any, str | None]:
        """Extract and process agent result safely. Returns (result, error_or_none)."""
        try:
            final_res = record_result.get("result", record_result) if isinstance(record_result, dict) else record_result
            if isinstance(final_res, dict):
                final_res = self._process_file_result(final_res)
            return final_res, None
        except Exception as exc:
            logger.exception("Failed to process agent result")
            return None, "Failed to process agent result"

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

    @staticmethod
    def _validate_result_structure(raw: dict[str, Any]) -> None:
        """Ensure agent result has the required {type, data} structure."""
        result = raw.get("result")
        if not isinstance(result, dict):
            raise ValueError("Agent result must be a JSON object with 'type' and 'data' keys")
        if "type" not in result or "data" not in result:
            raise ValueError("Agent result must contain 'type' and 'data' keys")

    def _create_runner(
        self,
        agent_payload: dict[str, Any],
        sender: str,
        amount: int,
        tx_hash: str,
        uploaded_files: dict[str, Path] | None = None,
    ):
        async def runner() -> dict[str, Any]:
            try:
                raw = await run_agent_subprocess(
                    command=self.settings.agent_command,
                    payload=agent_payload,
                    timeout_seconds=self.settings.final_timeout,
                    env={
                        "OWN_SIDECAR_ID": self.sidecar_id,
                        "CALLER_ADDRESS": sender,
                        "CALLER_TX_HASH": tx_hash,
                    },
                )
                self._validate_result_structure(raw)
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
                    )
                except Exception:
                    logger.exception("Refund sub-task failed inside runner")
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
    ) -> tuple[str, str, str, str | None, dict[str, Any], dict[str, Path]]:
        """Parse multipart/form-data invoke request.

        Returns: (tx_hash, nonce, capability, quote_id, body_dict, uploaded_files)
        """
        reader = await request.multipart()
        tx_hash = nonce = capability = ""
        quote_id: str | None = None
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

        return tx_hash, nonce, capability, quote_id, body, uploaded_files

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
                _, _, capability, _, body, _ = await self._parse_multipart_invoke(request)
            else:
                data = await request.json()
                capability = str(data.get("capability", "")).strip()
                body = data.get("body", {})
        except Exception:
            return web.json_response({"error": "Invalid request"}, status=400)

        if not capability:
            return web.json_response({"error": "capability is required"}, status=400)

        if capability != self.settings.capability:
            return web.json_response({"error": "Unsupported capability"}, status=400)

        missing = validate_body({"body": body}, self.args_schema)
        if missing:
            return web.json_response({"error": "Missing required fields", "missing": missing}, status=400)

        quote_payload = {
            "mode": "quote",
            "capability": capability,
            "body": body,
        }

        try:
            agent_result = await run_agent_subprocess(
                command=self.settings.agent_command,
                payload=quote_payload,
                timeout_seconds=self.settings.sync_timeout,
                env={"OWN_SIDECAR_ID": self.sidecar_id},
            )
        except Exception as exc:
            logger.exception("Quote subprocess failed")
            return web.json_response({"error": "Quote generation failed"}, status=500)

        price = agent_result.get("price")
        plan = agent_result.get("plan", "")
        note = agent_result.get("note")
        ttl = int(agent_result.get("ttl", DEFAULT_QUOTE_TTL))

        if not isinstance(price, int) or price <= 0:
            return web.json_response({"error": "Agent returned invalid price"}, status=500)

        self._cleanup_expired_quotes()

        quote_id = str(uuid.uuid4())
        expires_at = time.time() + ttl
        self.quotes[quote_id] = QuoteEntry(price=price, expires_at=expires_at)

        resp: dict[str, Any] = {
            "quote_id": quote_id,
            "price": price,
            "plan": plan,
            "expires_at": int(expires_at),
        }
        if note:
            resp["note"] = note

        return web.json_response(resp)

    async def handle_invoke(self, request: web.Request) -> web.Response:
        from aiohttp import web

        uploaded_files: dict[str, Path] = {}

        try:
            if request.content_type and "multipart/form-data" in request.content_type:
                tx_hash, nonce, capability, quote_id, body, uploaded_files = \
                    await self._parse_multipart_invoke(request)
                payload = {"body": body}
            else:
                data = await request.json()
                tx_hash = str(data.get("tx", "")).strip()
                nonce = str(data.get("nonce", "")).strip()
                capability = str(data.get("capability", "")).strip()
                quote_id = str(data.get("quote_id", "")).strip() or None
                body = data.get("body", {})
                payload = data
        except Exception:
            return web.json_response({"error": "Invalid request"}, status=400)

        if not capability:
            return web.json_response({"error": "capability is required"}, status=400)

        if capability != self.settings.capability:
            return web.json_response({"error": "Unsupported capability"}, status=400)

        # Determine minimum payment amount (quoted or static)
        min_amount = self.settings.agent_price
        if quote_id:
            self._cleanup_expired_quotes()
            quote_entry = self.quotes.get(quote_id)
            if quote_entry is None:
                return web.json_response({"error": "Quote not found or expired"}, status=400)
            if quote_entry.locked and tx_hash:
                return web.json_response({"error": "Quote is currently locked by another request"}, status=409)
            min_amount = quote_entry.price

        # HTTP 402 Payment Required flow — return price before validating body,
        # so preflight pings always get 402 with real price (not 400 for missing fields)
        if not tx_hash:
            if not nonce or not nonce.endswith(f":{self.sidecar_id}"):
                nonce = f"{uuid.uuid4().hex[:16]}:{self.sidecar_id}"

            return web.json_response({
                "error": "Payment required",
                "payment_request": {
                    "address": self.settings.agent_wallet,
                    "amount": str(min_amount),
                    "memo": nonce
                }
            }, status=402, headers={
                "x-ton-pay-address": self.settings.agent_wallet,
                "x-ton-pay-amount": str(min_amount),
                "x-ton-pay-nonce": nonce
            })

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
            verified_payment = await self.verifier.verify(tx_hash=tx_hash, raw_nonce=nonce, min_amount=min_amount)
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

        # Consume quote so it can't be reused
        if quote_id and quote_id in self.quotes:
            del self.quotes[quote_id]

        agent_body = dict(body)
        for field_name, file_path in uploaded_files.items():
            agent_body[f"{field_name}_path"] = str(file_path)
            if f"{field_name}_name" not in agent_body:
                agent_body[f"{field_name}_name"] = file_path.name

        agent_payload = {
            "capability": capability,
            "body": agent_body,
        }

        job_id = await self.jobs.submit(
            self._create_runner(agent_payload, verified_payment.sender, verified_payment.amount, tx_hash, uploaded_files)
        )

        record = await self.jobs.wait_for_completion(job_id, timeout_seconds=self.settings.sync_timeout)

        if record is None:
            return web.json_response({"job_id": job_id, "status": "pending"})

        if record.status == "done":
            final_res, extract_err = self._safe_extract_result(record.result)
            if extract_err:
                return web.json_response({"job_id": job_id, "status": "error", "error": extract_err}, status=500)
            return web.json_response({"job_id": job_id, "status": "done", "result": final_res})

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
            final_res, extract_err = self._safe_extract_result(record.result)
            if extract_err:
                response["status"] = "error"
                response["error"] = extract_err
            else:
                response["result"] = final_res
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
        from aiohttp import web

        return web.json_response({
            "name": self.settings.agent_name,
            "description": self.settings.agent_description,
            "capabilities": [self.settings.capability],
            "price": self.settings.agent_price,
            "args_schema": self.args_schema,
            "result_schema": self.result_schema,
            "sidecar_id": self.sidecar_id,
        })

    def build_web_app(self) -> web.Application:
        from aiohttp import web

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
                
            ip = request.headers.get("X-Forwarded-For", request.remote)
            if ip:
                ip = ip.split(",")[0].strip()
            else:
                ip = "unknown"
                
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
                web.get("/info", self.handle_info),
            ]
        )
        app.on_startup.append(lambda _: self.startup())
        app.on_shutdown.append(lambda _: self.shutdown())
        return app
