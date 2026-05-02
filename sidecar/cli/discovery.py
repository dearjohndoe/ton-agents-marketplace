from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .template import _CTLX_SUFFIX


def _normalize_service_name(name: str) -> str:
    if not name.endswith(_CTLX_SUFFIX):
        return f"{name}{_CTLX_SUFFIX}"
    return name


def _discover_sidecar_agents() -> list[str]:
    """Scan /etc/systemd/system/ for installed sidecar agent services."""
    systemd_dir = Path("/etc/systemd/system")
    agents: list[str] = []
    if not systemd_dir.exists():
        return agents
    for f in sorted(systemd_dir.glob("*.service")):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            if "TON Sidecar" in content:
                agents.append(f.stem)
        except OSError:
            pass
    return agents


def _resolve_service_name(args: argparse.Namespace, *, for_install: bool = False) -> str | None:
    """Return normalized service name; prompt user if --name not specified."""
    name: str | None = getattr(args, "name", None)

    if for_install:
        if not name:
            if not sys.stdin.isatty():
                print("--name required for install")
                return None
            name = input("Agent short name (will become <name>-ctlx-agent): ").strip()
            if not name:
                print("Name cannot be empty")
                return None
        return _normalize_service_name(name)

    if name:
        return name

    agents = _discover_sidecar_agents()
    if not agents:
        print("No sidecar agents found in /etc/systemd/system/. Use --name to specify.")
        return None
    if len(agents) == 1:
        print(f"Using agent: {agents[0]}")
        return agents[0]

    if not sys.stdin.isatty():
        print("Multiple sidecar agents found. Use --name to specify one:")
        for a in agents:
            print(f"  {a}")
        return None

    print("Installed sidecar agents:")
    for i, a in enumerate(agents, 1):
        print(f"  {i}) {a}")
    while True:
        try:
            choice = input("Select number: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(agents):
                return agents[idx]
            print(f"Enter 1–{len(agents)}")
        except (ValueError, EOFError, KeyboardInterrupt):
            return None
