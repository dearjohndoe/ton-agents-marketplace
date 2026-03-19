"""
TON Agent Marketplace — Agent Template
=======================================
Copy this file and implement your own logic in `process_task`.

Contract:
  stdin  — JSON task object
  stdout — JSON result object
  exit 0 — success
  exit 1 — error (message on stderr)
"""
from __future__ import annotations

import json
import sys


# ---------------------------------------------------------------------------
# Schema definition
#
# Describe every input field your agent accepts.
# Supported types: "string" | "number" | "boolean"
# This dict is returned in describe mode and included in the heartbeat so
# the marketplace frontend can render the call form automatically.
# ---------------------------------------------------------------------------
ARGS_SCHEMA: dict = {
    "text": {
        "type": "string",
        "description": "Input text to process",
        "required": True,
    },
    "max_length": {
        "type": "number",
        "description": "Maximum length of the output (optional)",
        "required": False,
    },
    "verbose": {
        "type": "boolean",
        "description": "Return extra details in the response",
        "required": False,
    },
}

# The capability name must match AGENT_CAPABILITY in your .env file
CAPABILITY = "my_capability"


def process_task(task: dict) -> dict:
    # ------------------------------------------------------------------
    # Describe mode — called once at sidecar startup to fetch the schema.
    # Return ARGS_SCHEMA so the marketplace can show the call form.
    # ------------------------------------------------------------------
    if task.get("mode") == "describe":
        return {"args_schema": ARGS_SCHEMA}

    # ------------------------------------------------------------------
    # Normal invocation
    # ------------------------------------------------------------------
    capability = task.get("capability")
    if capability != CAPABILITY:
        raise ValueError(f"Unsupported capability: {capability!r}")

    body: dict = task.get("body") or {}

    # Validate required fields
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("body.text must be a non-empty string")

    # Optional fields with defaults
    max_length: int | None = body.get("max_length")
    verbose: bool = body.get("verbose", False)

    # ------------------------------------------------------------------
    # TODO: implement your agent logic here
    # ------------------------------------------------------------------
    result_text = text[:max_length] if max_length else text  # placeholder

    if verbose:
        return {"result": {"output": result_text, "length": len(result_text)}}
    return {"result": result_text}


def main() -> None:
    task = json.load(sys.stdin)
    result = process_task(task)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
