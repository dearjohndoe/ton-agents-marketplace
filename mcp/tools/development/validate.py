import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from lib.agent_runner import run_agent


def _skus_have_pricing(raw: str, has_quote: bool) -> bool:
    """Sanity-check AGENT_SKUS: every SKU must declare ton/usd; positive price required unless has_quote."""
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 3:
            return False
        positive_seen = False
        rail_seen = False
        for tok in parts[2:]:
            tok = tok.strip()
            if "=" not in tok:
                continue
            key, _, val = tok.partition("=")
            if key.strip().lower() not in {"ton", "usd"}:
                continue
            rail_seen = True
            try:
                if int(val) > 0:
                    positive_seen = True
            except ValueError:
                return False
        if not rail_seen:
            return False
        if not positive_seen and not has_quote:
            return False
    return True


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
            "AGENT_ENDPOINT", "AGENT_WALLET_PK", "REGISTRY_ADDRESS",
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

        # AGENT_SKUS is the modern config; AGENT_PRICE/AGENT_PRICE_USD work as legacy fallback.
        has_skus = bool(env_values.get("AGENT_SKUS"))
        has_legacy_price = bool(env_values.get("AGENT_PRICE")) or bool(env_values.get("AGENT_PRICE_USD"))
        chk("AGENT_SKUS or AGENT_PRICE/AGENT_PRICE_USD is set", has_skus or has_legacy_price)
        if has_legacy_price and not has_skus:
            warnings.append("Using legacy AGENT_PRICE/AGENT_PRICE_USD — prefer AGENT_SKUS for new agents")

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

        # Pricing sanity — at least one rail must have a non-zero price unless has_quote/dynamic.
        has_quote = env_values.get("AGENT_HAS_QUOTE", "false").lower() == "true"
        if has_skus:
            chk("AGENT_SKUS pricing valid", _skus_have_pricing(env_values["AGENT_SKUS"], has_quote))
        else:
            try:
                ton_val = int(env_values.get("AGENT_PRICE", "0") or "0")
                usd_val = int(env_values.get("AGENT_PRICE_USD", "0") or "0")
                chk("price is positive (or has_quote=true)", ton_val > 0 or usd_val > 0 or has_quote)
            except ValueError:
                chk("price is positive (or has_quote=true)", False)

        # endpoint valid URL
        endpoint = env_values.get("AGENT_ENDPOINT", "")
        chk("AGENT_ENDPOINT is valid URL", endpoint.startswith("http://") or endpoint.startswith("https://"))
        if endpoint.startswith("http://"):
            warnings.append("AGENT_ENDPOINT uses HTTP, consider HTTPS for production")

        if env_values.get("TESTNET", "false").lower() == "true":
            warnings.append("TESTNET=true — make sure this is intentional for production")

        all_passed = all(c["passed"] for c in checks)
        return {"valid": all_passed, "checks": checks, "warnings": warnings}
