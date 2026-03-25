import os
import time
import aiohttp
from typing import Any

def get_toncenter_base() -> str:
    testnet = os.getenv("CATALLAXY_TESTNET", "false").lower() == "true"
    return "https://testnet.toncenter.com/api/v3" if testnet else "https://toncenter.com/api/v3"

async def fetch_transactions(registry_address: str, limit: int = 100) -> list[dict]:
    api_key = os.getenv("CATALLAXY_TONCENTER_API_KEY")
    base = get_toncenter_base()
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    params = {"account": registry_address, "limit": limit, "sort": "desc", "archival": "true"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/transactions", params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
    return data.get("transactions") or []
