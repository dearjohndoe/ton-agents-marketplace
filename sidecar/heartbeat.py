from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from pytoniq_core import Cell

from storage import SidecarState, StateStore
from transfer import TransferFn, heartbeat_body

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatConfig:
    registry_address: str
    endpoint: str
    price: int
    capability: str
    name: str
    description: str
    args_schema: dict[str, Any]
    has_quote: bool = False
    price_usdt: int | None = None
    sidecar_id: str | None = None
    result_schema: dict[str, Any] | None = None


class HeartbeatManager:
    def __init__(
        self,
        config: HeartbeatConfig,
        state_store: StateStore,
        transfer_sender: TransferFn,
        heartbeat_interval_days: int = 7,
        immediate_threshold_days: int = 6,
    ) -> None:
        self._config = config
        self._state_store = state_store
        self._transfer_sender = transfer_sender
        self._interval = timedelta(days=heartbeat_interval_days)
        self._immediate_threshold = timedelta(days=immediate_threshold_days)

    def _build_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self._config.name,
            "description": self._config.description,
            "capabilities": [self._config.capability],
            "price": self._config.price,
            "endpoint": self._config.endpoint,
            "args_schema": self._config.args_schema,
        }
        if self._config.has_quote:
            payload["has_quote"] = True
        if self._config.price_usdt is not None:
            payload["price_usdt"] = self._config.price_usdt
        if self._config.sidecar_id:
            payload["sidecar_id"] = self._config.sidecar_id
        if self._config.result_schema:
            payload["result_schema"] = self._config.result_schema
        return payload

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
        body = heartbeat_body(payload_json)
        await self._transfer_sender(self._config.registry_address, 10_000_000, body)

        state.last_heartbeat = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._state_store.save(state)
        logger.info("Heartbeat sent")
        return True

    async def loop(self, stop_event: asyncio.Event) -> None:
        # Wake at least once per hour so we can react quickly to shutdown,
        # but honor self._interval when it's shorter than that (tests and
        # aggressive intervals would otherwise be ignored entirely).
        poll_timeout = min(self._interval.total_seconds(), 3600)
        while not stop_event.is_set():
            try:
                await self.send_if_needed(force=False)
            except Exception:
                logger.exception("Heartbeat failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_timeout)
            except asyncio.TimeoutError:
                continue
