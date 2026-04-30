"""Sidecar HTTP layer.

Public exports kept for back-compat with `from api import ...` callers and
test monkeypatching of `api.run_agent_subprocess`.
"""
from __future__ import annotations

# Re-export run_agent_subprocess at the package level so tests can monkeypatch
# it via `monkeypatch.setattr(api_module, "run_agent_subprocess", fake)` and
# have submodules see the patched value (they call `api.run_agent_subprocess`).
from jobs import run_agent_subprocess  # noqa: F401

from api.constants import (
    DESCRIBE_TIMEOUT,
    DYNAMIC_PRICE_CACHE_TTL,
    DEFAULT_QUOTE_TTL,
)
from api.describe import fetch_describe
from api.validation import validate_body
from api.domain.quoting import QuoteEntry
from api.app import SidecarApp

__all__ = [
    "SidecarApp",
    "QuoteEntry",
    "fetch_describe",
    "validate_body",
    "DESCRIBE_TIMEOUT",
    "DYNAMIC_PRICE_CACHE_TTL",
    "DEFAULT_QUOTE_TTL",
    "run_agent_subprocess",
]
