"""Orchestrator agent — stdin/stdout interface for the sidecar.

Modes:
  describe  → returns args_schema
  quote     → plans chain via Gemini, returns plan + price to user
  (default) → executes a previously quoted chain
"""

import asyncio
import json
import os
import sys
import time
import uuid
import logging
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env")

# Add sidecar to path so we can import transfer.py
sys.path.insert(0, str(_HERE.parent.parent / "sidecar"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    filename=str(_HERE / "orchestrator.log"),
)
logger = logging.getLogger(__name__)

ARGS_SCHEMA = {
    "task": {
        "type": "string",
        "description": "Free-form task description in natural language",
        "required": True,
    },
    "quote_id": {
        "type": "string",
        "description": "Quote ID from a previous /quote call (required for execution, not for quoting)",
        "required": False,
    },
}

# Orchestrator fee: from AGENT_PRICE env var
ORCHESTRATOR_FEE = int(os.environ.get("AGENT_PRICE", 5_000_000))
NETWORK_FEE_PER_TX = 10_000_000  # ~0.01 TON per outgoing tx
QUOTE_TTL = 300  # seconds

# In-memory quote cache (persists across calls if sidecar keeps the process alive,
# but for subprocess mode we use a file-based cache)
QUOTES_DB = Path(__file__).parent / ".quotes_cache.db"


def _init_db() -> None:
    with sqlite3.connect(QUOTES_DB) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS quotes (
                quote_id TEXT PRIMARY KEY,
                data TEXT,
                expires_at REAL
            )
        ''')
        # Evict expired
        conn.execute('DELETE FROM quotes WHERE expires_at <= ?', (time.time(),))


def _save_quote(quote_id: str, data: dict, expires_at: float) -> None:
    _init_db()
    with sqlite3.connect(QUOTES_DB) as conn:
        conn.execute(
            'INSERT OR REPLACE INTO quotes (quote_id, data, expires_at) VALUES (?, ?, ?)',
            (quote_id, json.dumps(data, ensure_ascii=False), expires_at)
        )


def _load_quote(quote_id: str) -> dict | None:
    _init_db()
    with sqlite3.connect(QUOTES_DB) as conn:
        cur = conn.execute(
            'SELECT data FROM quotes WHERE quote_id = ? AND expires_at > ?',
            (quote_id, time.time())
        )
        row = cur.fetchone()
        if row:
            return json.loads(row[0])
        return None


def _delete_quote(quote_id: str) -> None:
    _init_db()
    with sqlite3.connect(QUOTES_DB) as conn:
        conn.execute('DELETE FROM quotes WHERE quote_id = ?', (quote_id,))


def _get_config():
    if "GEMINI_API_KEY" not in os.environ:
        raise RuntimeError("GEMINI_API_KEY is not set in environment")
        
    return {
        "gemini_api_key": os.environ["GEMINI_API_KEY"],
        "toncenter_base": os.environ.get(
            "TONCENTER_BASE",
            "https://testnet.toncenter.com/api/v3" if os.environ.get("TESTNET", "").lower() in ("1", "true") else "https://toncenter.com/api/v3",
        ),
        "registry_address": os.environ["REGISTRY_ADDRESS"],
        "toncenter_api_key": os.environ.get("TONCENTER_API_KEY", ""),
        "wallet_pk": os.environ["AGENT_WALLET_PK"],
        "testnet": os.environ.get("TESTNET", "").lower() in ("1", "true"),
        "own_sidecar_id": os.environ.get("OWN_SIDECAR_ID", ""),
    }


async def handle_quote(task: str) -> dict:
    """Plan a chain and return a quote for the user."""
    from agents_cache import AgentsCache
    from planner import plan_chain

    cfg = _get_config()

    cache = AgentsCache(
        toncenter_base=cfg["toncenter_base"],
        registry_address=cfg["registry_address"],
        toncenter_api_key=cfg["toncenter_api_key"] or None,
    )
    if cfg["own_sidecar_id"]:
        cache.set_own_sidecar_id(cfg["own_sidecar_id"])

    agents = await cache.get_agents()

    plan = await plan_chain(
        task=task,
        agents=agents,
        gemini_api_key=cfg["gemini_api_key"],
    )

    if plan.error:
        return {"error": plan.error}

    assert plan.chain is not None

    # Build quote
    agents_map = {a.sidecar_id: a for a in agents}

    # Truncate chain after the first agent that returns a file —
    # the executor cannot pass file results between agents.
    note: str | None = None
    truncated_chain = []
    dropped_names = []
    for step in plan.chain:
        truncated_chain.append(step)
        agent = agents_map[step.sidecar_id]
        if agent.result_schema.get("type") == "file":
            # Keep this step but drop everything after it
            remaining = plan.chain[len(truncated_chain):]
            dropped_names = [agents_map[s.sidecar_id].name for s in remaining]
            break

    if dropped_names:
        note = (
            f"Steps after '{agents_map[truncated_chain[-1].sidecar_id].name}' were removed "
            f"because file results cannot be forwarded to other agents yet. "
            f"Dropped: {', '.join(dropped_names)}."
        )
        plan.chain = truncated_chain

    steps_info = []
    total_agents_cost = 0

    for i, step in enumerate(plan.chain):
        agent = agents_map[step.sidecar_id]
        price = agent.actual_price
        total_agents_cost += price
        steps_info.append({
            "step": i,
            "agent": agent.name,
            "sidecar_id": agent.sidecar_id,
            "capability": agent.capability,
            "input": step.body,
            "price": price,
            "price_ton": f"{price / 1_000_000_000:.4f} TON",
        })

    network_fees = len(plan.chain) * NETWORK_FEE_PER_TX
    total_price = total_agents_cost + network_fees + ORCHESTRATOR_FEE

    quote_id = str(uuid.uuid4())
    expires_at = int(time.time()) + QUOTE_TTL

    # Persist quote
    quote_data = {
        "chain": [{"sidecar_id": s.sidecar_id, "body": s.body} for s in plan.chain],
        "agents": {
            a.sidecar_id: {
                "name": a.name,
                "capability": a.capability,
                "price": a.actual_price,
                "endpoint": a.endpoint,
                "address": a.address,
            }
            for a in agents
            if a.sidecar_id in agents_map
        },
        "total_price": total_price,
        "task": task,
        "expires_at": expires_at,
    }
    _save_quote(quote_id, quote_data, expires_at)

    result: dict = {
        "price": total_price,
        "plan": {
            "quote_id": quote_id,
            "steps": steps_info,
            "orchestrator_fee": ORCHESTRATOR_FEE,
            "orchestrator_fee_ton": f"{ORCHESTRATOR_FEE / 1_000_000_000:.4f} TON",
            "network_fees": network_fees,
            "network_fees_ton": f"{network_fees / 1_000_000_000:.4f} TON",
            "total_price": total_price,
            "total_price_ton": f"{total_price / 1_000_000_000:.4f} TON",
        },
        "ttl": QUOTE_TTL,
    }
    if note:
        result["note"] = note

    return result


async def handle_execute(task: str, quote_id: str) -> dict:
    """Execute a previously quoted chain."""
    from agents_cache import AgentInfo
    from executor import execute_chain
    from planner import ChainStep
    from transfer import TransferSender, payment_body, refund_body

    cfg = _get_config()

    # Load quote
    quote = _load_quote(quote_id)
    if not quote:
        return {"error": "Quote not found or expired"}

    # Rebuild chain and agents from quote
    chain = [ChainStep(sidecar_id=s["sidecar_id"], body=s["body"]) for s in quote["chain"]]
    agents_data = quote["agents"]

    agents_by_sid: dict[str, AgentInfo] = {}
    for sid, info in agents_data.items():
        agents_by_sid[sid] = AgentInfo(
            sidecar_id=sid,
            name=info["name"],
            description="",
            capability=info["capability"],
            price=info["price"],
            actual_price=info["price"],
            endpoint=info["endpoint"],
            address=info["address"],
            alive=True,
        )

    # Initialize payment sender
    sender = TransferSender(
        private_key_hex=cfg["wallet_pk"],
        testnet=cfg["testnet"],
    )

    async def send_payment(address: str, amount: int, nonce: str) -> str:
        body = payment_body(nonce)
        return await sender.send(address, amount, body)

    try:
        result = await execute_chain(
            chain=chain,
            agents_by_sid=agents_by_sid,
            send_payment=send_payment,
            total_budget=quote["total_price"],
            orchestrator_fee=ORCHESTRATOR_FEE,
        )

        # Refund unused budget to the user
        if result.refund_to_user > 0:
            caller_address = os.environ.get("CALLER_ADDRESS", "")
            caller_tx_hash = os.environ.get("CALLER_TX_HASH", "")
            own_sidecar_id = cfg.get("own_sidecar_id", "")
            if caller_address:
                try:
                    refund_cell = refund_body(caller_tx_hash, "partial_chain_failure", own_sidecar_id)
                    await sender.send(caller_address, result.refund_to_user, refund_cell)
                    logger.info(
                        "Refund sent: %d nanotons to %s",
                        result.refund_to_user, caller_address,
                    )
                except Exception:
                    logger.exception("Failed to send refund of %d to %s", result.refund_to_user, caller_address)
            else:
                logger.error("Cannot refund %d nanotons: CALLER_ADDRESS not set", result.refund_to_user)
    finally:
        await sender.close()

    # Consume quote
    _delete_quote(quote_id)

    # Build response
    steps_output = []
    for sr in result.steps:
        step_data = {"agent": sr.agent_name, "status": sr.status}
        if sr.result is not None:
            step_data["result"] = sr.result
        if sr.error:
            step_data["error"] = sr.error
        steps_output.append(step_data)

    data: dict = {
        "steps": steps_output,
        "final": result.final,
    }
    if result.refund_to_user > 0:
        data["refund_nanotons"] = result.refund_to_user

    return {"result": {"type": "json", "data": data}}


def main() -> None:
    task_input = json.load(sys.stdin)
    mode = task_input.get("mode", "")

    if mode == "describe":
        print(json.dumps({"args_schema": ARGS_SCHEMA, "result_schema": {"type": "json"}}))
        return

    body = task_input.get("body") or {}
    task_text = body.get("task", "").strip()

    if not task_text:
        raise ValueError("body.task must be a non-empty string")

    if mode == "quote":
        result = asyncio.run(handle_quote(task_text))
    else:
        quote_id = body.get("quote_id", "").strip()
        if not quote_id:
            raise ValueError("body.quote_id is required for execution (get a quote first)")
        result = asyncio.run(handle_execute(task_text, quote_id))

    if "error" in result and "result" not in result:
        print(result["error"], file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
