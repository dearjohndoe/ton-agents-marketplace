from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_body(
    payload: dict[str, Any],
    args_schema: dict[str, Any],
    has_tx: bool = False,
    uploaded_files: dict[str, Path] | None = None,
) -> list[str]:
    body = payload.get("body")
    if not isinstance(body, dict):
        body = {}

    missing: list[str] = []
    for field, spec in args_schema.items():
        if not spec.get("required"):
            continue
        if spec.get("type") == "file":
            # Skip file validation on preflight (no tx) — file not sent yet
            if not has_tx:
                continue
            if uploaded_files and field in uploaded_files:
                continue
            missing.append(field)
        elif field not in body:
            missing.append(field)
    return missing


def validate_result_structure(raw: dict[str, Any]) -> None:
    """Ensure agent result has the required {type, data} structure."""
    result = raw.get("result")
    if not isinstance(result, dict):
        raise ValueError("Agent result must be a JSON object with 'type' and 'data' keys")
    if "type" not in result or "data" not in result:
        raise ValueError("Agent result must contain 'type' and 'data' keys")
