from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from api.http.responses import render_done_response
from api.infra.files import cleanup_file

if TYPE_CHECKING:
    from api.app import SidecarApp


async def handle_result(request: web.Request, sidecar: "SidecarApp") -> web.Response:
    job_id = request.match_info["job_id"]
    record = await sidecar.jobs.get(job_id)
    if record is None:
        return web.json_response({"error": "Job not found"}, status=404)

    if record.status == "done":
        return render_done_response(
            job_id, record.result,
            sidecar._file_store, sidecar._file_store_dir, sidecar._file_store_ttl,
        )

    response: dict[str, Any] = {"status": record.status}
    if record.error is not None:
        response["error"] = record.error
    return web.json_response(response)


async def handle_download(request: web.Request, file_store: dict[str, dict[str, Any]]) -> web.Response:
    file_id = request.match_info["file_id"]
    entry = file_store.get(file_id)

    if entry is None:
        return web.json_response({"error": "File not found"}, status=404)

    if time.time() > entry["expires_at"]:
        cleanup_file(file_store, file_id)
        return web.json_response({"error": "File expired"}, status=410)

    file_path = Path(entry["path"])
    if not file_path.exists():
        return web.json_response({"error": "File not found on disk"}, status=404)

    return web.Response(
        body=file_path.read_bytes(),
        content_type=entry["mime_type"],
        headers={
            "Content-Disposition": f'inline; filename="{entry["file_name"]}"',
        },
    )
