from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from api.app import SidecarApp


def register_routes(app: web.Application, sidecar: "SidecarApp") -> None:
    app.add_routes(
        [
            web.post("/invoke", sidecar.handle_invoke),
            web.post("/quote", sidecar.handle_quote),
            web.get("/result/{job_id}", sidecar.handle_result),
            web.get("/download/{file_id}", sidecar.handle_download),
            web.get("/images/{name}", sidecar.handle_image),
            web.get("/info", sidecar.handle_info),
        ]
    )
