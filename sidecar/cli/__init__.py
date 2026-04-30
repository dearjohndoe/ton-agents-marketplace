from .args import parse_cli_args
from .commands.doctor import handle_doctor
from .commands.init_cmd import handle_init
from .commands.scaffold import handle_scaffold
from .commands.service import (
    handle_service_command,
    handle_service_install,
    handle_service_uninstall,
)
from .commands.stock import handle_stock_command
from .discovery import (
    _discover_sidecar_agents,
    _normalize_service_name,
    _resolve_service_name,
)
from .main import async_main, main
from .server import run_server
from .shell import _run_command, _systemctl_command
from .systemd import render_systemd_unit
from .template import _AGENT_TEMPLATE, _CAPABILITIES, _CTLX_SUFFIX, _REGISTRY_ADDRESS
from .wallet import _generate_wallet_keypair

__all__ = [
    "main",
    "async_main",
    "parse_cli_args",
    "run_server",
    "handle_doctor",
    "handle_init",
    "handle_scaffold",
    "handle_service_command",
    "handle_service_install",
    "handle_service_uninstall",
    "handle_stock_command",
    "render_systemd_unit",
    "_normalize_service_name",
    "_discover_sidecar_agents",
    "_resolve_service_name",
    "_run_command",
    "_systemctl_command",
    "_generate_wallet_keypair",
]
