"""TON DNS Bind agent — stdin/stdout interface for the sidecar.

Modes:
  describe  → returns args_schema + result_schema
  (default) → resolves domain, builds TON DNS change-record transaction,
               returns a QR code PNG the domain owner scans to sign the update

stdin (default):
  {
    "body": {
      "bag_id": "<64 hex chars>",
      "domain":  "mysite.ton"
    }
  }

stdout:
  {
    "result": {
      "type":      "file",
      "data":      "<base64-encoded PNG>",
      "mime_type": "image/png",
      "file_name": "bind-mysite.ton.png"
    }
  }

The QR encodes a ton:// deep-link that opens Tonkeeper / MyTonWallet and
proposes a ChangeDNSRecord transaction — setting the SITE key of the
domain's NFT contract to the given bag_id. No private key is ever required.
"""

import base64
import io
import json
import os
import sys
from pathlib import Path

import qrcode
import requests
from dotenv import load_dotenv
from tonutils.contracts.dns.tlb import ChangeDNSRecordBody, DNSRecordStorage
from tonutils.types import BagID, DNSCategory

load_dotenv(Path(__file__).parent / ".env")

TONAPI_KEY = os.getenv("TONAPI_KEY", "")
GAS_AMOUNT = 50_000_000

ARGS_SCHEMA = {
    "bag_id": {
        "type": "string",
        "description": "TON Storage bag ID (64 hex chars)",
        "required": True,
    },
    "domain": {
        "type": "string",
        "description": "TON DNS domain, e.g. mysite.ton",
        "required": True,
    },
}


def resolve_domain_address(domain: str) -> str:
    """Returns the NFT item contract address for a .ton domain via tonapi.io."""
    headers = {"Authorization": f"Bearer {TONAPI_KEY}"} if TONAPI_KEY else {}
    resp = requests.get(
        f"https://tonapi.io/v2/dns/{domain}",
        headers=headers,
        timeout=10,
    )
    if resp.status_code == 404:
        raise ValueError(f"Domain {domain!r} not found in TON DNS")
    resp.raise_for_status()
    data = resp.json()
    address = data.get("item", {}).get("address")
    if not address:
        raise ValueError(f"Cannot resolve contract address for {domain!r}")
    return address


def build_deeplink(contract_address: str, body_cell) -> str:
    boc_b64 = base64.urlsafe_b64encode(body_cell.to_boc()).decode().rstrip("=")
    return f"ton://transfer/{contract_address}?amount={GAS_AMOUNT}&bin={boc_b64}"


def make_qr_png_bytes(data: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def main():
    task = json.load(sys.stdin)

    if task.get("mode") == "describe":
        print(json.dumps({
            "args_schema": ARGS_SCHEMA,
            "result_schema": {"type": "file", "mime_type": "image/png"},
        }))
        return

    body = task.get("body") or {}
    bag_id = body.get("bag_id", "").strip().lower()
    domain = body.get("domain", "").strip().lower()

    if len(bag_id) != 64 or not all(c in "0123456789abcdef" for c in bag_id):
        raise ValueError("bag_id must be a 64-character hex string")
    if not domain.endswith(".ton"):
        raise ValueError("domain must end with .ton")

    contract_address = resolve_domain_address(domain)

    body_cell = ChangeDNSRecordBody(
        category=DNSCategory.SITE,
        record=DNSRecordStorage(BagID(bag_id)),
    ).serialize()

    deeplink = build_deeplink(contract_address, body_cell)
    png_bytes = make_qr_png_bytes(deeplink)

    print(json.dumps({
        "result": {
            "type": "file",
            "data": base64.b64encode(png_bytes).decode(),
            "mime_type": "image/png",
            "file_name": f"bind-{domain}.png",
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
