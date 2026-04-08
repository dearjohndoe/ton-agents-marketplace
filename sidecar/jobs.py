from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class JobRecord:
    job_id: str
    status: str = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class JobStore:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._jobs: dict[str, JobRecord] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    async def submit(self, runner: Callable[[], Awaitable[dict[str, Any]]]) -> str:
        job_id = str(uuid.uuid4())
        record = JobRecord(job_id=job_id)
        async with self._lock:
            self._jobs[job_id] = record

        task = asyncio.create_task(self._run_job(job_id, runner))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
        return job_id

    async def _run_job(self, job_id: str, runner: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        try:
            result = await runner()
            await self._mark_done(job_id, result)
        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
            await self._mark_error(job_id, "Agent processing failed")

    async def wait_for_completion(self, job_id: str, timeout_seconds: int) -> JobRecord | None:
        task = self._tasks.get(job_id)
        if task is None:
            return await self.get(job_id)

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            pass
        return await self.get(job_id)

    async def _mark_done(self, job_id: str, result: dict[str, Any]) -> None:
        async with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.status = "done"
            record.result = result
            record.error = None

    async def _mark_error(self, job_id: str, error: str) -> None:
        async with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.status = "error"
            record.error = error

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        async with self._lock:
            stale_ids = [
                job_id
                for job_id, record in self._jobs.items()
                if now - record.created_at > self._ttl
            ]
            for job_id in stale_ids:
                self._jobs.pop(job_id, None)
                task = self._tasks.pop(job_id, None)
                if task and not task.done():
                    task.cancel()


_SENSITIVE_ENV_KEYS = frozenset({"AGENT_WALLET_PK", "AGENT_WALLET_SEED"})


async def run_agent_subprocess(
    command: str, payload: dict[str, Any], timeout_seconds: int, env: dict[str, str] | None = None
) -> dict[str, Any]:
    import os
    import sys
    env_vars = {k: v for k, v in os.environ.items() if k not in _SENSITIVE_ENV_KEYS}
    env_vars["SIDECAR_PYTHON"] = sys.executable
    if env:
        env_vars.update(env)

    process = await asyncio.create_subprocess_shell(
        command,
        env=env_vars,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    input_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(input=input_bytes), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise TimeoutError("Agent subprocess timed out") from exc

    if process.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        logger.error("Agent subprocess failed (exit %d): %s", process.returncode, stderr_text)
        raise RuntimeError("Agent processing failed")

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    if not stdout_text:
        raise ValueError("Agent subprocess returned empty stdout")

    try:
        parsed = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        logger.error(f"Agent subprocess returned invalid JSON. Output was: {stdout_text}")
        raise ValueError("Agent subprocess returned invalid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Agent subprocess response must be a JSON object")

    return parsed
