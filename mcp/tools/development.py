import asyncio
import json
import os
import subprocess
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from lib.agent_runner import run_agent

# Scaffold template — includes quote stub when has_quote=True
AGENT_TEMPLATE = '''\
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ARGS_SCHEMA = {args_schema}

RESULT_SCHEMA = {result_schema}


def main():
    task = json.load(sys.stdin)

    if task.get("mode") == "describe":
        print(json.dumps({{
            "args_schema": ARGS_SCHEMA,
            "result_schema": RESULT_SCHEMA,
        }}))
        return

    body = task.get("body") or {{}}
{quote_block}
    # --- YOUR LOGIC HERE ---
    result = ""
    # --- END ---

    print(json.dumps({{"result": {{"type": "{result_type}", "data": result}}}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
'''

QUOTE_BLOCK = '''\
    if task.get("mode") == "quote":
        # Return dynamic price in nanoTON based on body contents.
        # {"price": int_nanoton, "plan": "human-readable plan", "ttl": seconds}
        # exit(1) here = no quote, client sees an error (no payment taken).
        raise NotImplementedError("quote mode not implemented")

'''

ENV_EXAMPLE_TEMPLATE = '''\
AGENT_COMMAND=$SIDECAR_PYTHON agent.py
AGENT_CAPABILITY={capability}
AGENT_NAME={name}
AGENT_DESCRIPTION={description_escaped}
AGENT_PRICE={price}
AGENT_ENDPOINT=https://your-server.example.com
AGENT_WALLET_PK=0x...your_private_key_hex...
REGISTRY_ADDRESS=EQ...
SIDECAR_STATE_PATH=.sidecar_state.json
SIDECAR_TX_DB_PATH=processed_txs.db
PORT=8080
TESTNET=false
AGENT_HAS_QUOTE={has_quote}
'''

REQUIREMENTS_TEMPLATE = '''\
python-dotenv>=1.0.0
'''

VALID_ARG_TYPES = {"string", "number", "boolean", "file"}


def _extract_fields(args_schema: dict) -> dict:
    """Normalise args_schema to a flat {field: {type, description}} dict.

    Accepts both the legacy flat format and standard JSON Schema
    (type=object + properties).  Returns the flat dict for validation.
    """
    if args_schema.get("type") == "object" and "properties" in args_schema:
        return args_schema["properties"]
    return args_schema


def register_development_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    def scaffold_agent(
        name: str,
        capability: str,
        description: str,
        price: int,
        args_schema: dict,
        result_type: str,
        result_mime_type: str | None = None,
        has_quote: bool = False,
        directory: str | None = None,
    ) -> dict:
        """Generate a new agent skeleton with all required files.

        Read catallaxy://guide/create-agent for the full step-by-step guide
        and catallaxy://spec/agent-contract for the stdin/stdout contract.
        """
        project_root = os.getenv("CATALLAXY_PROJECT_ROOT", "/media/second_disk/cont5")
        agent_dir = Path(directory or f"{project_root}/agents-examples/{name}")
        agent_dir.mkdir(parents=True, exist_ok=True)

        result_schema: dict = {"type": result_type}
        if result_mime_type:
            result_schema["mime_type"] = result_mime_type

        quote_block = QUOTE_BLOCK if has_quote else "\n"

        agent_code = AGENT_TEMPLATE.format(
            args_schema=json.dumps(args_schema, indent=4),
            result_schema=json.dumps(result_schema),
            result_type=result_type,
            quote_block=quote_block,
        )
        (agent_dir / "agent.py").write_text(agent_code)
        desc_escaped = description.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        desc_line = f'"{desc_escaped}"' if ("\n" in description or '"' in description) else description
        (agent_dir / ".env.example").write_text(ENV_EXAMPLE_TEMPLATE.format(
            capability=capability,
            name=name,
            description_escaped=desc_line,
            price=price,
            has_quote=str(has_quote).lower(),
        ))
        (agent_dir / "requirements.txt").write_text(REQUIREMENTS_TEMPLATE)

        return {
            "path": str(agent_dir),
            "files": ["agent.py", ".env.example", "requirements.txt"],
        }

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

    @mcp.tool()
    async def validate_agent(agent_dir: str) -> dict:
        """Full validation of agent before deployment.

        Checks .env completeness and runs describe mode via AGENT_COMMAND.
        See catallaxy://guide/gotchas if describe mode fails unexpectedly.
        """
        agent_path = Path(agent_dir)
        checks = []
        warnings = []

        def chk(name: str, passed: bool) -> bool:
            checks.append({"name": name, "passed": passed})
            return passed

        chk("agent.py exists", (agent_path / "agent.py").exists())
        env_exists = chk(".env exists", (agent_path / ".env").exists())

        required_vars = [
            "AGENT_COMMAND", "AGENT_CAPABILITY", "AGENT_NAME", "AGENT_DESCRIPTION",
            "AGENT_PRICE", "AGENT_ENDPOINT", "AGENT_WALLET_PK", "REGISTRY_ADDRESS",
            "SIDECAR_STATE_PATH", "SIDECAR_TX_DB_PATH", "AGENT_HAS_QUOTE",
        ]
        env_values: dict[str, str] = {}
        if env_exists:
            env_text = (agent_path / ".env").read_text()
            for line in env_text.splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env_values[k.strip()] = v.strip()

        for var in required_vars:
            chk(f"{var} is set", bool(env_values.get(var)))

        # describe mode — uses AGENT_COMMAND from .env via run_agent
        code, stdout, stderr = await run_agent(agent_dir, {"mode": "describe"}, timeout=10)
        describe_ok = False
        if code == 0:
            try:
                desc = json.loads(stdout)
                describe_ok = isinstance(desc.get("args_schema"), dict)
            except Exception:
                pass
        else:
            warnings.append(f"describe mode stderr: {stderr.strip()[:200]}")
        chk("describe mode works", describe_ok)

        # price positive — for has_quote=true, 0 is acceptable (dynamic pricing)
        price_str = env_values.get("AGENT_PRICE", "0")
        has_quote = env_values.get("AGENT_HAS_QUOTE", "false").lower() == "true"
        try:
            price_val = int(price_str)
            chk("AGENT_PRICE is positive", price_val > 0 or has_quote)
        except ValueError:
            chk("AGENT_PRICE is positive", False)

        # endpoint valid URL
        endpoint = env_values.get("AGENT_ENDPOINT", "")
        chk("AGENT_ENDPOINT is valid URL", endpoint.startswith("http://") or endpoint.startswith("https://"))
        if endpoint.startswith("http://"):
            warnings.append("AGENT_ENDPOINT uses HTTP, consider HTTPS for production")

        if env_values.get("TESTNET", "false").lower() == "true":
            warnings.append("TESTNET=true — make sure this is intentional for production")

        all_passed = all(c["passed"] for c in checks)
        return {"valid": all_passed, "checks": checks, "warnings": warnings}

    @mcp.tool()
    def deploy_agent(agent_dir: str, env_file: str | None = None) -> dict:
        """Install and start agent sidecar via systemd.

        Calls: sidecar.py service --name <name> install --workdir <workdir> --env-file <env>
        """
        project_root = os.getenv("CATALLAXY_PROJECT_ROOT", "/media/second_disk/cont5")
        env_path = str(Path(env_file or str(Path(agent_dir) / ".env")).resolve())

        env_values: dict[str, str] = {}
        for line in Path(env_path).read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env_values[k.strip()] = v.strip()

        agent_name = env_values.get("AGENT_NAME", Path(agent_dir).name).lower().replace(" ", "-")
        service_name = f"catallaxy-{agent_name}"
        sidecar_py = str(Path(project_root) / "sidecar" / "sidecar.py")
        python_bin = str(Path(project_root) / ".venv" / "bin" / "python")

        cmd = [
            python_bin, sidecar_py,
            "service", "--name", service_name,
            "install",
            "--workdir", str(Path(agent_dir).resolve()),
            "--env-file", env_path,
            "--sidecar-path", sidecar_py,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
        if result.returncode != 0:
            raise RuntimeError(f"Deploy failed: {result.stderr or result.stdout}")

        return {
            "service_name": service_name,
            "status": "active",
            "command": f"{python_bin} {sidecar_py} run --env-file {env_path}",
        }

    @mcp.tool()
    def agent_status(service_name: str) -> dict:
        """Get systemd service status for a deployed agent."""
        result = subprocess.run(
            ["systemctl", "show", service_name, "--property=ActiveState,SubState,ActiveEnterTimestamp"],
            capture_output=True, text=True,
        )
        props: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                props[k] = v

        active = props.get("ActiveState") == "active"
        sub = props.get("SubState", "")
        ts = props.get("ActiveEnterTimestamp", "")

        return {"active": active, "sub_state": sub, "active_since": ts}

    @mcp.tool()
    def agent_logs(service_name: str, lines: int = 50) -> dict:
        """Get recent logs for a deployed agent."""
        result = subprocess.run(
            ["journalctl", "-u", service_name, "-n", str(lines), "--no-pager"],
            capture_output=True, text=True,
        )
        log_lines = result.stdout.splitlines()
        return {"lines": log_lines}

    @mcp.tool()
    def stop_agent(service_name: str) -> dict:
        """Stop a deployed agent service."""
        result = subprocess.run(
            ["systemctl", "stop", service_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Stop failed: {result.stderr}")
        return {"stopped": True}
