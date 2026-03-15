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
from storage import StateStore, TonStorageClient, parse_storage_expiry, should_extend_storage
from settings import Settings, load_settings

logger = logging.getLogger("sidecar")

async def handle_storage_status(settings: Settings) -> int:
    state_store = StateStore(settings.state_path)
    storage = TonStorageClient(settings.ton_storage_base_url, settings.ton_storage_session)
    try:
        state = state_store.load()
        if not state.bag_id:
            print(json.dumps({"bag_id": None, "status": "missing"}, ensure_ascii=False))
            return 1

        details = await storage.get_details(state.bag_id)
        expires_at = parse_storage_expiry(details)
        if expires_at:
            state.storage_expires = expires_at
            state_store.save(state)

        print(
            json.dumps(
                {
                    "bag_id": state.bag_id,
                    "expires_at": expires_at,
                    "should_extend": should_extend_storage(
                        expires_at,
                        threshold_days=settings.storage_extend_threshold_days,
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        await storage.close()


async def handle_extend_storage(settings: Settings) -> int:
    state_store = StateStore(settings.state_path)
    storage = TonStorageClient(settings.ton_storage_base_url, settings.ton_storage_session)
    try:
        state = state_store.load()
        if not state.bag_id:
            print("No bag_id in state")
            return 1

        response = await storage.extend_storage(state.bag_id)
        print(json.dumps(response, ensure_ascii=False))
        return 0
    finally:
        await storage.close()


async def handle_update_docs(settings: Settings) -> int:
    if not settings.ton_storage_session:
        print("TON_STORAGE_SESSION is required for docs upload")
        return 1

    docs_payload = generate_docs(settings)
    write_docs_file(settings.docs_path, docs_payload)

    state_store = StateStore(settings.state_path)
    storage = TonStorageClient(settings.ton_storage_base_url, settings.ton_storage_session)
    try:
        bag_id = await storage.upload_docs(settings.docs_path, description=settings.agent_name)
        state = state_store.load()
        state.bag_id = bag_id
        state_store.save(state)
        print(json.dumps({"bag_id": bag_id}, ensure_ascii=False))
        return 0
    finally:
        await storage.close()


async def handle_stop_storage(settings: Settings) -> int:
    state_store = StateStore(settings.state_path)
    storage = TonStorageClient(settings.ton_storage_base_url, settings.ton_storage_session)
    try:
        state = state_store.load()
        if not state.bag_id:
            print("No bag_id in state")
            return 1

        await storage.stop_storage(state.bag_id)
        state.bag_id = None
        state.storage_expires = None
        state_store.save(state)
        print(json.dumps({"stopped": True}, ensure_ascii=False))
        return 0
    finally:
        await storage.close()


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
    python_bin = str(Path(args.python_bin or sys.executable).resolve())
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

    print(json.dumps({"uninstalled": True, "service": f"{service_name}.service"}, ensure_ascii=False))
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

    try:
        load_settings(args.env_file)
        checks["settings"] = "ok"
    except Exception as exc:
        checks["settings"] = f"error: {exc}"

    print(json.dumps(checks, ensure_ascii=False))
    return 0 if checks["env_exists"] and checks["settings"] == "ok" else 1


def parse_cli_args() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser], argparse.Namespace]:
    parser = argparse.ArgumentParser(description="TON Agent Marketplace sidecar CLI")
    subparsers = parser.add_subparsers(dest="command")
    parser_map: dict[str, argparse.ArgumentParser] = {}

    run_parser = subparsers.add_parser("run", help="Run sidecar HTTP server")
    run_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser_map["run"] = run_parser

    storage_parser = subparsers.add_parser("storage", help="TON Storage operations")
    storage_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    storage_sub = storage_parser.add_subparsers(dest="storage_command", required=True)
    storage_sub.add_parser("status", help="Show storage status")
    storage_sub.add_parser("extend", help="Extend storage duration")
    storage_sub.add_parser("update-docs", help="Re-upload docs and update bag_id")
    storage_sub.add_parser("stop", help="Stop storage for current bag")
    parser_map["storage"] = storage_parser

    service_parser = subparsers.add_parser("service", help="Manage systemd service")
    service_parser.add_argument("--name", default="sidecar", help="Service name without .service")
    service_sub = service_parser.add_subparsers(dest="service_command", required=True)

    install_parser = service_sub.add_parser("install", help="Install + enable + start systemd service")
    install_parser.add_argument("--workdir", default=str(Path.cwd()), help="Working directory for service")
    install_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    install_parser.add_argument("--python-bin", default=sys.executable, help="Python executable path")
    install_parser.add_argument("--sidecar-path", default=__file__, help="Path to sidecar.py")

    service_sub.add_parser("uninstall", help="Disable and remove systemd service")
    service_sub.add_parser("start", help="Start service")
    service_sub.add_parser("stop", help="Stop service")
    service_sub.add_parser("restart", help="Restart service")
    service_sub.add_parser("status", help="Show service status")
    logs_parser = service_sub.add_parser("logs", help="Show service logs")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow logs")
    logs_parser.add_argument("--lines", type=int, default=200, help="Number of lines")
    parser_map["service"] = service_parser

    doctor_parser = subparsers.add_parser("doctor", help="Validate local sidecar setup")
    doctor_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser_map["doctor"] = doctor_parser

    help_parser = subparsers.add_parser("help", help="Show help")
    help_parser.add_argument("topic", nargs="?", choices=["run", "storage", "service", "doctor"], help="Help topic")
    parser_map["help"] = help_parser

    args = parser.parse_args()
    return parser, parser_map, args


async def async_main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

    parser, parser_map, args = parse_cli_args()

    if args.command in {None, "run"}:
        env_file = getattr(args, "env_file", ".env")
        settings = load_settings(env_file)
        return await run_server(settings)

    if args.command == "storage":
        settings = load_settings(args.env_file)
        if args.storage_command == "status":
            return await handle_storage_status(settings)
        if args.storage_command == "extend":
            return await handle_extend_storage(settings)
        if args.storage_command == "update-docs":
            return await handle_update_docs(settings)
        if args.storage_command == "stop":
            return await handle_stop_storage(settings)
        print("Unknown storage command")
        return 1

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
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
