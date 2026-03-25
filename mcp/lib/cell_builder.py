"""Reuses payment_body() from sidecar/transfer.py."""
import base64
import os
import sys

# Add sidecar to path so we can import transfer.py
_SIDECAR = os.path.join(os.path.dirname(__file__), "..", "..", "sidecar")
if _SIDECAR not in sys.path:
    sys.path.insert(0, _SIDECAR)

from transfer import payment_body  # noqa: E402


def build_payment_cell(nonce: str) -> tuple[str, str]:
    """Build TON payment Cell with nonce. Returns (base64_boc, hex_boc)."""
    boc = payment_body(nonce).to_boc()
    return base64.b64encode(boc).decode(), boc.hex()
