from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from storage import SidecarState, StateStore


logger = logging.getLogger(__name__)


@dataclass
class HeartbeatConfig:
    registry_address: str
    endpoint: str
    price: int
    capability: str
    docs_bag_id: str | None


class HeartbeatManager:
    def __init__(
        self,
        config: HeartbeatConfig,
        state_store: StateStore,
        transfer_sender: Callable[[str, int, str], Awaitable[str]],
        heartbeat_interval_days: int = 7,
        immediate_threshold_days: int = 6,
    ) -> None:
        self._config = config
        self._state_store = state_store
        self._transfer_sender = transfer_sender
        self._interval = timedelta(days=heartbeat_interval_days)
        self._immediate_threshold = timedelta(days=immediate_threshold_days)

    def _build_payload(self) -> dict[str, Any]:
        return {
            "capabilities": [self._config.capability],
            "price": self._config.price,
            "endpoint": self._config.endpoint,
            "docs_bag_id": self._config.docs_bag_id,
        }

    def _should_send_now(self, state: SidecarState) -> bool:
        if not state.last_heartbeat:
            return True
        try:
            last = datetime.fromisoformat(state.last_heartbeat.replace("Z", "+00:00"))
        except ValueError:
            return True
        return datetime.now(timezone.utc) - last >= self._immediate_threshold

    async def send_if_needed(self, force: bool = False) -> bool:
        state = self._state_store.load()
        if not force and not self._should_send_now(state):
            return False

        payload = self._build_payload()
        payload_json = json.dumps(payload, ensure_ascii=False)
        await self._transfer_sender(self._config.registry_address, 10_000_000, payload_json)

        state.last_heartbeat = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._state_store.save(state)
        logger.info("Heartbeat sent")
        return True

    async def loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.send_if_needed(force=False)
            except Exception:
                logger.exception("Heartbeat failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=3600)
            except asyncio.TimeoutError:
                continue
