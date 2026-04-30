import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from lib.agent_runner import run_agent


def register(mcp: FastMCP) -> None:

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
