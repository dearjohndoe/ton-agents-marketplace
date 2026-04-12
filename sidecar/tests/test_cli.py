"""Tests for cli.py — argument parsing, systemd unit rendering, service commands, doctor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import cli as cli_module
from cli import (
    handle_doctor,
    handle_service_command,
    handle_service_install,
    handle_service_uninstall,
    parse_cli_args,
    render_systemd_unit,
)


# ── render_systemd_unit ────────────────────────────────────────────────

def test_render_systemd_unit_contains_required_directives():
    unit = render_systemd_unit(
        service_name="sidecar",
        workdir="/opt/sidecar",
        env_file="/opt/sidecar/.env",
        python_bin="/usr/bin/python3",
        sidecar_path="/opt/sidecar/sidecar.py",
    )
    assert "[Unit]" in unit
    assert "[Service]" in unit
    assert "[Install]" in unit
    assert "Description=TON Sidecar (sidecar)" in unit
    assert "WorkingDirectory=/opt/sidecar" in unit
    assert "EnvironmentFile=/opt/sidecar/.env" in unit
    assert "ExecStart=/usr/bin/python3 /opt/sidecar/sidecar.py run --env-file /opt/sidecar/.env" in unit
    assert "Restart=always" in unit
    assert "WantedBy=multi-user.target" in unit


def test_render_systemd_unit_custom_service_name():
    unit = render_systemd_unit(
        service_name="my-agent",
        workdir="/x", env_file="/x/.env", python_bin="/py", sidecar_path="/x/sidecar.py",
    )
    assert "Description=TON Sidecar (my-agent)" in unit


# ── parse_cli_args ─────────────────────────────────────────────────────

def test_parse_cli_args_run_default():
    with patch.object(sys, "argv", ["sidecar", "run"]):
        _, _, args = parse_cli_args()
    assert args.command == "run"
    assert args.env_file == ".env"
    assert args.force_heartbeat is False


def test_parse_cli_args_run_with_force_heartbeat():
    with patch.object(sys, "argv", ["sidecar", "run", "--force-heartbeat", "--env-file", "/tmp/.env"]):
        _, _, args = parse_cli_args()
    assert args.force_heartbeat is True
    assert args.env_file == "/tmp/.env"


def test_parse_cli_args_service_install():
    with patch.object(sys, "argv", [
        "sidecar", "service", "--name", "myagent", "install",
        "--workdir", "/opt/a", "--env-file", "/opt/a/.env",
    ]):
        _, _, args = parse_cli_args()
    assert args.command == "service"
    assert args.service_command == "install"
    assert args.name == "myagent"
    assert args.workdir == "/opt/a"
    assert args.env_file == "/opt/a/.env"


def test_parse_cli_args_doctor():
    with patch.object(sys, "argv", ["sidecar", "doctor", "--env-file", "/tmp/e"]):
        _, _, args = parse_cli_args()
    assert args.command == "doctor"
    assert args.env_file == "/tmp/e"


def test_parse_cli_args_service_requires_subcommand():
    with patch.object(sys, "argv", ["sidecar", "service"]):
        with pytest.raises(SystemExit):
            parse_cli_args()


def test_parse_cli_args_service_restart_with_force_heartbeat():
    with patch.object(sys, "argv", ["sidecar", "service", "restart", "--force-heartbeat"]):
        _, _, args = parse_cli_args()
    assert args.service_command == "restart"
    assert args.force_heartbeat is True


def test_parse_cli_args_service_logs_follow():
    with patch.object(sys, "argv", ["sidecar", "service", "logs", "-f", "--lines", "50"]):
        _, _, args = parse_cli_args()
    assert args.follow is True
    assert args.lines == 50


# ── handle_service_install ─────────────────────────────────────────────

def test_handle_service_install_missing_env_file(tmp_path, capsys):
    args = argparse.Namespace(
        name="sidecar",
        workdir=str(tmp_path),
        env_file=str(tmp_path / "missing.env"),
        sidecar_path=str(tmp_path / "sidecar.py"),
    )
    assert handle_service_install(args) == 1
    out = capsys.readouterr().out
    assert "Env file not found" in out


def test_handle_service_install_permission_denied(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("")
    sidecar_path = tmp_path / "sidecar.py"
    sidecar_path.write_text("")

    def raise_perm(self, content, encoding="utf-8"):
        raise PermissionError("no")

    monkeypatch.setattr(Path, "write_text", raise_perm)

    args = argparse.Namespace(
        name="sidecar",
        workdir=str(tmp_path),
        env_file=str(env),
        sidecar_path=str(sidecar_path),
    )
    assert handle_service_install(args) == 1
    assert "Permission denied" in capsys.readouterr().out


def test_handle_service_install_success(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("KEY=val")
    sidecar_path = tmp_path / "sidecar.py"
    sidecar_path.write_text("")

    written: dict[str, str] = {}

    def fake_write_text(self, content, encoding="utf-8"):
        # Only intercept systemd unit writes; leave real env file alone.
        if str(self).startswith("/etc/systemd/system"):
            written["unit"] = content
            return
        return Path.write_text.__wrapped__(self, content, encoding=encoding)  # fallback

    # Simpler: capture any write to /etc/systemd/system
    original_write_text = Path.write_text

    def capturing_write_text(self, *a, **kw):
        if str(self).startswith("/etc/systemd/system"):
            written["unit"] = a[0] if a else kw.get("data", "")
            return
        return original_write_text(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", capturing_write_text)

    run_calls: list[list[str]] = []

    def fake_run(cmd):
        run_calls.append(cmd)
        return 0

    monkeypatch.setattr(cli_module, "_run_command", fake_run)

    args = argparse.Namespace(
        name="sidecar-x",
        workdir=str(tmp_path),
        env_file=str(env),
        sidecar_path=str(sidecar_path),
    )
    assert handle_service_install(args) == 0
    # Unit content was written.
    assert "unit" in written
    assert "TON Sidecar (sidecar-x)" in written["unit"]
    # daemon-reload and enable --now were both called.
    assert ["systemctl", "daemon-reload"] in run_calls
    assert any("enable" in cmd for cmd in run_calls)
    # Env file permissions were tightened.
    assert (env.stat().st_mode & 0o777) == 0o600
    # JSON success output.
    out = capsys.readouterr().out
    parsed = json.loads(out.strip())
    assert parsed["installed"] is True


# ── handle_service_uninstall ───────────────────────────────────────────

def test_handle_service_uninstall_no_env_file(tmp_path, monkeypatch, capsys):
    run_calls: list[list[str]] = []

    def fake_run(cmd):
        run_calls.append(cmd)
        return 0

    monkeypatch.setattr(cli_module, "_run_command", fake_run)

    # Unit file doesn't exist — skip unlink path.
    args = argparse.Namespace(name="sidecar-x", env_file=None)
    assert handle_service_uninstall(args) == 0
    out = capsys.readouterr().out
    parsed = json.loads(out.strip())
    assert parsed["uninstalled"] is True
    assert parsed["removed_files"] == []
    # Stop, disable, daemon-reload all called.
    actions = {cmd[1] if len(cmd) > 1 and cmd[0] == "systemctl" else "" for cmd in run_calls}
    assert "stop" in actions
    assert "disable" in actions


def test_handle_service_uninstall_cleans_state_files(tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}")
    tx_file = tmp_path / "tx.db"
    tx_file.write_text("")

    monkeypatch.setattr(cli_module, "_run_command", lambda cmd: 0)

    fake_settings = MagicMock()
    fake_settings.state_path = str(state_file)
    fake_settings.tx_db_path = str(tx_file)
    monkeypatch.setattr(cli_module, "load_settings", lambda _: fake_settings)

    args = argparse.Namespace(name="sidecar-x", env_file="/fake/.env")
    assert handle_service_uninstall(args) == 0
    assert not state_file.exists()
    assert not tx_file.exists()
    parsed = json.loads(capsys.readouterr().out.strip())
    assert len(parsed["removed_files"]) == 2


# ── handle_service_command dispatcher ──────────────────────────────────

def test_handle_service_command_unknown_returns_1(capsys):
    args = argparse.Namespace(service_command="nonsense", name="sidecar")
    assert handle_service_command(args) == 1
    assert "Unknown service command" in capsys.readouterr().out


def test_handle_service_command_start(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_module, "_run_command", lambda cmd: calls.append(cmd) or 0)

    args = argparse.Namespace(service_command="start", name="sidecar")
    assert handle_service_command(args) == 0
    assert calls == [["systemctl", "start", "sidecar.service"]]


def test_handle_service_command_stop(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_module, "_run_command", lambda cmd: calls.append(cmd) or 0)
    args = argparse.Namespace(service_command="stop", name="sidecar")
    assert handle_service_command(args) == 0
    assert calls == [["systemctl", "stop", "sidecar.service"]]


def test_handle_service_command_logs(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_module, "_run_command", lambda cmd: calls.append(cmd) or 0)
    args = argparse.Namespace(service_command="logs", name="sidecar", follow=True, lines=100)
    handle_service_command(args)
    assert calls == [["journalctl", "-u", "sidecar.service", "-n", "100", "-f"]]


# ── handle_doctor ──────────────────────────────────────────────────────

def test_handle_doctor_missing_env_file(tmp_path, capsys):
    args = argparse.Namespace(env_file=str(tmp_path / "missing.env"))
    rc = handle_doctor(args)
    assert rc == 1
    out = capsys.readouterr().out
    parsed = json.loads(out.strip())
    assert parsed["env_exists"] is False
    assert str(parsed["settings"]).startswith("error")


def test_handle_doctor_settings_error_reported(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("")

    def boom(_):
        raise RuntimeError("missing vars")
    monkeypatch.setattr(cli_module, "load_settings", boom)

    args = argparse.Namespace(env_file=str(env))
    rc = handle_doctor(args)
    assert rc == 1
    parsed = json.loads(capsys.readouterr().out.strip())
    assert "error" in parsed["settings"]
    assert "missing vars" in parsed["settings"]


def test_handle_doctor_describe_ok(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("")

    fake_settings = MagicMock()
    fake_settings.agent_command = 'echo {"args_schema": {"text": {}}}'
    monkeypatch.setattr(cli_module, "load_settings", lambda _: fake_settings)

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = b'{"args_schema": {"text": {}}}'
    fake_result.stderr = b""
    monkeypatch.setattr(cli_module.subprocess, "run", lambda *a, **kw: fake_result)

    args = argparse.Namespace(env_file=str(env))
    rc = handle_doctor(args)
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out.strip())
    assert parsed["describe_mode"].startswith("ok")
    assert "text" in parsed["describe_mode"]


def test_handle_doctor_describe_nonzero_exit(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.setattr(cli_module, "load_settings", lambda _: MagicMock(agent_command="false"))

    fake_result = MagicMock()
    fake_result.returncode = 2
    fake_result.stdout = b""
    fake_result.stderr = b"agent explosion"
    monkeypatch.setattr(cli_module.subprocess, "run", lambda *a, **kw: fake_result)

    args = argparse.Namespace(env_file=str(env))
    assert handle_doctor(args) == 1
    parsed = json.loads(capsys.readouterr().out.strip())
    assert "exit 2" in parsed["describe_mode"]
    assert "agent explosion" in parsed["describe_mode"]


def test_handle_doctor_describe_invalid_json(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.setattr(cli_module, "load_settings", lambda _: MagicMock(agent_command="x"))

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = b"not json"
    fake_result.stderr = b""
    monkeypatch.setattr(cli_module.subprocess, "run", lambda *a, **kw: fake_result)

    args = argparse.Namespace(env_file=str(env))
    assert handle_doctor(args) == 1
    parsed = json.loads(capsys.readouterr().out.strip())
    assert "invalid JSON" in parsed["describe_mode"]


def test_handle_doctor_describe_timeout(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.setattr(cli_module, "load_settings", lambda _: MagicMock(agent_command="x"))

    def timeout_run(*a, **kw):
        import subprocess as sp
        raise sp.TimeoutExpired(cmd="x", timeout=10)

    monkeypatch.setattr(cli_module.subprocess, "run", timeout_run)

    args = argparse.Namespace(env_file=str(env))
    assert handle_doctor(args) == 1
    parsed = json.loads(capsys.readouterr().out.strip())
    assert "timed out" in parsed["describe_mode"]


# ── _run_command ───────────────────────────────────────────────────────

def test_run_command_propagates_returncode():
    rc = cli_module._run_command([sys.executable, "-c", "import sys; sys.exit(7)"])
    assert rc == 7


def test_systemctl_command_builder():
    cmd = cli_module._systemctl_command("myagent", "restart")
    assert cmd == ["systemctl", "restart", "myagent.service"]
