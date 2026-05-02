"""
Reference template for a Catallaxy agent.

This file is for documentation purposes. The actual template used by
scaffold_agent is embedded as a string in mcp/tools/development.py
(AGENT_TEMPLATE constant).

A Catallaxy agent:
- Reads JSON from stdin
- Writes JSON to stdout
- On error: writes to stderr and exits with non-zero exit code

Modes:
  describe: {"mode": "describe"} → {"args_schema": {...}, "result_schema": {...}}
  execute:  {"capability": "...", "body": {...}} → {"result": {"type": "...", "data": ...}}
  quote:    {"mode": "quote", "capability": "...", "sku": "...", "body": {...}} → {"price": int, "price_usdt": int?, "plan": "...", "ttl": int}
  prices:   {"mode": "prices"} → {"sku_id": {"ton": int, "usd": int}, ...}  # only for SKUs with ton=0/usd=0 sentinel
"""

import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ARGS_SCHEMA = {
    "input": {
        "type": "string",
        "description": "The input to process",
        "required": True,
    }
}

RESULT_SCHEMA = {"type": "string"}


def main():
    task = json.load(sys.stdin)

    if task.get("mode") == "describe":
        print(json.dumps({
            "args_schema": ARGS_SCHEMA,
            "result_schema": RESULT_SCHEMA,
        }))
        return

    body = task.get("body") or {}

    # --- YOUR LOGIC HERE ---
    result = body.get("input", "")
    # --- END ---

    print(json.dumps({"result": {"type": "string", "data": result}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
