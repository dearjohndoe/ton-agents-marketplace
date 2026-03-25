"""Agent subprocess runner — thin wrapper around sidecar/jobs.py."""
import os
import sys

# Add sidecar to path so we can import jobs.py
_SIDECAR = os.path.join(os.path.dirname(__file__), "..", "..", "sidecar")
if _SIDECAR not in sys.path:
    sys.path.insert(0, _SIDECAR)

from jobs import run_agent_subprocess  # noqa: E402


async def run_agent(agent_dir: str, stdin_data: dict, timeout: int = 30) -> tuple[int, str, str]:
    """Run agent.py with JSON stdin. Returns (exit_code, stdout, stderr).

    Uses create_subprocess_shell (same as sidecar) so SIDECAR_PYTHON expands correctly.
    """
    import asyncio
    import json

    command = f"python {os.path.join(agent_dir, 'agent.py')}"
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
