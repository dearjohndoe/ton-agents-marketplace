import json

from mcp.server.fastmcp import FastMCP

from lib.agent_runner import run_agent

from .template import VALID_ARG_TYPES, _extract_fields


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def test_agent(
        agent_dir: str,
        test_body: dict | None = None,
        timeout: int = 30,
    ) -> dict:
        """Run agent locally and verify stdin→stdout contract.

        Uses AGENT_COMMAND from the agent's .env (respects $SIDECAR_PYTHON).
        See catallaxy://guide/gotchas for known pitfalls.
        """
        errors = []

        # describe
        code, stdout, stderr = await run_agent(agent_dir, {"mode": "describe"}, timeout=10)
        describe_ok = False
        args_schema = {}
        result_schema = {}
        if code != 0:
            errors.append(f"describe failed (exit {code}): {stderr}")
        else:
            try:
                desc = json.loads(stdout)
                args_schema = desc.get("args_schema", {})
                result_schema = desc.get("result_schema", {})
                if not isinstance(args_schema, dict):
                    errors.append("args_schema is not a dict")
                else:
                    # Support both flat {field: {type, desc}} and JSON Schema {type:object, properties:{}}
                    fields = _extract_fields(args_schema)
                    for fname, fdef in fields.items():
                        if not isinstance(fdef, dict):
                            continue  # skip non-field entries (e.g. "required" list)
                        if fdef.get("type") not in VALID_ARG_TYPES | {"integer", "array", "object"}:
                            errors.append(f"field '{fname}' has unusual type '{fdef.get('type')}'")
                    describe_ok = not errors
            except json.JSONDecodeError as e:
                errors.append(f"describe: invalid JSON: {e}")

        test_result = None
        test_ok = False
        if test_body is not None:
            cap = list(args_schema.get("properties", args_schema).keys())[0] if args_schema else "test"
            code, stdout, stderr = await run_agent(agent_dir, {"capability": cap, "body": test_body}, timeout=timeout)
            if code != 0:
                errors.append(f"execute failed (exit {code}): {stderr}")
            else:
                try:
                    out = json.loads(stdout)
                    test_result = out.get("result")
                    if not test_result or "type" not in test_result or "data" not in test_result:
                        errors.append("result missing 'type' or 'data'")
                    else:
                        test_ok = True
                except json.JSONDecodeError as e:
                    errors.append(f"execute: invalid JSON: {e}")

        return {
            "describe_ok": describe_ok,
            "args_schema": args_schema,
            "result_schema": result_schema,
            "test_result": test_result,
            "test_ok": test_ok,
            "errors": errors,
        }
