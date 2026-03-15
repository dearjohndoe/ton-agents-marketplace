from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


@dataclass
class SidecarState:
    bag_id: str | None = None
    last_heartbeat: str | None = None
    storage_expires: str | None = None


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
            bag_id=payload.get("bag_id"),
            last_heartbeat=payload.get("last_heartbeat"),
            storage_expires=payload.get("storage_expires"),
        )

    def save(self, state: SidecarState) -> None:
        payload = {
            "bag_id": state.bag_id,
            "last_heartbeat": state.last_heartbeat,
            "storage_expires": state.storage_expires,
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class TonStorageClient:
    def __init__(self, base_url: str, session_cookie: str | None = None, timeout_seconds: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        cookies: dict[str, str] = {}
        if session_cookie:
            cookies["session"] = session_cookie
        self._client = httpx.AsyncClient(timeout=timeout_seconds, headers=headers, cookies=cookies)

    async def close(self) -> None:
        await self._client.aclose()

    async def upload_docs(self, docs_path: str, description: str | None = None) -> str:
        docs_file = Path(docs_path)
        if not docs_file.exists():
            raise FileNotFoundError(f"docs file not found: {docs_path}")

        data = {}
        if description:
            data["description"] = description[:100]

        with docs_file.open("rb") as file_handle:
            files = {"file": (docs_file.name, file_handle, "application/json")}
            response = await self._client.post(f"{self._base_url}/api/v1/files", data=data, files=files)

        response.raise_for_status()
        payload = response.json()
        bag_id = payload.get("bag_id")
        if not bag_id:
            raise RuntimeError("TON Storage response missing bag_id")
        return str(bag_id)

    async def get_details(self, bag_id: str) -> dict[str, Any]:
        response = await self._client.post(f"{self._base_url}/api/v1/files/details", json={"bag_id": bag_id})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected storage details response")
        return payload

    async def stop_storage(self, bag_id: str) -> None:
        response = await self._client.delete(f"{self._base_url}/api/v1/files/{bag_id}")
        response.raise_for_status()

    async def extend_storage(self, bag_id: str, amount: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"bag_id": bag_id}
        if amount is not None:
            body["amount"] = amount
        response = await self._client.post(f"{self._base_url}/api/v1/contracts/topup", json=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {}
        return payload


def parse_storage_expiry(details_payload: dict[str, Any]) -> str | None:
    expiry_keys = ["expires_at", "expiration", "expiry", "valid_until"]
    for key in expiry_keys:
        value = details_payload.get(key)
        if value:
            return str(value)

    file_info = details_payload.get("file")
    if isinstance(file_info, dict):
        for key in expiry_keys:
            value = file_info.get(key)
            if value:
                return str(value)

    return None


def should_extend_storage(expires_at_iso: str | None, threshold_days: int = 7) -> bool:
    if not expires_at_iso:
        return False
    try:
        expires = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return False

    now = datetime.now(timezone.utc)
    return expires - now <= timedelta(days=threshold_days)
