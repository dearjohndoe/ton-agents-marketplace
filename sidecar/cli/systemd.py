from __future__ import annotations


def render_systemd_unit(service_name: str, workdir: str, env_file: str, python_bin: str, sidecar_path: str) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description=TON Sidecar ({service_name})",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={workdir}",
            f"EnvironmentFile={env_file}",
            f"ExecStart={python_bin} {sidecar_path} run --env-file {env_file}",
            "Restart=always",
            "RestartSec=3",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )
