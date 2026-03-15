import re
from pathlib import Path

base_dir = Path("/media/second_disk/cont5/sidecar")
sidecar_py = base_dir / "sidecar.py"
api_py = base_dir / "api.py"
cli_py = base_dir / "cli.py"
settings_py = base_dir / "settings.py"

content = sidecar_py.read_text()

# Extract settings definitions
settings_start = content.index("@dataclass\nclass ArgSchema:")
settings_end = content.index("def generate_docs(")

settings_content = "import os\nfrom dataclasses import dataclass\n" + content[settings_start:settings_end]
settings_py.write_text(settings_content)

# Extract api definitions
api_start = content.index("def generate_docs(")
api_end = content.index("async def handle_storage_status(")

api_content = """from __future__ import annotations

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

""" + content[api_start:api_end]

# Modify api_content for background task wrapper and max size dos limit
api_content = api_content.replace(
"""        self.background_tasks.append(asyncio.create_task(self.heartbeat.loop(self.stop_event)))
        self.background_tasks.append(asyncio.create_task(self.cleanup_loop()))
        self.background_tasks.append(asyncio.create_task(self.storage_loop()))""",
"""
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
"""
)

# Fix job runner out of handle_invoke inside api.py
api_content = api_content.replace(
"""        agent_payload = {
            "capability": capability,
            "body": payload["body"],
        }

        async def runner() -> dict[str, Any]:
            try:
                return await run_agent_subprocess(
                    command=self.settings.agent_command,
                    payload=agent_payload,
                    timeout_seconds=self.settings.final_timeout,
                )
            except Exception as exc:
                await self.refund_user(
                    recipient=verified_payment.sender,
                    payment_amount=verified_payment.amount,
                    original_tx_hash=tx_hash,
                    reason=str(exc),
                )
                raise""",
"""        agent_payload = {
            "capability": capability,
            "body": payload["body"],
        }

        job_id = await self.jobs.submit(
            self._create_runner(agent_payload, verified_payment.sender, verified_payment.amount, tx_hash)
        )"""
)

api_content = api_content.replace("        job_id = await self.jobs.submit(runner)\n", "")

runner_method = """

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

    async def handle_invoke(self, request: web.Request) -> web.Response:"""

api_content = api_content.replace("    async def handle_invoke(self, request: web.Request) -> web.Response:", runner_method)

# Fix JSON parsing and set payload limit inside handle_invoke
api_content = api_content.replace("        if self.tx_store.is_processed(tx_hash):", "        if await self.tx_store.is_processed(tx_hash):")
api_content = api_content.replace("            self.tx_store.mark_processed(tx_hash)", "            await self.tx_store.mark_processed(tx_hash)")


api_content = api_content.replace("""    def build_web_app(self) -> web.Application:
        from aiohttp import web

        app = web.Application()""", """    def build_web_app(self) -> web.Application:
        from aiohttp import web

        app = web.Application(client_max_size=1024 * 1024 * 2)  # Limit 2MB""")


# Ensure sleep instead of wait_for in clean loop and storage loop
api_content = api_content.replace("""            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                continue""", """            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass""")
api_content = api_content.replace("""            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=3600)
            except asyncio.TimeoutError:
                continue""", """            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=3600)
            except asyncio.TimeoutError:
                pass""")


api_py.write_text(api_content)


# Extract cli definitions
cli_start = content.index("async def handle_storage_status(")

cli_content = """from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from api import SidecarApp
from storage import StateStore, TonStorageClient, parse_storage_expiry, should_extend_storage
from settings import Settings, load_settings

logger = logging.getLogger("sidecar")

""" + content[cli_start:]

cli_py.write_text(cli_content)

# Update sidecar.py to just act as an entrypoint
sidecar_content = """from cli import main

if __name__ == "__main__":
    main()
"""
sidecar_py.write_text(sidecar_content)

print("Split completed successfully")
