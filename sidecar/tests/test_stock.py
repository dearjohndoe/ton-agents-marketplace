"""Unit + small integration tests for stock.py (StockStore)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from settings import AgentSku
from stock import StockStore, UnknownSkuError, StockError


def _skus(stock: int | None = 5) -> tuple[AgentSku, ...]:
    return (
        AgentSku(sku_id="basic", title="Basic", price_ton=1_000_000_000,
                 price_usd=None, initial_stock=stock),
        AgentSku(sku_id="premium", title="Premium", price_ton=5_000_000_000,
                 price_usd=None, initial_stock=stock),
    )


@pytest.fixture
async def store(tmp_path: Path):
    s = StockStore(str(tmp_path / "stock.db"))
    await s.init(_skus())
    yield s
    await s.close()


async def test_init_seeds_skus(store):
    views = await store.list_views()
    ids = {v.sku_id for v in views}
    assert ids == {"basic", "premium"}
    for v in views:
        assert v.total == 5 and v.sold == 0 and v.stock_left == 5


async def test_reserve_happy_path(store):
    ok = await store.reserve("basic", "q1", ttl_seconds=60)
    assert ok is True
    view = await store.get_view("basic")
    assert view.reserved == 1
    assert view.stock_left == 4


async def test_reserve_idempotent_same_key(store):
    assert await store.reserve("basic", "q1", 60) is True
    # Re-reserving the same key should succeed and not double-consume.
    assert await store.reserve("basic", "q1", 60) is True
    view = await store.get_view("basic")
    assert view.reserved == 1
    assert view.stock_left == 4


async def test_reserve_conflicting_sku_raises(store):
    await store.reserve("basic", "q1", 60)
    with pytest.raises(StockError):
        await store.reserve("premium", "q1", 60)


async def test_reserve_concurrent_only_n_succeed(tmp_path):
    s = StockStore(str(tmp_path / "stock.db"))
    skus = (AgentSku(sku_id="basic", title="B", price_ton=1_000, price_usd=None, initial_stock=3),)
    await s.init(skus)
    try:
        results = await asyncio.gather(*[
            s.reserve("basic", f"k{i}", 60) for i in range(10)
        ])
        assert sum(1 for r in results if r) == 3
        view = await s.get_view("basic")
        assert view.reserved == 3
        assert view.stock_left == 0
    finally:
        await s.close()


async def test_reserve_out_of_stock_returns_false(store):
    for i in range(5):
        assert await store.reserve("basic", f"k{i}", 60) is True
    assert await store.reserve("basic", "k5", 60) is False


async def test_infinite_stock_reserve_never_fails(tmp_path):
    s = StockStore(str(tmp_path / "stock.db"))
    skus = (AgentSku(sku_id="a", title="A", price_ton=1, price_usd=None, initial_stock=None),)
    await s.init(skus)
    try:
        for i in range(50):
            assert await s.reserve("a", f"k{i}", 60) is True
        v = await s.get_view("a")
        assert v.total is None
        assert v.stock_left is None
    finally:
        await s.close()


async def test_commit_sold_advances_counters(store):
    await store.reserve("basic", "q1", 60)
    await store.commit_sold("q1", tx_hash="TX1")
    view = await store.get_view("basic")
    assert view.sold == 1
    assert view.reserved == 0
    assert view.stock_left == 4


async def test_release_drops_reservation_without_selling(store):
    await store.reserve("basic", "q1", 60)
    await store.release("q1")
    view = await store.get_view("basic")
    assert view.sold == 0
    assert view.reserved == 0
    assert view.stock_left == 5


async def test_agent_out_of_stock_decrements_total(store):
    await store.reserve("basic", "q1", 60)
    sku = await store.agent_out_of_stock("q1")
    assert sku == "basic"
    view = await store.get_view("basic")
    assert view.total == 4
    assert view.sold == 0
    assert view.reserved == 0
    assert view.stock_left == 4


async def test_sweep_expired_drops_orphaned_reservations(tmp_path):
    s = StockStore(str(tmp_path / "stock.db"))
    await s.init(_skus())
    try:
        await s.reserve("basic", "expired", ttl_seconds=1)
        await s.reserve("basic", "alive", ttl_seconds=120)
        # sweep_expired uses current time; jump past the TTL
        import time
        deleted = await s.sweep_expired(now=int(time.time()) + 5)
        assert deleted == 1
        view = await s.get_view("basic")
        # "alive" is still reserved
        assert view.reserved == 1
    finally:
        await s.close()


async def test_sweep_expired_keeps_reservations_with_job_id(tmp_path):
    """A reservation attached to a job is owned by the runner — sweep must leave it alone."""
    s = StockStore(str(tmp_path / "stock.db"))
    await s.init(_skus())
    try:
        await s.reserve("basic", "q1", ttl_seconds=1)
        await s.attach_job("q1", "job-xyz")
        import time
        deleted = await s.sweep_expired(now=int(time.time()) + 5)
        assert deleted == 0
    finally:
        await s.close()


async def test_set_total_updates_and_logs(store):
    await store.set_total("basic", 100, reason="topup")
    view = await store.get_view("basic")
    assert view.total == 100


async def test_adjust_total_positive_and_floor(store):
    new = await store.adjust_total("basic", 3, reason="topup")
    assert new == 8
    # Going below zero floors at 0
    new = await store.adjust_total("basic", -1000, reason="writeoff")
    assert new == 0


async def test_adjust_total_on_infinite_raises(tmp_path):
    s = StockStore(str(tmp_path / "stock.db"))
    skus = (AgentSku(sku_id="a", title="A", price_ton=1, price_usd=None, initial_stock=None),)
    await s.init(skus)
    try:
        with pytest.raises(StockError):
            await s.adjust_total("a", 5, reason="x")
    finally:
        await s.close()


async def test_unknown_sku_raises(store):
    with pytest.raises(UnknownSkuError):
        await store.get_view("ghost")


async def test_two_skus_are_independent(store):
    assert await store.reserve("basic", "q1", 60) is True
    assert await store.reserve("premium", "q2", 60) is True
    b = await store.get_view("basic")
    p = await store.get_view("premium")
    assert b.reserved == 1 and p.reserved == 1
    assert b.stock_left == 4 and p.stock_left == 4


async def test_restart_preserves_total_but_updates_metadata(tmp_path):
    path = str(tmp_path / "stock.db")
    s1 = StockStore(path)
    await s1.init(_skus())
    # Simulate a sale
    await s1.reserve("basic", "q", 60)
    await s1.commit_sold("q", tx_hash="T")
    await s1.close()

    # Reopen with a changed price / title — seed should not reset total/sold.
    s2 = StockStore(path)
    new_skus = (
        AgentSku(sku_id="basic", title="Renamed", price_ton=9_999_999_999,
                 price_usd=None, initial_stock=5),
        AgentSku(sku_id="premium", title="Premium", price_ton=5_000_000_000,
                 price_usd=None, initial_stock=5),
    )
    await s2.init(new_skus)
    try:
        v = await s2.get_view("basic")
        assert v.sold == 1
        assert v.total == 5  # from first init, not overwritten
        assert v.title == "Renamed"
        assert v.price_ton == 9_999_999_999
    finally:
        await s2.close()
