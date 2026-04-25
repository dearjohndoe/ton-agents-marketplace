"""Tests for settings.py — env parsing, wallet derivation, required keys."""

from __future__ import annotations

import pytest

import settings as settings_module
from settings import Settings, _env_bool, load_settings


# A deterministic hex-encoded 32-byte Ed25519 seed used only for address derivation.
TEST_PK_HEX = "a" * 64


# ── _env_bool ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("TRUE", True),
    ("yes", True), ("YES", True), ("on", True), ("On", True),
    ("0", False), ("false", False), ("no", False), ("off", False),
    ("", False), ("bogus", False),
])
def test_env_bool_variants(monkeypatch, raw, expected):
    monkeypatch.setenv("FLAG", raw)
    assert _env_bool("FLAG", default=not expected) is expected


def test_env_bool_missing_uses_default_true(monkeypatch):
    monkeypatch.delenv("FLAG", raising=False)
    assert _env_bool("FLAG", default=True) is True


def test_env_bool_missing_uses_default_false(monkeypatch):
    monkeypatch.delenv("FLAG", raising=False)
    assert _env_bool("FLAG", default=False) is False


# ── load_settings required keys ────────────────────────────────────────

REQUIRED_KEYS = {
    "AGENT_COMMAND": "echo hi",
    "AGENT_CAPABILITY": "translate",
    "AGENT_NAME": "Translator",
    "AGENT_DESCRIPTION": "Translates text",
    "AGENT_PRICE": "10000000",
    "AGENT_ENDPOINT": "https://example.com",
    "AGENT_WALLET_PK": TEST_PK_HEX,
    "REGISTRY_ADDRESS": "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
}

# Keys that are truly required (always checked)
_ALWAYS_REQUIRED = {k for k in REQUIRED_KEYS if k != "AGENT_PRICE"}


def _apply_required(monkeypatch, overrides: dict[str, str] | None = None):
    for key, val in REQUIRED_KEYS.items():
        monkeypatch.setenv(key, val)
    if overrides:
        for k, v in overrides.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)


def test_load_settings_missing_required_raises(clean_env):
    # no env set at all → must report every required key
    with pytest.raises(RuntimeError) as exc:
        load_settings(env_file="/nonexistent/.env")
    msg = str(exc.value)
    for key in _ALWAYS_REQUIRED:
        assert key in msg


def test_load_settings_missing_single_key_raises(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.delenv("AGENT_COMMAND", raising=False)
    with pytest.raises(RuntimeError) as exc:
        load_settings(env_file="/nonexistent/.env")
    assert "AGENT_COMMAND" in str(exc.value)


def test_load_settings_no_price_at_all_raises(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.delenv("AGENT_PRICE", raising=False)
    monkeypatch.delenv("AGENT_PRICE_USD", raising=False)
    with pytest.raises(RuntimeError, match="AGENT_PRICE.*AGENT_PRICE_USD"):
        load_settings(env_file="/nonexistent/.env")


def test_load_settings_usdt_only(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.delenv("AGENT_PRICE", raising=False)
    monkeypatch.setenv("AGENT_PRICE_USD", "1000000")
    s = load_settings(env_file="/nonexistent/.env")
    assert s.agent_price == 0
    assert s.agent_price_usdt == 1_000_000


def test_load_settings_both_prices(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.setenv("AGENT_PRICE_USD", "500000")
    s = load_settings(env_file="/nonexistent/.env")
    assert s.agent_price == 10_000_000
    assert s.agent_price_usdt == 500_000


def test_load_settings_defaults(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    s = load_settings(env_file="/nonexistent/.env")
    assert isinstance(s, Settings)
    assert s.port == 8080
    assert s.payment_timeout == 300
    assert s.sync_timeout == 30
    assert s.final_timeout == 1200
    assert s.jobs_ttl == 3600
    assert s.testnet is False
    assert s.enforce_comment_nonce is True
    assert s.refund_fee_nanoton == 500000
    assert s.has_quote is False
    assert s.rate_limit_requests == 60
    assert s.rate_limit_window == 60
    assert s.file_store_dir == "file_store"
    assert s.file_store_ttl == 900
    assert s.trusted_proxy_ips == frozenset()
    # wallet is derived from private key, not provided directly
    assert isinstance(s.agent_wallet, str)
    assert len(s.agent_wallet) > 10


def test_load_settings_testnet_toggles_wallet_format(clean_env, monkeypatch):
    _apply_required(monkeypatch, {"TESTNET": "true"})
    s = load_settings(env_file="/nonexistent/.env")
    assert s.testnet is True
    # Just verify it's non-empty and different from a mainnet derivation.
    monkeypatch.setenv("TESTNET", "false")
    s2 = load_settings(env_file="/nonexistent/.env")
    assert s.agent_wallet != s2.agent_wallet


def test_load_settings_trusted_proxy_ips_parsing(clean_env, monkeypatch):
    _apply_required(monkeypatch, {"TRUSTED_PROXY_IPS": "10.0.0.1, 10.0.0.2 ,,  10.0.0.3"})
    s = load_settings(env_file="/nonexistent/.env")
    assert s.trusted_proxy_ips == frozenset({"10.0.0.1", "10.0.0.2", "10.0.0.3"})


def test_load_settings_trusted_proxy_ips_all_whitespace(clean_env, monkeypatch):
    _apply_required(monkeypatch, {"TRUSTED_PROXY_IPS": " ,  ,"})
    s = load_settings(env_file="/nonexistent/.env")
    assert s.trusted_proxy_ips == frozenset()


def test_load_settings_numeric_overrides(clean_env, monkeypatch):
    _apply_required(monkeypatch, {
        "PORT": "9090",
        "PAYMENT_TIMEOUT": "120",
        "AGENT_SYNC_TIMEOUT": "15",
        "AGENT_FINAL_TIMEOUT": "600",
        "JOBS_TTL_SECONDS": "1800",
        "REFUND_FEE_NANOTON": "1234567",
        "RATE_LIMIT_REQUESTS": "200",
        "RATE_LIMIT_WINDOW_SECONDS": "10",
        "FILE_STORE_TTL": "60",
        "FILE_STORE_DIR": "custom_store",
    })
    s = load_settings(env_file="/nonexistent/.env")
    assert s.port == 9090
    assert s.payment_timeout == 120
    assert s.sync_timeout == 15
    assert s.final_timeout == 600
    assert s.jobs_ttl == 1800
    assert s.refund_fee_nanoton == 1234567
    assert s.rate_limit_requests == 200
    assert s.rate_limit_window == 10
    assert s.file_store_ttl == 60
    assert s.file_store_dir == "custom_store"


def test_load_settings_invalid_numeric_raises(clean_env, monkeypatch):
    _apply_required(monkeypatch, {"AGENT_PRICE": "not-a-number"})
    with pytest.raises(ValueError):
        load_settings(env_file="/nonexistent/.env")


def test_derive_wallet_address_strips_0x_prefix():
    addr_with = settings_module._derive_wallet_address("0x" + TEST_PK_HEX, testnet=False)
    addr_without = settings_module._derive_wallet_address(TEST_PK_HEX, testnet=False)
    assert addr_with == addr_without


def test_derive_wallet_address_bad_hex_raises():
    with pytest.raises(ValueError):
        settings_module._derive_wallet_address("zz" * 32, testnet=False)


# ── AGENT_SKUS parsing ─────────────────────────────────────────────────

def test_load_settings_skus_simple(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.setenv("AGENT_SKUS", "basic:10:ton=1000000000,premium:3:ton=5000000000")
    s = load_settings(env_file="/nonexistent/.env")
    assert len(s.skus) == 2
    ids = [x.sku_id for x in s.skus]
    assert ids == ["basic", "premium"]
    assert s.skus[0].price_ton == 1_000_000_000
    assert s.skus[0].initial_stock == 10
    assert s.payment_rails == ("TON",)


def test_load_settings_skus_with_both_rails(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.setenv(
        "AGENT_SKUS",
        "basic:10:ton=1000000000:usd=1500000,premium:3:ton=5000000000:usd=7000000",
    )
    s = load_settings(env_file="/nonexistent/.env")
    assert set(s.payment_rails) == {"TON", "USDT"}
    assert all(sku.price_ton and sku.price_usd for sku in s.skus)


def test_load_settings_skus_inconsistent_rails_raises(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.setenv("AGENT_SKUS", "basic:10:ton=1000000000,premium:3:usd=1500000")
    with pytest.raises(RuntimeError, match="inconsistent_sku_rails"):
        load_settings(env_file="/nonexistent/.env")


def test_load_settings_skus_no_price_raises(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.setenv("AGENT_SKUS", "basic:10:")
    with pytest.raises(RuntimeError):
        load_settings(env_file="/nonexistent/.env")


def test_load_settings_skus_duplicate_id_raises(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.setenv("AGENT_SKUS", "basic:10:ton=1,basic:5:ton=2")
    with pytest.raises(RuntimeError, match="Duplicate"):
        load_settings(env_file="/nonexistent/.env")


def test_load_settings_skus_titles_applied(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.setenv("AGENT_SKUS", "basic:10:ton=1000000000")
    monkeypatch.setenv("AGENT_SKU_TITLES", "basic=Hello World")
    s = load_settings(env_file="/nonexistent/.env")
    assert s.skus[0].title == "Hello World"


def test_load_settings_legacy_synth_single_default_sku(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    monkeypatch.setenv("AGENT_PRICE", "7")
    monkeypatch.setenv("AGENT_STOCK", "42")
    s = load_settings(env_file="/nonexistent/.env")
    assert len(s.skus) == 1
    assert s.skus[0].sku_id == "default"
    assert s.skus[0].price_ton == 7
    assert s.skus[0].initial_stock == 42


def test_load_settings_legacy_infinite_stock_when_unset(clean_env, monkeypatch):
    _apply_required(monkeypatch)
    s = load_settings(env_file="/nonexistent/.env")
    assert s.skus[0].initial_stock is None
