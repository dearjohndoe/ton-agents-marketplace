"""Execute a planned chain: 402 flow per agent, sequential, with refunds on failure."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from agents_cache import AgentInfo
from planner import ChainStep

logger = logging.getLogger(__name__)

STEP_REF_RE = re.compile(r"\{\{step_(\d+)\.result\}\}")

POLL_INTERVAL = 1  # seconds
POLL_TIMEOUT = 300  # seconds — max wait for async agent result
NETWORK_FEE_PER_TX = 10_000_000  # 0.01 TON estimate per outgoing tx


@dataclass
class StepResult:
    agent_name: str
    capability: str
    status: str  # "done" | "error"
    result: Any = None
    error: str | None = None
    tx_hash: str = ""
    amount_paid: int = 0


@dataclass
class ExecutionResult:
    steps: list[StepResult] = field(default_factory=list)
    final: Any = None
    refund_to_user: int = 0  # nanotons to return


def _substitute_refs(body: dict[str, Any], results: list[StepResult]) -> dict[str, Any]:
    """Replace {{step_N.result}} placeholders with actual results from previous steps."""
    resolved: dict[str, Any] = {}
    for key, value in body.items():
        if isinstance(value, str):
            def replacer(m: re.Match) -> str:
                idx = int(m.group(1))
                r = results[idx].result
                return r if isinstance(r, str) else __import__("json").dumps(r)
            resolved[key] = STEP_REF_RE.sub(replacer, value)
        else:
            resolved[key] = value
    return resolved


async def _preflight(
    session: aiohttp.ClientSession,
    endpoint: str,
    capability: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Send invoke without tx to get 402 payment request."""
    async with session.post(
        f"{endpoint}/invoke",
        json={"capability": capability, "body": body},
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        data = await resp.json()
        if resp.status == 402 and data.get("payment_request"):
            return data["payment_request"]
        raise RuntimeError(f"Expected 402, got {resp.status}: {data}")


async def _invoke_with_payment(
    session: aiohttp.ClientSession,
    endpoint: str,
    capability: str,
    body: dict[str, Any],
    tx_hash: str,
    nonce: str,
) -> dict[str, Any]:
    """Send invoke with tx proof, poll if pending."""
    async with session.post(
        f"{endpoint}/invoke",
        json={"tx": tx_hash, "nonce": nonce, "capability": capability, "body": body},
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        data = await resp.json()
        if resp.status != 200:
            raise RuntimeError(data.get("error", f"HTTP {resp.status}"))

    if data.get("status") == "done":
        return data.get("result", data)

    if data.get("status") == "pending":
        job_id = data["job_id"]
        return await _poll_result(session, endpoint, job_id)

    if data.get("status") == "error":
        raise RuntimeError(data.get("error", "Agent returned error"))

    return data.get("result", data)


async def _poll_result(
    session: aiohttp.ClientSession,
    endpoint: str,
    job_id: str,
) -> Any:
    """Poll /result/:job_id until done or timeout."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        async with session.get(
            f"{endpoint}/result/{job_id}",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json()

        if data.get("status") == "done":
            return data.get("result", data)
        if data.get("status") == "error":
            raise RuntimeError(data.get("error", "Agent returned error"))

    raise TimeoutError(f"Agent job {job_id} timed out after {POLL_TIMEOUT}s")


async def execute_chain(
    chain: list[ChainStep],
    agents_by_sid: dict[str, AgentInfo],
    send_payment,  # async (address, amount, nonce) -> tx_hash
    total_budget: int,
    orchestrator_fee: int,
) -> ExecutionResult:
    """
    Execute chain step by step.

    send_payment: coroutine(address: str, amount: int, nonce: str) -> tx_hash: str
    total_budget: what the user paid to orchestrator (nanotons)
    orchestrator_fee: how much orchestrator keeps (nanotons)
    """
    result = ExecutionResult()
    spent = orchestrator_fee  # orchestrator fee is already "spent"
    remaining_steps_cost = sum(
        agents_by_sid[step.sidecar_id].actual_price + NETWORK_FEE_PER_TX
        for step in chain
    )

    async with aiohttp.ClientSession() as session:
        for i, step in enumerate(chain):
            agent = agents_by_sid[step.sidecar_id]
            step_result = StepResult(
                agent_name=agent.name,
                capability=agent.capability,
                status="error",
            )

            # Cost for remaining steps (including this one)
            this_step_cost = agent.actual_price + NETWORK_FEE_PER_TX
            remaining_steps_cost -= this_step_cost

            try:
                # Substitute {{step_N.result}} in body
                resolved_body = _substitute_refs(step.body, result.steps)

                # 402 preflight — get payment address and nonce
                payment_req = await _preflight(session, agent.endpoint, agent.capability, resolved_body)
                pay_address = payment_req["address"]
                pay_amount = int(payment_req["amount"])
                pay_nonce = payment_req["memo"]

                # Safety: check if agent raised price beyond what we quoted
                if pay_amount > agent.actual_price:
                    step_result.error = (
                        f"Agent raised price from {agent.actual_price} to {pay_amount}"
                    )
                    # Refund remaining budget for this + future steps
                    result.refund_to_user += this_step_cost + remaining_steps_cost
                    result.steps.append(step_result)
                    break

                # Send payment
                tx_hash = await send_payment(pay_address, pay_amount, pay_nonce)
                step_result.tx_hash = tx_hash
                step_result.amount_paid = pay_amount
                spent += pay_amount + NETWORK_FEE_PER_TX

                # Invoke with payment proof
                agent_result = await _invoke_with_payment(
                    session, agent.endpoint, agent.capability, resolved_body, tx_hash, pay_nonce,
                )
                step_result.status = "done"
                # Make file download URLs absolute so the frontend resolves them
                # against the correct sidecar, not the orchestrator's endpoint.
                if (
                    isinstance(agent_result, dict)
                    and agent_result.get("type") == "file"
                    and isinstance(agent_result.get("url"), str)
                    and agent_result["url"].startswith("/")
                ):
                    agent_result = {**agent_result, "url": f"{agent.endpoint}{agent_result['url']}"}
                step_result.result = agent_result

            except Exception as exc:
                logger.exception("Step %d (%s) failed", i, agent.name)
                step_result.error = "Step execution failed"
                # If an agent fails, we cannot guarantee it will refund us (it might be completely offline/broken).
                # To avoid losing money globally, we do not refund the user for the current failed step.
                # We only refund the budget allocated for steps that we haven't even attempted yet.
                result.refund_to_user += remaining_steps_cost
                result.steps.append(step_result)
                break

            result.steps.append(step_result)

    # Set final result from last successful step
    if result.steps and result.steps[-1].status == "done":
        result.final = result.steps[-1].result

    return result
