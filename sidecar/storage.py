from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SidecarState:
    last_heartbeat: str | None = None
    sidecar_id: str | None = None


class StateStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def load(self) -> SidecarState:
        if not self._path.exists():
            return SidecarState()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return SidecarState()
        return SidecarState(
            last_heartbeat=payload.get("last_heartbeat"),
            sidecar_id=payload.get("sidecar_id"),
        )

    def save(self, state: SidecarState) -> None:
        payload = {
            "last_heartbeat": state.last_heartbeat,
            "sidecar_id": state.sidecar_id,
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
