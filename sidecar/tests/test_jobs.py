"""Tests for jobs.py — JobStore lifecycle + run_agent_subprocess."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from jobs import JobRecord, JobStore, run_agent_subprocess


# ── JobStore ───────────────────────────────────────────────────────────

async def test_submit_creates_pending_record():
    store = JobStore()

    async def slow_runner():
        await asyncio.sleep(0.05)
        return {"result": {"type": "text", "data": "ok"}}

    job_id = await store.submit(slow_runner)
    record = await store.get(job_id)
    assert record is not None
    assert record.job_id == job_id
    assert record.status == "pending"


async def test_wait_for_completion_returns_done():
    store = JobStore()

    async def runner():
        return {"result": {"type": "text", "data": "hello"}}

    job_id = await store.submit(runner)
    record = await store.wait_for_completion(job_id, timeout_seconds=5)
    assert record is not None
    assert record.status == "done"
    assert record.result == {"result": {"type": "text", "data": "hello"}}
    assert record.error is None


async def test_wait_for_completion_timeout_returns_pending():
    store = JobStore()

    async def slow_runner():
        await asyncio.sleep(2.0)
        return {"result": {"type": "text", "data": "late"}}

    job_id = await store.submit(slow_runner)
    record = await store.wait_for_completion(job_id, timeout_seconds=0)
    assert record is not None
    assert record.status == "pending"
    # Poll a few times instead of a fixed sleep — we want to confirm the task
    # eventually completes even after the caller gave up waiting.
    for _ in range(50):
        record = await store.get(job_id)
        if record.status == "done":
            break
        await asyncio.sleep(0.05)
    assert record.status == "done"


async def test_wait_for_completion_unknown_job_id():
    store = JobStore()
    record = await store.wait_for_completion("does-not-exist", timeout_seconds=1)
    assert record is None


async def test_runner_exception_marks_error():
    store = JobStore()

    async def broken_runner():
        raise ValueError("boom")

    job_id = await store.submit(broken_runner)
    record = await store.wait_for_completion(job_id, timeout_seconds=5)
    assert record.status == "error"
    assert record.error == "Agent processing failed"
    assert record.result is None


async def test_mark_done_ignores_unknown_job_id():
    store = JobStore()
    await store._mark_done("ghost", {"any": "thing"})  # must not raise


async def test_mark_error_ignores_unknown_job_id():
    store = JobStore()
    await store._mark_error("ghost", "anything")


async def test_cleanup_removes_stale_records():
    store = JobStore(ttl_seconds=0)

    async def runner():
        return {"result": {"type": "text", "data": "x"}}

    job_id = await store.submit(runner)
    await store.wait_for_completion(job_id, timeout_seconds=5)

    # Force the record to look ancient.
    record = await store.get(job_id)
    record.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    await store.cleanup()
    assert await store.get(job_id) is None


async def test_cleanup_cancels_still_running_task():
    store = JobStore(ttl_seconds=0)
    started = asyncio.Event()

    async def hanger():
        started.set()
        await asyncio.sleep(60)
        return {"result": {"type": "text", "data": "never"}}

    job_id = await store.submit(hanger)
    await started.wait()
    record = await store.get(job_id)
    record.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    await store.cleanup()
    # Give the cancellation a moment to propagate.
    await asyncio.sleep(0.05)
    assert await store.get(job_id) is None


async def test_submit_generates_unique_ids():
    store = JobStore()

    async def runner():
        return {"result": {"type": "text", "data": "x"}}

    ids = set()
    for _ in range(20):
        ids.add(await store.submit(runner))
    assert len(ids) == 20


# ── run_agent_subprocess ───────────────────────────────────────────────

def _py_cmd(code: str) -> str:
    return f'{sys.executable} -c "{code}"'


async def test_run_agent_subprocess_success():
    code = (
        "import json, sys; "
        "data=json.loads(sys.stdin.read()); "
        r"print(json.dumps({\"echoed\": data[\"mode\"]}))"
    )
    result = await run_agent_subprocess(_py_cmd(code), {"mode": "describe"}, timeout_seconds=5)
    assert result == {"echoed": "describe"}


async def test_run_agent_subprocess_timeout():
    code = "import time; time.sleep(5)"
    with pytest.raises(TimeoutError):
        await run_agent_subprocess(_py_cmd(code), {"mode": "describe"}, timeout_seconds=1)


async def test_run_agent_subprocess_nonzero_exit_raises():
    code = "import sys; sys.stderr.write('bad'); sys.exit(2)"
    with pytest.raises(RuntimeError, match="Agent processing failed"):
        await run_agent_subprocess(_py_cmd(code), {}, timeout_seconds=5)


async def test_run_agent_subprocess_empty_stdout_raises():
    code = "pass"  # no output
    with pytest.raises(ValueError, match="empty stdout"):
        await run_agent_subprocess(_py_cmd(code), {}, timeout_seconds=5)


async def test_run_agent_subprocess_invalid_json_raises():
    code = r"print('not json at all')"
    with pytest.raises(ValueError, match="invalid JSON"):
        await run_agent_subprocess(_py_cmd(code), {}, timeout_seconds=5)


async def test_run_agent_subprocess_non_dict_json_raises():
    code = r"import json; print(json.dumps([1, 2, 3]))"
    with pytest.raises(ValueError, match="must be a JSON object"):
        await run_agent_subprocess(_py_cmd(code), {}, timeout_seconds=5)


async def test_run_agent_subprocess_propagates_env_vars():
    code = (
        "import os, json; "
        r"print(json.dumps({\"sidecar_id\": os.environ.get(\"OWN_SIDECAR_ID\",\"\")}))"
    )
    result = await run_agent_subprocess(
        _py_cmd(code), {}, timeout_seconds=5, env={"OWN_SIDECAR_ID": "sid-xyz"}
    )
    assert result == {"sidecar_id": "sid-xyz"}


async def test_run_agent_subprocess_sets_sidecar_python():
    code = (
        "import os, json; "
        r"print(json.dumps({\"py\": os.environ.get(\"SIDECAR_PYTHON\",\"\")}))"
    )
    result = await run_agent_subprocess(_py_cmd(code), {}, timeout_seconds=5)
    assert result["py"] == sys.executable
