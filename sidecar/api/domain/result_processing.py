from __future__ import annotations

import base64
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from api.constants import MIME_EXT

logger = logging.getLogger("sidecar")


def is_out_of_stock_result(raw: dict[str, Any]) -> bool:
    return isinstance(raw, dict) and str(raw.get("error", "")).strip() == "out_of_stock"


def process_file_result(
    result: dict[str, Any],
    file_store: dict[str, dict[str, Any]],
    file_store_dir: Path,
    file_store_ttl: int,
) -> dict[str, Any]:
    """If result is type=file with base64 data, store to disk and replace with download URL."""
    if result.get("type") != "file":
        return result
    if "data" not in result:
        # Agent declared type=file but sent no payload — surface the
        # contract violation instead of silently forwarding a broken
        # result to the caller.
        raise ValueError("File result is missing required 'data' field")

    raw_data = result["data"]
    if not isinstance(raw_data, str) or not raw_data:
        raise ValueError("File result 'data' must be a non-empty base64 string")

    file_id = uuid.uuid4().hex
    mime_type = result.get("mime_type", "application/octet-stream")
    ext = MIME_EXT.get(mime_type, "")
    file_name = result.get("file_name") or f"{file_id[:12]}{ext}"

    try:
        file_bytes = base64.b64decode(raw_data)
    except Exception as exc:
        raise ValueError(f"File result contains invalid base64 data: {exc}") from exc

    if not file_bytes:
        raise ValueError("File result decoded to empty bytes")

    file_path = file_store_dir / f"{file_id}{ext}"
    file_path.write_bytes(file_bytes)

    expires_at = time.time() + file_store_ttl
    file_store[file_id] = {
        "path": str(file_path),
        "mime_type": mime_type,
        "file_name": file_name,
        "expires_at": expires_at,
    }

    return {
        "type": "file",
        "url": f"/download/{file_id}",
        "mime_type": mime_type,
        "file_name": file_name,
        "expires_in": file_store_ttl,
    }


def safe_extract_result(
    record_result: Any,
    file_store: dict[str, dict[str, Any]],
    file_store_dir: Path,
    file_store_ttl: int,
) -> tuple[dict[str, Any] | Any, str | None]:
    """Extract and process agent result safely. Returns (result, error_or_none)."""
    try:
        final_res = record_result.get("result", record_result) if isinstance(record_result, dict) else record_result
        if isinstance(final_res, dict):
            final_res = process_file_result(final_res, file_store, file_store_dir, file_store_ttl)
        return final_res, None
    except Exception:
        logger.exception("Failed to process agent result")
        return None, "Failed to process agent result"
