from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from api import SidecarApp
from settings import Settings, load_settings

logger = logging.getLogger("sidecar")


async def run_server(settings: Settings) -> int:
    from aiohttp import web

    app = SidecarApp(settings).build_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)

    logger.info("Starting sidecar on port %s", settings.port)
    await site.start()

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        logger.info("Stopping sidecar")
    finally:
        await runner.cleanup()
    return 0


def _run_command(command: list[str]) -> int:
    return subprocess.run(command, check=False).returncode


def _systemctl_command(name: str, *args: str) -> list[str]:
    return ["systemctl", *args, f"{name}.service"]


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


def handle_service_install(args: argparse.Namespace) -> int:
    service_name = args.name
    workdir = str(Path(args.workdir).resolve())
    env_file = str(Path(args.env_file).resolve())
    python_bin = str(Path(sys.executable).absolute())
    sidecar_path = str(Path(args.sidecar_path).resolve())
    unit_path = Path(f"/etc/systemd/system/{service_name}.service")

    if not Path(env_file).exists():
        print(f"Env file not found: {env_file}")
        return 1

    unit_content = render_systemd_unit(service_name, workdir, env_file, python_bin, sidecar_path)

    try:
        unit_path.write_text(unit_content, encoding="utf-8")
    except PermissionError:
        print(f"Permission denied writing {unit_path}. Run command with sudo.")
        return 1

    if _run_command(["systemctl", "daemon-reload"]) != 0:
        return 1
    if _run_command(["systemctl", "enable", "--now", f"{service_name}.service"]) != 0:
        return 1

    print(json.dumps({"installed": True, "service": f"{service_name}.service"}, ensure_ascii=False))
    return 0


def handle_service_uninstall(args: argparse.Namespace) -> int:
    service_name = args.name
    unit_path = Path(f"/etc/systemd/system/{service_name}.service")

    _run_command(_systemctl_command(service_name, "stop"))
    _run_command(_systemctl_command(service_name, "disable"))

    try:
        if unit_path.exists():
            unit_path.unlink()
    except PermissionError:
        print(f"Permission denied deleting {unit_path}. Run command with sudo.")
        return 1

    if _run_command(["systemctl", "daemon-reload"]) != 0:
        return 1

    removed_files = []
    if getattr(args, "env_file", None):
        try:
            settings = load_settings(args.env_file)
            for path in [settings.state_path, settings.tx_db_path]:
                p = Path(path)
                if p.exists():
                    p.unlink()
                    removed_files.append(str(p))
        except Exception as exc:
            print(f"Warning: could not clean up state files: {exc}")

    print(json.dumps({"uninstalled": True, "service": f"{service_name}.service", "removed_files": removed_files}, ensure_ascii=False))
    return 0


def handle_service_command(args: argparse.Namespace) -> int:
    if args.service_command == "install":
        return handle_service_install(args)
    if args.service_command == "uninstall":
        return handle_service_uninstall(args)
    if args.service_command == "logs":
        cmd = ["journalctl", "-u", f"{args.name}.service", "-n", str(args.lines)]
        if args.follow:
            cmd.append("-f")
        return _run_command(cmd)

    if args.service_command == "restart" and getattr(args, "force_heartbeat", False):
        try:
            settings = load_settings(args.env_file)
            from storage import StateStore
            store = StateStore(settings.state_path)
            state = store.load()
            state.last_heartbeat = None
            store.save(state)
            logger.info("Cleared last_heartbeat — fresh heartbeat will be sent after restart")
        except Exception as exc:
            print(f"Warning: could not clear heartbeat state: {exc}")

    mapping = {
        "start": "start",
        "stop": "stop",
        "restart": "restart",
        "status": "status",
    }
    action = mapping.get(args.service_command)
    if action is None:
        print("Unknown service command")
        return 1
    return _run_command(_systemctl_command(args.name, action))


def handle_doctor(args: argparse.Namespace) -> int:
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "systemctl": shutil.which("systemctl") is not None,
        "env_file": str(Path(args.env_file).resolve()),
        "env_exists": Path(args.env_file).exists(),
    }

    settings = None
    try:
        settings = load_settings(args.env_file)
        checks["settings"] = "ok"
    except Exception as exc:
        checks["settings"] = f"error: {exc}"

    if settings is not None:
        try:
            from jobs import _SENSITIVE_ENV_KEYS
            env_vars = {k: v for k, v in os.environ.items() if k not in _SENSITIVE_ENV_KEYS}
            env_vars["SIDECAR_PYTHON"] = sys.executable
            result = subprocess.run(
                settings.agent_command,
                shell=True,
                input=json.dumps({"mode": "describe"}).encode(),
                capture_output=True,
                timeout=10,
                env=env_vars,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                checks["describe_mode"] = f"error (exit {result.returncode}): {stderr}"
            else:
                try:
                    parsed = json.loads(result.stdout)
                    schema = parsed.get("args_schema", parsed)
                    checks["describe_mode"] = f"ok, fields: {list(schema.keys())}"
                except Exception:
                    checks["describe_mode"] = "error: invalid JSON from agent"
        except subprocess.TimeoutExpired:
            checks["describe_mode"] = "error: timed out after 10s"
        except Exception as exc:
            checks["describe_mode"] = f"error: {exc}"

    print(json.dumps(checks, ensure_ascii=False))
    ok = checks["env_exists"] and checks["settings"] == "ok" and str(checks.get("describe_mode", "")).startswith("ok")
    return 0 if ok else 1


def parse_cli_args() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser], argparse.Namespace]:
    parser = argparse.ArgumentParser(description="TON Agent Marketplace sidecar CLI")
    subparsers = parser.add_subparsers(dest="command")
    parser_map: dict[str, argparse.ArgumentParser] = {}

    run_parser = subparsers.add_parser("run", help="Run sidecar HTTP server")
    run_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    run_parser.add_argument("--force-heartbeat", action="store_true",
                            help="Clear last_heartbeat state so a fresh heartbeat is sent on startup")
    parser_map["run"] = run_parser

    service_parser = subparsers.add_parser("service", help="Manage systemd service")
    service_parser.add_argument("--name", default="sidecar", help="Service name without .service")
    service_sub = service_parser.add_subparsers(dest="service_command", required=True)

    install_parser = service_sub.add_parser("install", help="Install + enable + start systemd service")
    install_parser.add_argument("--workdir", default=str(Path.cwd()), help="Working directory for service")
    install_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    install_parser.add_argument("--sidecar-path", default=__file__, help="Path to sidecar.py")

    uninstall_parser = service_sub.add_parser("uninstall", help="Disable and remove systemd service")
    uninstall_parser.add_argument("--env-file", default=None, help="Path to .env file to clean up state files")
    service_sub.add_parser("start", help="Start service")
    service_sub.add_parser("stop", help="Stop service")
    restart_parser = service_sub.add_parser("restart", help="Restart service")
    restart_parser.add_argument("--force-heartbeat", action="store_true",
                                help="Clear last_heartbeat state so a fresh heartbeat is sent after restart")
    restart_parser.add_argument("--env-file", default=".env", help="Path to .env file (needed for --force-heartbeat)")
    service_sub.add_parser("status", help="Show service status")
    logs_parser = service_sub.add_parser("logs", help="Show service logs")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow logs")
    logs_parser.add_argument("--lines", type=int, default=200, help="Number of lines")
    parser_map["service"] = service_parser

    doctor_parser = subparsers.add_parser("doctor", help="Validate local sidecar setup")
    doctor_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser_map["doctor"] = doctor_parser

    help_parser = subparsers.add_parser("help", help="Show help")
    help_parser.add_argument("topic", nargs="?", choices=["run", "service", "doctor"], help="Help topic")
    parser_map["help"] = help_parser

    args = parser.parse_args()
    return parser, parser_map, args


async def async_main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

    parser, parser_map, args = parse_cli_args()

    if args.command in {None, "run"}:
        env_file = getattr(args, "env_file", ".env")
        settings = load_settings(env_file)
        if getattr(args, "force_heartbeat", False):
            from storage import StateStore
            store = StateStore(settings.state_path)
            state = store.load()
            state.last_heartbeat = None
            store.save(state)
            logger.info("Cleared last_heartbeat — fresh heartbeat will be sent on startup")
        return await run_server(settings)

    if args.command == "service":
        return handle_service_command(args)

    if args.command == "doctor":
        return handle_doctor(args)

    if args.command == "help":
        if args.topic:
            parser_map[args.topic].print_help()
        else:
            parser.print_help()
        return 0

    parser.print_help()
    return 1


def main() -> None:
    try:
        raise SystemExit(asyncio.run(async_main()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
