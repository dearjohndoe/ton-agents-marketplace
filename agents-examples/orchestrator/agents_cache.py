"""Fetch and cache the list of live agents from TONCenter + health ping."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

HEARTBEAT_OPCODE = 0xAC52AB67
HEARTBEAT_OPCODE_HEX = f"0x{HEARTBEAT_OPCODE:x}"


@dataclass
class AgentInfo:
    sidecar_id: str
    name: str
    description: str
    capability: str
    price: int  # nanotons from heartbeat
    actual_price: int  # nanotons from 402 ping (0 if not pinged yet)
    endpoint: str
    address: str
    args_schema: dict[str, Any] = field(default_factory=dict)
    alive: bool = False


def _parse_heartbeat_body(body_b64: str) -> dict[str, Any] | None:
    """Parse the heartbeat Cell payload (opcode + JSON string tail)."""
    try:
        from pytoniq_core import Cell
        cell = Cell.from_boc(__import__("base64").b64decode(body_b64))[0]
        s = cell.begin_parse()
        opcode = s.load_uint(32)
        if opcode != HEARTBEAT_OPCODE:
            return None
        return __import__("json").loads(s.load_snake_string())
    except Exception as e:                                                                                                                 
        logger.warning("parse error: %s", e)                  
        return None 
    except Exception:
        return None


def _parse_tx(tx: dict[str, Any]) -> AgentInfo | None:
    """Parse a single TONCenter transaction into AgentInfo."""
    try:
        msg = tx.get("in_msg") or {}
        opcode = (msg.get("opcode") or "").lower()
        if opcode != HEARTBEAT_OPCODE_HEX:
            return None

        body = (msg.get("message_content") or {}).get("body")
        if not body:
            return None

        payload = _parse_heartbeat_body(body)
        if not payload or not payload.get("endpoint") or not payload.get("sidecar_id"):
            return None

        caps = payload.get("capabilities") or ([payload["capability"]] if payload.get("capability") else [])
        capability = caps[0] if caps else ""

        return AgentInfo(
            sidecar_id=payload["sidecar_id"],
            name=payload.get("name", ""),
            description=payload.get("description", ""),
            capability=capability,
            price=int(payload.get("price", 0)),
            actual_price=0,
            endpoint=payload["endpoint"],
            address=msg.get("source", ""),
            args_schema=payload.get("args_schema") or {},
        )
    except Exception:
        return None


def _dedupe(agents: list[AgentInfo]) -> list[AgentInfo]:
    best: dict[str, AgentInfo] = {}
    for a in agents:
        if a.sidecar_id not in best:
            best[a.sidecar_id] = a
    return list(best.values())


async def _fetch_agents_from_chain(
    toncenter_base: str,
    registry_address: str,
    api_key: str | None = None,
) -> list[AgentInfo]:
    """Fetch heartbeat TXs from TONCenter and parse them into AgentInfo list."""
    seven_days_ago = int(time.time()) - 7 * 24 * 3600
    params: dict[str, Any] = {
        "account": registry_address,
        "limit": 100,
        "sort": "desc",
        "archival": "true",
    }
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{toncenter_base}/transactions",
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()

    txs = data.get("transactions") or []
    agents: list[AgentInfo] = []
    for tx in txs:
        if tx.get("now", 0) < seven_days_ago:
            continue
        info = _parse_tx(tx)
        if info:
            agents.append(info)

    return _dedupe(agents)


async def _ping_agent(session: aiohttp.ClientSession, agent: AgentInfo) -> AgentInfo:
    """Send a dummy invoke to get 402 — confirms agent is alive and gets actual price."""
    try:
        async with session.post(
            f"{agent.endpoint}/invoke",
            json={"capability": agent.capability, "body": {}},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 402:
                data = await resp.json()
                pr = data.get("payment_request") or {}
                agent.actual_price = int(pr.get("amount", agent.price))
                agent.alive = True
            elif resp.status == 400:
                # Agent is alive but rejected empty body — that's fine, use heartbeat price
                agent.actual_price = agent.price
                agent.alive = True
    except Exception:
        logger.debug("Ping failed for %s (%s)", agent.name, agent.endpoint)
    return agent


async def _ping_all(agents: list[AgentInfo], max_agents: int = 100) -> list[AgentInfo]:
    """Ping all agents in parallel, return only alive ones."""
    to_ping = agents[:max_agents]
    async with aiohttp.ClientSession() as session:
        tasks = [_ping_agent(session, a) for a in to_ping]
        results = await asyncio.gather(*tasks)
    return [a for a in results if a.alive]


class AgentsCache:
    """Fetches agents from blockchain + pings them, caches result with TTL."""

    def __init__(
        self,
        toncenter_base: str,
        registry_address: str,
        toncenter_api_key: str | None = None,
        ttl_seconds: int = 600,
        max_agents: int = 100,
    ) -> None:
        self._toncenter_base = toncenter_base
        self._registry_address = registry_address
        self._api_key = toncenter_api_key
        self._ttl = ttl_seconds
        self._max_agents = max_agents
        self._cache: list[AgentInfo] = []
        self._last_fetch: float = 0
        self._own_sidecar_id: str = ""

    def set_own_sidecar_id(self, sidecar_id: str) -> None:
        """Exclude self from the agents list."""
        self._own_sidecar_id = sidecar_id

    async def get_agents(self) -> list[AgentInfo]:
        now = time.time()
        if self._cache and (now - self._last_fetch) < self._ttl:
            return self._cache

        logger.info("Refreshing agents list from blockchain...")
        agents = await _fetch_agents_from_chain(
            self._toncenter_base,
            self._registry_address,
            self._api_key,
        )

        # Exclude self
        if self._own_sidecar_id:
            agents = [a for a in agents if a.sidecar_id != self._own_sidecar_id]

        logger.info("Found %d agents, pinging...", len(agents))
        alive = await _ping_all(agents, self._max_agents)
        logger.info("%d agents alive", len(alive))

        self._cache = alive
        self._last_fetch = now
        return self._cache

    def find_by_sidecar_id(self, sidecar_id: str) -> AgentInfo | None:
        for a in self._cache:
            if a.sidecar_id == sidecar_id:
                return a
        return None
