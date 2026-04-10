"""Agent subprocess runner — thin wrapper around sidecar/jobs.py."""
import os
import sys

# Add sidecar to path so we can import jobs.py
_SIDECAR = os.path.join(os.path.dirname(__file__), "..", "..", "sidecar")
if _SIDECAR not in sys.path:
    sys.path.insert(0, _SIDECAR)

from jobs import run_agent_subprocess  # noqa: E402


def _resolve_command(agent_dir: str) -> str:
    """Read AGENT_COMMAND from agent's .env and resolve $SIDECAR_PYTHON.

    Falls back to `sys.executable agent.py` if .env is missing or
    AGENT_COMMAND is not set.
    """
    env_path = os.path.join(agent_dir, ".env")
    command: str | None = None

    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "AGENT_COMMAND":
                    command = v.strip()
                    break

    if not command:
        command = f"$SIDECAR_PYTHON {os.path.join(agent_dir, 'agent.py')}"

    # $SIDECAR_PYTHON → the interpreter that launched the sidecar/MCP server
    command = command.replace("$SIDECAR_PYTHON", sys.executable)

    # If the script arg is relative (e.g. "agent.py"), resolve against agent_dir
    parts = command.split(None, 1)
    if len(parts) == 2 and not os.path.isabs(parts[1]):
        command = f"{parts[0]} {os.path.join(agent_dir, parts[1])}"

    return command


async def run_agent(agent_dir: str, stdin_data: dict, timeout: int = 30) -> tuple[int, str, str]:
    """Run agent with JSON stdin. Returns (exit_code, stdout, stderr).

    Resolves AGENT_COMMAND from the agent's .env and substitutes
    $SIDECAR_PYTHON with sys.executable — same Python that runs the sidecar.
    """
    import asyncio
    import json

    command = _resolve_command(agent_dir)
    stdin_bytes = json.dumps(stdin_data).encode()

    proc = await asyncio.create_subprocess_shell(
        command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=agent_dir,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_bytes), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return -1, "", "Timeout"
    return (proc.returncode or 0), stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")
