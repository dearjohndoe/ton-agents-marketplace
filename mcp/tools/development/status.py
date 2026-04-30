import subprocess

from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:

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
