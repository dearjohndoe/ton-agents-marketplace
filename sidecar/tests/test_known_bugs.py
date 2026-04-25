"""Tests that probe for known weaknesses in sidecar code.

These tests encode the BEHAVIOUR WE WANT. Many of them are expected to fail
against the current implementation — they document real bugs that should be
fixed rather than pinned. Each test has a docstring explaining the bug it
catches.

Run this file in isolation to see every pending issue at a glance:

    python -m pytest tests/test_known_bugs.py -v
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

import api as api_module
import transfer as transfer_module
from api import SidecarApp
from settings import AgentSku, DEFAULT_SKU_ID, Settings
from transfer import TransferSender
from verify import PaymentVerificationError, ProcessedTxStore, VerifiedPayment


# ── Shared settings/app builders (subset of test_api.py) ───────────────

def _make_settings(tmp_path: Path, **overrides) -> Settings:
    agent_price = overrides.get("agent_price", 1_000_000)
    agent_price_usdt = overrides.get("agent_price_usdt", None)
    default_sku = AgentSku(
        sku_id=DEFAULT_SKU_ID, title=DEFAULT_SKU_ID,
        price_ton=agent_price if agent_price else None,
        price_usd=agent_price_usdt,
        initial_stock=None,
    )
    rails: list[str] = []
    if default_sku.price_ton is not None:
        rails.append("TON")
    if default_sku.price_usd is not None:
        rails.append("USDT")
    base = dict(
        agent_command="true",
        capability="translate",
        agent_name="Translator",
        agent_description="Translates text",
        agent_price=agent_price,
        agent_endpoint="https://agent.test",
        agent_wallet_pk="a" * 64,
        agent_wallet_seed=None,
        agent_wallet="EQagent",
        registry_address="EQregistry",
        port=8080,
        payment_timeout=300,
        sync_timeout=30,
        final_timeout=1200,
        jobs_ttl=3600,
        testnet=True,
        state_path=str(tmp_path / "state.json"),
        tx_db_path=str(tmp_path / "tx.db"),
        stock_db_path=str(tmp_path / "stock.db"),
        enforce_comment_nonce=True,
        refund_fee_nanoton=500_000,
        agent_price_usdt=agent_price_usdt,
        has_quote=False,
        rate_limit_requests=3,
        rate_limit_window=1,  # short window so eviction test runs fast
        trusted_proxy_ips=frozenset(),
        file_store_dir=str(tmp_path / "file_store"),
        file_store_ttl=60,
        images_dir=str(tmp_path / "images"),
        agent_preview_url=None,
        agent_avatar_url=None,
        agent_images=(),
        skus=(default_sku,),
        payment_rails=tuple(rails),
    )
    base.update(overrides)
    return Settings(**base)


def _make_app(tmp_path: Path, **settings_overrides) -> SidecarApp:
    app = SidecarApp(_make_settings(tmp_path, **settings_overrides))
    app.sidecar_id = "sid-test"
    app.args_schema = {"text": {"type": "string", "required": True}}
    app._file_store_dir.mkdir(parents=True, exist_ok=True)
    return app


@pytest.fixture
async def bug_client(tmp_path):
    """aiohttp TestClient bound to a SidecarApp with mocks for TON deps."""
    app = _make_app(tmp_path)

    async def noop():
        app._file_store_dir.mkdir(parents=True, exist_ok=True)

    app.startup = noop  # type: ignore[method-assign]
    app.shutdown = noop  # type: ignore[method-assign]
    web_app = app.build_web_app()
    web_app.on_startup.clear()
    web_app.on_shutdown.clear()
    web_app.on_startup.append(lambda _: noop())
    web_app.on_shutdown.append(lambda _: noop())

    async with TestClient(TestServer(web_app)) as c:
        c.sidecar = app  # type: ignore[attr-defined]
        yield c


# ────────────────────────────────────────────────────────────────────────
# BUG 1 — rate limiter leaks memory: empty histories are never evicted
# ────────────────────────────────────────────────────────────────────────

async def test_rate_limiter_evicts_empty_histories(bug_client):
    """The rate_limits dict must not grow unboundedly.

    BUG history: the middleware appended each request timestamp into
    ``self.rate_limits[ip]`` and filtered out expired timestamps on every
    subsequent call from the same IP — but when the filtered history became
    empty for an IP that never returned, the key itself was never deleted.
    An attacker rotating source IPs could force the dict to grow without
    bound (slow memory exhaustion / DoS vector).

    Fix contract: the app exposes ``_cleanup_rate_limits()`` (called from
    cleanup_loop on a timer) that sweeps every IP whose entire history is
    now older than the window and drops it from the dict.
    """
    app: SidecarApp = bug_client.sidecar
    assert app.settings.rate_limit_window == 1  # 1 second window from fixture

    # Seed an entry via a non-exempt path so the middleware actually stores
    # a timestamp. /result/<job_id> is non-exempt and returns quickly (404).
    await bug_client.get("/result/nope")
    assert len(app.rate_limits) >= 1

    # Let the window elapse so every stored timestamp is stale.
    await asyncio.sleep(app.settings.rate_limit_window + 0.2)

    # Simulate the periodic cleanup sweep the cleanup_loop would run.
    app._cleanup_rate_limits()

    cutoff = time.time() - app.settings.rate_limit_window
    leaked = {
        ip: hist
        for ip, hist in app.rate_limits.items()
        if not hist or all(ts <= cutoff for ts in hist)
    }
    assert not leaked, (
        f"Rate limiter leaks {len(leaked)} stale histories: {list(leaked.keys())[:5]}"
    )


# ────────────────────────────────────────────────────────────────────────
# BUG 2 — uploaded files leak on pre-runner error paths in handle_invoke
# ────────────────────────────────────────────────────────────────────────

def _uploads_dir(app: SidecarApp) -> Path:
    return app._file_store_dir / "uploads"


def _count_uploaded_files(app: SidecarApp) -> int:
    d = _uploads_dir(app)
    if not d.exists():
        return 0
    return sum(1 for p in d.rglob("*") if p.is_file())


async def test_uploaded_file_cleaned_on_missing_required_body_field(bug_client):
    """Validation failure after upload must not leak files on disk.

    BUG: when a multipart /invoke request parses successfully (file lands on
    disk under file_store/uploads/<uuid>/...) but body validation fails
    because a required field is missing, handle_invoke returns 400 without
    deleting the uploaded file. The cleanup only lives in _create_runner's
    ``finally`` block, which runs only if the request makes it to the agent
    subprocess. Every pre-runner error path leaks its uploads permanently.
    """
    app: SidecarApp = bug_client.sidecar
    assert _count_uploaded_files(app) == 0

    form = FormData()
    form.add_field("capability", "translate")
    form.add_field("tx", "user-tx")
    form.add_field("nonce", "n:sid-test")
    form.add_field("body_json", json.dumps({}))  # missing required "text"
    form.add_field("file:image", io.BytesIO(b"LEAK-ME"),
                   filename="leak.png", content_type="image/png")

    resp = await bug_client.post("/invoke", data=form)
    assert resp.status == 400  # validation fails
    assert _count_uploaded_files(app) == 0, (
        "Uploaded file leaked on validation-error path"
    )


async def test_uploaded_file_cleaned_on_nonce_sidecar_mismatch(bug_client):
    """Same bug, different error branch: nonce sidecar mismatch returns 402
    without cleaning the uploaded files."""
    app: SidecarApp = bug_client.sidecar
    assert _count_uploaded_files(app) == 0

    form = FormData()
    form.add_field("capability", "translate")
    form.add_field("tx", "user-tx")
    form.add_field("nonce", "n:wrong-sid")  # wrong sidecar suffix
    form.add_field("body_json", json.dumps({"text": "hi"}))
    form.add_field("file:image", io.BytesIO(b"LEAK-ME-2"),
                   filename="leak2.png", content_type="image/png")

    resp = await bug_client.post("/invoke", data=form)
    assert resp.status == 402
    assert _count_uploaded_files(app) == 0, (
        "Uploaded file leaked on nonce mismatch path"
    )


async def test_uploaded_file_cleaned_on_payment_verification_error(bug_client):
    """Same bug, verification-error branch."""
    app: SidecarApp = bug_client.sidecar
    app.tx_store.is_processed = AsyncMock(return_value=False)
    app.verifier.verify = AsyncMock(side_effect=PaymentVerificationError("bad"))

    assert _count_uploaded_files(app) == 0

    form = FormData()
    form.add_field("capability", "translate")
    form.add_field("tx", "user-tx")
    form.add_field("nonce", "n:sid-test")
    form.add_field("body_json", json.dumps({"text": "hi"}))
    form.add_field("file:image", io.BytesIO(b"LEAK-ME-3"),
                   filename="leak3.png", content_type="image/png")

    resp = await bug_client.post("/invoke", data=form)
    assert resp.status == 402
    assert _count_uploaded_files(app) == 0, (
        "Uploaded file leaked on PaymentVerificationError path"
    )


async def test_uploaded_file_cleaned_on_duplicate_tx(bug_client):
    """Same bug, duplicate-tx branch."""
    app: SidecarApp = bug_client.sidecar
    app.tx_store.is_processed = AsyncMock(return_value=True)

    assert _count_uploaded_files(app) == 0

    form = FormData()
    form.add_field("capability", "translate")
    form.add_field("tx", "dup-tx")
    form.add_field("nonce", "n:sid-test")
    form.add_field("body_json", json.dumps({"text": "hi"}))
    form.add_field("file:image", io.BytesIO(b"LEAK-ME-4"),
                   filename="leak4.png", content_type="image/png")

    resp = await bug_client.post("/invoke", data=form)
    assert resp.status == 409
    assert _count_uploaded_files(app) == 0, (
        "Uploaded file leaked on duplicate-tx path"
    )


# ────────────────────────────────────────────────────────────────────────
# BUG 3 — TransferSender reconnects+sleeps after the final failed attempt
# ────────────────────────────────────────────────────────────────────────

async def test_transfer_sender_no_reconnect_after_exhaustion(monkeypatch):
    """After exhausting retries, the sender must not reconnect+sleep.

    BUG: the retry loop in TransferSender.send unconditionally calls
    ``await self._reconnect()`` and ``await asyncio.sleep(delay)`` in the
    ``except`` branch, even on the final attempt. When all attempts fail we
    pay for one extra liteserver reconnect and one extra sleep (currently
    5 s on the last delay slot) for no benefit, before the exception is
    raised. The reconnect count should be MAX_RETRIES - 1, not MAX_RETRIES.
    """
    sender = TransferSender(private_key_hex="a" * 64, testnet=True)

    wallet = MagicMock()
    wallet.transfer = AsyncMock(side_effect=ConnectionError("down"))
    reconnect_calls = {"n": 0}

    async def fake_init(self):
        self._client = MagicMock()
        self._client.close = AsyncMock()
        self._wallet = wallet

    async def fake_reconnect(self):
        reconnect_calls["n"] += 1
        await fake_init(self)

    monkeypatch.setattr(TransferSender, "_ensure_initialized", fake_init)
    monkeypatch.setattr(TransferSender, "_reconnect", fake_reconnect)
    monkeypatch.setattr(transfer_module, "SEND_RETRY_DELAYS", [0, 0, 0])
    monkeypatch.setattr(transfer_module, "SEND_MAX_RETRIES", 3)

    with pytest.raises(ConnectionError):
        await sender.send("EQdest", 1_000, MagicMock())

    # Optimal behaviour: reconnect happens only between attempts.
    # With 3 attempts that means 2 reconnects, not 3.
    assert reconnect_calls["n"] == 2, (
        f"Expected 2 reconnects between 3 attempts, got {reconnect_calls['n']} "
        f"(reconnect is still being called after the final failed attempt)"
    )


# ────────────────────────────────────────────────────────────────────────
# BUG 4 — ProcessedTxStore.close does not await the background cleanup task
# ────────────────────────────────────────────────────────────────────────

async def test_processed_tx_store_close_awaits_background_cleanup(tmp_tx_db):
    """mark_processed spawns a fire-and-forget cleanup task; close must wait.

    BUG: every call to ``ProcessedTxStore.mark_processed`` does
    ``asyncio.create_task(self.cleanup(...))`` without tracking the returned
    task. The task is not awaited anywhere. Consequences:
      - ``close()`` can finish while cleanup is mid-flight, leaving a
        dangling coroutine holding a reference to a just-closed sqlite
        connection. Accessing it raises.
      - pytest and production shutdowns both warn about "Task was destroyed
        but it is pending".
    Expected behaviour: either cleanup must run synchronously, or the store
    must keep a handle to its background task and drain it on ``close()``.
    """
    store = ProcessedTxStore(tmp_tx_db)
    cleanup_finished = asyncio.Event()

    async def slow_cleanup(*args, **kwargs):
        # Deliberately slow so the race with close() is deterministic.
        await asyncio.sleep(0.15)
        cleanup_finished.set()

    # Replace the method on the instance — mark_processed reads self.cleanup.
    store.cleanup = slow_cleanup  # type: ignore[method-assign]

    await store.mark_processed("hash-1")
    # close() returns "immediately" because it doesn't know about the task.
    await store.close()

    # If close() properly drained background tasks, the flag is already set.
    assert cleanup_finished.is_set(), (
        "close() returned while a background cleanup task was still pending "
        "— the store is leaking unmanaged asyncio tasks"
    )


# ────────────────────────────────────────────────────────────────────────
# BUG 5 — Heartbeat loop ignores its configured interval
# ────────────────────────────────────────────────────────────────────────

async def test_heartbeat_loop_respects_configured_interval(tmp_state_path):
    """The loop wakes on a hardcoded 3600s timer, not on ``_interval``.

    BUG: HeartbeatManager.__init__ stores ``self._interval`` from the
    ``heartbeat_interval_days`` argument, but ``loop()`` uses a hard-coded
    ``timeout=3600`` for the ``wait_for(stop_event.wait(), ...)``. Changing
    the interval parameter has no effect on how often the loop polls, which
    defeats the point of the parameter.

    Expected behaviour: the loop's wait timeout should be derived from
    ``self._interval`` (or at least a documented fraction of it).
    """
    from heartbeat import HeartbeatConfig, HeartbeatManager
    from storage import StateStore
    import inspect

    cfg = HeartbeatConfig(
        registry_address="EQr", endpoint="https://e", price=1, capability="c",
        name="n", description="d", args_schema={}, has_quote=False,
        sidecar_id=None, result_schema=None,
    )
    mgr = HeartbeatManager(
        config=cfg,
        state_store=StateStore(tmp_state_path),
        transfer_sender=AsyncMock(return_value="h"),
        heartbeat_interval_days=1,
    )

    source = inspect.getsource(HeartbeatManager.loop)
    assert "self._interval" in source, (
        "HeartbeatManager.loop() does not reference self._interval — the "
        "configured interval is ignored"
    )
