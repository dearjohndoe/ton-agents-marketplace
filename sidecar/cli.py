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

# ── constants ─────────────────────────────────────────────────────────────────

_REGISTRY_ADDRESS = "UQCYxSFNCJHmBxVpgfqAesgjLQDsLch3WJG3MJYyhnBDS7gg"
_CTLX_SUFFIX = "-ctlx-agent"
_CAPABILITIES = ["translate", "summarize", "analyze", "generate", "classify", "qa", "code"]

_AGENT_TEMPLATE = '''\
import json
import sys


def describe() -> dict:
    # Return the schema of arguments your agent accepts.
    # Used for marketplace UI and request validation.
    return {
        "args_schema": {
            "text": {"type": "string", "description": "Input text", "required": True},
        }
    }


def run(body: dict) -> dict:
    # TODO: implement your agent logic here.
    # body contains the fields declared in describe().
    text = body.get("text", "")
    return {"result": f"echo: {text}"}


if __name__ == "__main__":
    request = json.loads(sys.stdin.read())
    if request.get("mode") == "describe":
        print(json.dumps(describe()))
    else:
        print(json.dumps(run(request.get("body", {}))))
'''

# ── service name helpers ──────────────────────────────────────────────────────

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


# ── server ────────────────────────────────────────────────────────────────────

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


# ── systemd helpers ───────────────────────────────────────────────────────────

def _run_command(command: list[str]) -> int:
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        print(f"Command failed (rc={result.returncode}): {' '.join(command)}", file=sys.stderr)
    return result.returncode


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


# ── service commands ──────────────────────────────────────────────────────────

def handle_service_install(args: argparse.Namespace) -> int:
    service_name = _resolve_service_name(args, for_install=True)
    if service_name is None:
        return 1

    workdir = str(Path(args.workdir).resolve())
    env_file = str(Path(args.env_file).resolve())
    python_bin = str(Path(sys.executable).absolute())
    sidecar_path = str(Path(args.sidecar_path).resolve())
    unit_path = Path(f"/etc/systemd/system/{service_name}.service")

    env_path = Path(env_file)
    if not env_path.exists():
        print(f"Env file not found: {env_file}")
        return 1

    try:
        env_path.chmod(0o600)
    except OSError as exc:
        print(f"Warning: could not set secure permissions on {env_file}: {exc}")

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
    service_name = _resolve_service_name(args)
    if service_name is None:
        return 1

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

    service_name = _resolve_service_name(args)
    if service_name is None:
        return 1

    if args.service_command == "logs":
        cmd = ["journalctl", "-u", f"{service_name}.service", "-n", str(args.lines)]
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

    mapping = {"start": "start", "stop": "stop", "restart": "restart", "status": "status"}
    action = mapping.get(args.service_command)
    if action is None:
        print("Unknown service command")
        return 1
    return _run_command(_systemctl_command(service_name, action))


# ── doctor ────────────────────────────────────────────────────────────────────

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
            env_vars = os.environ.copy()
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


# ── stock ─────────────────────────────────────────────────────────────────────

async def handle_stock_command(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    from stock import StockStore
    store = StockStore(settings.stock_db_path)
    await store.init(settings.skus)
    try:
        if args.stock_command == "show":
            views = await store.list_views()
            rows = []
            for v in views:
                rows.append({
                    "sku": v.sku_id,
                    "title": v.title,
                    "price_ton": v.price_ton,
                    "price_usd": v.price_usd,
                    "total": v.total,
                    "sold": v.sold,
                    "reserved": v.reserved,
                    "stock_left": v.stock_left,
                })
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0

        if args.stock_command == "set":
            total: int | None
            raw = args.total.strip().lower()
            if raw in {"none", "infinite", "inf"}:
                total = None
            else:
                try:
                    total = int(raw)
                except ValueError:
                    print(f"Invalid total value: {args.total}")
                    return 1
                if total < 0:
                    print("total must be >= 0")
                    return 1
            await store.set_total(args.sku, total, reason="cli_set")
            view = await store.get_view(args.sku)
            print(json.dumps({"sku": view.sku_id, "total": view.total, "sold": view.sold, "stock_left": view.stock_left}, ensure_ascii=False))
            return 0

        if args.stock_command == "add":
            try:
                delta = int(args.delta)
            except ValueError:
                print(f"Invalid delta value: {args.delta}")
                return 1
            new_total = await store.adjust_total(args.sku, delta, reason="cli_add")
            view = await store.get_view(args.sku)
            print(json.dumps({"sku": view.sku_id, "total": new_total, "sold": view.sold, "stock_left": view.stock_left}, ensure_ascii=False))
            return 0

        print("Unknown stock command")
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        await store.close()


# ── init ──────────────────────────────────────────────────────────────────────

def _generate_wallet_keypair() -> tuple[str, str, str]:
    """Returns (pk_hex, seed_phrase_or_empty, wallet_address)."""
    try:
        from pytoniq_core.crypto.keys import mnemonic_new, mnemonic_to_private_key
        words = mnemonic_new(24)
        _, priv_bytes = mnemonic_to_private_key(words)
        pk_hex = bytes(priv_bytes).hex()
        seed = " ".join(words)
    except ImportError:
        import secrets
        pk_hex = secrets.token_bytes(32).hex()
        seed = ""

    from settings import _derive_wallet_address
    address = _derive_wallet_address(pk_hex, False)
    return pk_hex, seed, address


def handle_init(args: argparse.Namespace, _prefill: dict[str, str] | None = None) -> int:
    output = getattr(args, "output", ".env")
    prefill = _prefill or {}
    directory = Path(getattr(args, "directory", "."))

    print("=== sidecar init ===\n")

    agent_name = input("Agent name (AGENT_NAME): ").strip()
    if not agent_name:
        print("Name is required")
        return 1

    print("Description (AGENT_DESCRIPTION, Ctrl+D when done):")
    desc_lines: list[str] = []
    try:
        while True:
            desc_lines.append(input(""))
    except EOFError:
        pass
    agent_description = "\n".join(desc_lines).strip()

    if "capability" in prefill:
        capability = prefill["capability"]
        print(f"Capability: {capability}")
    else:
        print("\nCapability:")
        for i, c in enumerate(_CAPABILITIES, 1):
            print(f"  {i}) {c}")
        cap_raw = input("Number or custom value: ").strip()
        try:
            capability = _CAPABILITIES[int(cap_raw) - 1]
        except (ValueError, IndexError):
            capability = cap_raw
    if not capability:
        print("Capability is required")
        return 1

    price_str = input("\nPrice in TON (e.g. 0.01, leave blank to skip): ").strip()
    price_nanoton: int | None = None
    if price_str:
        try:
            price_nanoton = int(float(price_str) * 1_000_000_000)
            if price_nanoton <= 0:
                raise ValueError
        except ValueError:
            print(f"Invalid price: {price_str!r}")
            return 1

    usd_prompt = "Price in USDT (e.g. 1.0, leave blank to skip): " if price_nanoton is not None \
        else "Price in USDT (e.g. 1.0, required — TON price was skipped): "
    usd_str = input(usd_prompt).strip()
    price_usdt: int | None = None
    if usd_str:
        try:
            price_usdt = int(float(usd_str) * 1_000_000)
            if price_usdt <= 0:
                raise ValueError
        except ValueError:
            print(f"Invalid USDT price: {usd_str!r}")
            return 1
    elif price_nanoton is None:
        print("At least one price rail is required. Enter TON or USDT price.")
        return 1

    endpoint = input("Endpoint URL (e.g. https://my-agent.com): ").strip()
    if not endpoint:
        print("Endpoint is required")
        return 1

    agent_command = input(f"Agent command [$SIDECAR_PYTHON {directory}/agent.py]: ").strip() or f"$SIDECAR_PYTHON {directory}/agent.py"

    print("\nWallet private key:")
    print("  1) Enter existing hex key")
    print("  2) Generate new keypair")
    pk_choice = input("Choice [1/2]: ").strip()

    wallet_pk = ""
    wallet_seed = ""
    wallet_address = ""

    if pk_choice == "2":
        wallet_pk, wallet_seed, wallet_address = _generate_wallet_keypair()
        print(f"\nNew wallet generated!")
        print(f"  Address: {wallet_address}")
        if wallet_seed:
            print(f"  Seed:    {wallet_seed}")
            print("  SAVE THE SEED PHRASE in a safe place!\n")
        else:
            print("  (pytoniq_core not installed — no seed phrase; save the private key!)\n")
    else:
        wallet_pk = input("AGENT_WALLET_PK (hex): ").strip()
        if not wallet_pk:
            print("Private key is required")
            return 1
        try:
            from settings import _derive_wallet_address
            wallet_address = _derive_wallet_address(wallet_pk, False)
            print(f"  Wallet address: {wallet_address}")
        except Exception as exc:
            print(f"  Warning: could not derive wallet address: {exc}")

    if "\n" in agent_description:
        _desc_escaped = agent_description.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        _desc_line = f'AGENT_DESCRIPTION="{_desc_escaped}"'
    else:
        _desc_line = f"AGENT_DESCRIPTION={agent_description}"

    lines = [
        f"AGENT_NAME={agent_name}",
        _desc_line,
        f"AGENT_CAPABILITY={capability}",
        f"AGENT_ENDPOINT={endpoint}",
        f"AGENT_COMMAND={agent_command}",
        f"AGENT_WALLET_PK={wallet_pk}",
        f"AGENT_WALLET_SEED={wallet_seed}",
        f"REGISTRY_ADDRESS={_REGISTRY_ADDRESS}",
        "",
        "PORT=8080",
        "TESTNET=false",
    ]
    insert_at = 4
    if price_nanoton is not None:
        lines.insert(insert_at, f"AGENT_PRICE={price_nanoton}")
        insert_at += 1
    if price_usdt is not None:
        lines.insert(insert_at, f"AGENT_PRICE_USD={price_usdt}")

    out_path = Path(output)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_path.chmod(0o600)

    print(f"\n.env written to {out_path}")
    if wallet_address:
        print(f"Wallet address: {wallet_address}")
        print("Fund the wallet with TON before starting the agent!")

    return 0


# ── scaffold ──────────────────────────────────────────────────────────────────

def handle_scaffold(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    capability: str = getattr(args, "capability", "") or ""

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Cannot create directory {directory}: {exc}")
        return 1

    agent_py = directory / "agent.py"
    if agent_py.exists():
        print(f"{agent_py} already exists — skipping")
    else:
        agent_py.write_text(_AGENT_TEMPLATE, encoding="utf-8")
        print(f"Created {agent_py}")

    reqs = directory / "requirements.txt"
    if reqs.exists():
        print(f"{reqs} already exists — skipping")
    else:
        reqs.write_text("python-dotenv\n# Add your dependencies below\n", encoding="utf-8")
        print(f"Created {reqs}")

    env_file = directory / ".env"
    if env_file.exists():
        print(f"{env_file} already exists — skipping")
    else:
        print(f"\nCreating {env_file} ...")
        init_args = argparse.Namespace(output=str(env_file))
        prefill = {"capability": capability} if capability else {}
        rc = handle_init(init_args, _prefill=prefill)
        if rc != 0:
            return rc
        slug = directory.name
        with env_file.open("a", encoding="utf-8") as f:
            f.write(f"\nSIDECAR_STATE_PATH=.sidecar_state.{slug}.json\n")
            f.write(f"SIDECAR_TX_DB_PATH=processed_txs.{slug}.db\n")

    print(f"\nScaffold complete! Next steps:")
    print(f"  1. Edit {agent_py}")
    print(f"  2. sudo sidecar service install --name <agent-name> --env-file {env_file}")
    return 0


# ── arg parser ────────────────────────────────────────────────────────────────

def parse_cli_args() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser], argparse.Namespace]:
    parser = argparse.ArgumentParser(description="TON Agent Marketplace sidecar CLI")
    subparsers = parser.add_subparsers(dest="command")
    parser_map: dict[str, argparse.ArgumentParser] = {}

    run_parser = subparsers.add_parser("run", help="Run sidecar HTTP server")
    run_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    run_parser.add_argument("--force-heartbeat", action="store_true",
                            help="Clear last_heartbeat so a fresh heartbeat is sent on startup")
    parser_map["run"] = run_parser

    service_parser = subparsers.add_parser("service", help="Manage systemd service")
    service_parser.add_argument("--name", default=None,
                                help="Service name (without .service suffix); -ctlx-agent appended automatically. "
                                     "If omitted, auto-detected from installed services.")
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
                                help="Clear last_heartbeat after restart")
    restart_parser.add_argument("--env-file", default=".env", help="Path to .env file (needed for --force-heartbeat)")
    service_sub.add_parser("status", help="Show service status")
    logs_parser = service_sub.add_parser("logs", help="Show service logs")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow logs")
    logs_parser.add_argument("--lines", type=int, default=200, help="Number of lines")
    parser_map["service"] = service_parser

    doctor_parser = subparsers.add_parser("doctor", help="Validate local sidecar setup")
    doctor_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser_map["doctor"] = doctor_parser

    stock_parser = subparsers.add_parser("stock", help="Manage SKU stock")
    stock_parser.add_argument("--env-file", default=".env", help="Path to .env file")
    stock_sub = stock_parser.add_subparsers(dest="stock_command", required=True)
    stock_sub.add_parser("show", help="Show stock state for all SKUs")
    stock_set = stock_sub.add_parser("set", help="Set absolute total for a SKU")
    stock_set.add_argument("sku", help="SKU id")
    stock_set.add_argument("total", help="New total (int, or 'none'/'infinite' to disable tracking)")
    stock_add = stock_sub.add_parser("add", help="Increment/decrement SKU total by delta")
    stock_add.add_argument("sku", help="SKU id")
    stock_add.add_argument("delta", help="Integer delta (can be negative)")
    parser_map["stock"] = stock_parser

    init_parser = subparsers.add_parser("init", help="Interactive wizard to create a .env file")
    init_parser.add_argument("--output", default=".env", help="Output file path (default: .env)")
    parser_map["init"] = init_parser

    scaffold_parser = subparsers.add_parser("scaffold", help="Create a new agent directory with starter files")
    scaffold_parser.add_argument("directory", help="Directory to create")
    scaffold_parser.add_argument("--capability", default="", help="Pre-fill capability (e.g. translate)")
    parser_map["scaffold"] = scaffold_parser

    help_parser = subparsers.add_parser("help", help="Show help")
    help_parser.add_argument("topic", nargs="?",
                             choices=["run", "service", "doctor", "stock", "init", "scaffold"],
                             help="Help topic")
    parser_map["help"] = help_parser

    args = parser.parse_args()
    return parser, parser_map, args


# ── main ──────────────────────────────────────────────────────────────────────

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

    if args.command == "stock":
        return await handle_stock_command(args)

    if args.command == "init":
        return handle_init(args)

    if args.command == "scaffold":
        return handle_scaffold(args)

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
