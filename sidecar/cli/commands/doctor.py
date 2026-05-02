from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from settings import load_settings


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
