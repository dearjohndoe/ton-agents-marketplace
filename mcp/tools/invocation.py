import asyncio
import aiohttp
from mcp.server.fastmcp import FastMCP
from lib.cell_builder import build_payment_cell

def register_invocation_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def preflight(
        endpoint: str,
        capability: str,
        body: dict,
        quote_id: str | None = None,
    ) -> dict:
        """Initiate agent call: get payment details and build TON Cell payload for @ton/mcp."""
        payload = {"capability": capability, "body": body}
        if quote_id:
            payload["quote_id"] = quote_id
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{endpoint}/invoke",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 402:
                    text = await resp.text()
                    raise ValueError(f"Expected 402, got {resp.status}: {text}")
                data = await resp.json()
        pr = data.get("payment_request") or {}
        address = pr.get("address", "")
        amount = str(pr.get("amount", "0"))
        nonce = pr.get("memo", "")
        payload_b64, payload_hex = build_payment_cell(nonce)
        return {
            "address": address,
            "amount": amount,
            "amount_ton": f"{int(amount) / 1e9:.9f}".rstrip("0").rstrip("."),
            "nonce": nonce,
            "payload_base64": payload_b64,
            "payload_hex": payload_hex,
        }

    @mcp.tool()
    async def invoke_paid(
        endpoint: str,
        tx_hash: str,
        nonce: str,
        capability: str,
        body: dict,
        quote_id: str | None = None,
        auto_poll: bool = True,
        poll_timeout: int = 300,
    ) -> dict:
        """Call agent with proof of payment (TX hash from @ton/mcp)."""
        payload: dict = {"tx": tx_hash, "nonce": nonce, "capability": capability, "body": body}
        if quote_id:
            payload["quote_id"] = quote_id
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{endpoint}/invoke",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json()

        if data.get("status") == "done":
            return {"status": "done", "result": data.get("result"), "job_id": data.get("job_id")}

        job_id = data.get("job_id") or data.get("id")
        if not job_id or not auto_poll:
            return {"status": data.get("status", "pending"), "job_id": job_id, "poll_endpoint": f"GET /result/{job_id}"}

        # auto poll
        deadline = asyncio.get_event_loop().time() + poll_timeout
        async with aiohttp.ClientSession() as session:
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(1)
                async with session.get(
                    f"{endpoint}/result/{job_id}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    result = await resp.json()
                status = result.get("status")
                if status in ("done", "error"):
                    return result
        return {"status": "pending", "job_id": job_id, "error": "poll_timeout"}

    @mcp.tool()
    async def poll_result(endpoint: str, job_id: str) -> dict:
        """Poll async job result."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{endpoint}/result/{job_id}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return await resp.json()

    @mcp.tool()
    async def get_quote(endpoint: str, capability: str, body: dict) -> dict:
        """Get price quote from agent (for agents with dynamic pricing)."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{endpoint}/quote",
                json={"capability": capability, "body": body},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
        price = data.get("price", 0)
        if price:
            data["price_ton"] = f"{price / 1e9:.9f}".rstrip("0").rstrip(".")
        return data
