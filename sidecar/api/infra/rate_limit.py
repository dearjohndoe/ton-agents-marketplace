from __future__ import annotations

import time


def cleanup_rate_limits(rate_limits: dict[str, list[float]], window_seconds: int) -> None:
    """Drop rate-limit entries whose every timestamp is stale.

    Without this sweep, rate_limits grows unboundedly as new IPs connect —
    the middleware only filters a key's history when that same IP makes
    another request, so rotating source IPs is a slow-drip memory leak.
    """
    cutoff = time.time() - window_seconds
    stale = [
        ip
        for ip, history in rate_limits.items()
        if not history or all(ts <= cutoff for ts in history)
    ]
    for ip in stale:
        rate_limits.pop(ip, None)
