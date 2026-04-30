from __future__ import annotations

from typing import Any

from transfer import PAYMENT_OPCODE

from .types import NonceMeta


def parse_nonce(raw_nonce: str) -> NonceMeta:
    return NonceMeta(value=raw_nonce.strip())


def _parse_payment_nonce(body: Any) -> str:
    if body is None:
        return ""
    try:
        s = body.begin_parse()
        if s.remaining_bits < 32:
            return ""
        if s.load_uint(32) != PAYMENT_OPCODE:
            return ""
        return s.load_snake_string()
    except Exception:
        return ""
