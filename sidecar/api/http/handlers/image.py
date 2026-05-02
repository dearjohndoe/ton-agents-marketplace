from __future__ import annotations

from pathlib import Path

from aiohttp import web

from api.constants import IMAGE_EXT_MIME


async def handle_image(request: web.Request, images_dir: Path) -> web.StreamResponse:
    name = request.match_info.get("name", "")
    # Defence in depth — aiohttp already strips path segments, but keep explicit check.
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return web.Response(status=404)

    ext = Path(name).suffix.lower()
    mime = IMAGE_EXT_MIME.get(ext)
    if mime is None:
        return web.Response(status=404)

    raw = images_dir / name
    if raw.is_symlink():
        return web.Response(status=404)
    path = raw.resolve()
    try:
        path.relative_to(images_dir)
    except ValueError:
        return web.Response(status=404)
    if not path.is_file():
        return web.Response(status=404)

    return web.FileResponse(
        path,
        headers={
            "Content-Type": mime,
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )
