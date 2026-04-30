from __future__ import annotations

import asyncio
import logging

from api import SidecarApp
from settings import Settings

logger = logging.getLogger("sidecar")


async def run_server(settings: Settings) -> int:
    from aiohttp import web

    app = SidecarApp(settings).build_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)

    logger.info("Starting sidecar on port %s", settings.port)
    await site.start()

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        logger.info("Stopping sidecar")
    finally:
        await runner.cleanup()
    return 0
