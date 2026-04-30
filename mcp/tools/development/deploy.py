import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:

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
