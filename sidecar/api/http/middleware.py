from __future__ import annotations

import time

from aiohttp import web

from settings import Settings


def make_cors_middleware():
    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400",
        }
        if request.method == "OPTIONS":
            return web.Response(status=204, headers=cors_headers)
        response = await handler(request)
        response.headers.update(cors_headers)
        return response

    return cors_middleware


def make_rate_limit_middleware(settings: Settings, rate_limits: dict[str, list[float]]):
    @web.middleware
    async def rate_limit_middleware(request: web.Request, handler):
        if request.method == "OPTIONS" or request.path == "/info" or request.path.startswith("/download/"):
            return await handler(request)

        remote = request.remote or ""
        if remote and settings.trusted_proxy_ips and remote in settings.trusted_proxy_ips:
            ip = (request.headers.get("X-Forwarded-For") or remote).split(",")[0].strip()
        else:
            ip = remote or "unknown"

        now = time.time()
        cutoff = now - settings.rate_limit_window

        # Fast cleanup and check
        history = rate_limits.get(ip, [])
        history = [ts for ts in history if ts > cutoff]

        if len(history) >= settings.rate_limit_requests:
            return web.json_response({
                "error": "Too many requests",
                "retry_after": int(history[0] - cutoff)
            }, status=429)

        history.append(now)
        rate_limits[ip] = history

        return await handler(request)

    return rate_limit_middleware
