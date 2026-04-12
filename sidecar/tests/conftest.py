"""Shared fixtures and sys.path setup for sidecar tests.

The sidecar package uses flat imports (e.g. ``from jobs import ...``)
rather than package-qualified imports, so the sidecar directory itself
must be on ``sys.path`` before any test module imports from it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parent.parent
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))


import pytest  # noqa: E402


@pytest.fixture
def tmp_state_path(tmp_path: Path) -> str:
    return str(tmp_path / "state.json")


@pytest.fixture
def tmp_tx_db(tmp_path: Path) -> str:
    return str(tmp_path / "processed.db")


@pytest.fixture
def tmp_file_store(tmp_path: Path) -> Path:
    d = tmp_path / "file_store"
    d.mkdir()
    return d


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Strip AGENT_* / SIDECAR_* / TESTNET env vars so settings tests start clean."""
    for key in list(os.environ.keys()):
        if key.startswith(("AGENT_", "SIDECAR_", "REGISTRY_", "PAYMENT_", "JOBS_",
                           "FILE_STORE_", "RATE_LIMIT_", "TRUSTED_PROXY_", "REFUND_",
                           "ENFORCE_COMMENT_NONCE", "TESTNET", "PORT")):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch
