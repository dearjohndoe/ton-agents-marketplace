from __future__ import annotations

import logging
from typing import Any

import api  # noqa: F401  — late binding for monkeypatched run_agent_subprocess

logger = logging.getLogger("sidecar")


async def fetch_describe(command: str, timeout: int, sidecar_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Call the agent with mode=describe and return (args_schema, result_schema)."""
    try:
        result = await api.run_agent_subprocess(
            command=command,
            payload={"mode": "describe"},
            timeout_seconds=timeout,
            env={"OWN_SIDECAR_ID": sidecar_id},
        )
        args_schema = result.get("args_schema")
        if not isinstance(args_schema, dict):
            raise RuntimeError("Agent describe response missing valid args_schema")
        result_schema = result.get("result_schema")
        if result_schema is not None and not isinstance(result_schema, dict):
            result_schema = None
        return args_schema, result_schema
    except Exception as exc:
        logger.critical("Critical error: Agent failed to respond to describe mode: %s", exc)
        raise RuntimeError(f"Agent must return valid args_schema on startup. Error: {exc}")
