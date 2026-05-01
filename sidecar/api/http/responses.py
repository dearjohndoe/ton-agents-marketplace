from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web

from api.domain.result_processing import safe_extract_result


def render_done_response(
    job_id: str,
    record_result: Any,
    file_store: dict[str, dict[str, Any]],
    file_store_dir: Path,
    file_store_ttl: int,
) -> web.Response:
    """Translate a done job's payload into HTTP response, recognizing refunds."""
    # Recognize runner-produced refund record without running it through
    # process_file_result (it's already a plain dict, not an agent result).
    if isinstance(record_result, dict):
        inner = record_result.get("result") if isinstance(record_result.get("result"), dict) else None
        if isinstance(inner, dict) and inner.get("status") == "refunded":
            return web.json_response({
                "job_id": job_id,
                "status": "refunded",
                "reason_code": inner.get("reason_code"),
                "reason": inner.get("reason"),
                "refund_tx": inner.get("refund_tx"),
            })

    final_res, extract_err = safe_extract_result(
        record_result, file_store, file_store_dir, file_store_ttl,
    )
    if extract_err:
        return web.json_response({"job_id": job_id, "status": "error", "error": extract_err}, status=500)
    return web.json_response({"job_id": job_id, "status": "done", "result": final_res})
