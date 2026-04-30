from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("sidecar")


def cleanup_file(file_store: dict[str, dict[str, Any]], file_id: str) -> None:
    entry = file_store.pop(file_id, None)
    if entry:
        try:
            Path(entry["path"]).unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to delete file %s", entry["path"])


def cleanup_expired_files(file_store: dict[str, dict[str, Any]]) -> None:
    now = time.time()
    expired = [fid for fid, entry in file_store.items() if entry["expires_at"] <= now]
    for fid in expired:
        cleanup_file(file_store, fid)


def cleanup_uploaded_files(uploaded_files: dict[str, Path]) -> None:
    """Remove upload directories created by parse_multipart_invoke.

    Called on every handle_invoke error path that runs before the agent
    subprocess takes ownership of the files — without this, multipart
    uploads that hit a validation/verification error would accumulate on
    disk forever.
    """
    for file_path in uploaded_files.values():
        try:
            shutil.rmtree(file_path.parent, ignore_errors=True)
        except Exception:
            logger.warning("Failed to cleanup uploaded file dir %s", file_path.parent)
