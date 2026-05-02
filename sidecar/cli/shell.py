from __future__ import annotations

import subprocess
import sys


def _run_command(command: list[str]) -> int:
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        print(f"Command failed (rc={result.returncode}): {' '.join(command)}", file=sys.stderr)
    return result.returncode


def _systemctl_command(name: str, *args: str) -> list[str]:
    return ["systemctl", *args, f"{name}.service"]
