from __future__ import annotations

from typing import Iterable

from aiohttp import web

from settings import AgentSku


def resolve_sku(
    sku_field: str | None,
    skus_by_id: dict[str, AgentSku],
    single_sku: AgentSku | None,
    all_skus: Iterable[AgentSku],
) -> tuple[AgentSku | None, web.Response | None]:
    """Pick SKU from an explicit id. Falls back to single-SKU agent default.

    Returns (sku, None) on success, (None, error_response) on failure.
    """
    requested = (sku_field or "").strip()
    if requested:
        sku = skus_by_id.get(requested)
        if sku is None:
            return None, web.json_response(
                {"error": "Unknown SKU", "sku": requested}, status=400,
            )
        return sku, None

    if single_sku is not None:
        return single_sku, None

    return None, web.json_response(
        {"error": "sku is required (multiple SKUs configured)",
         "available_skus": [s.sku_id for s in all_skus]},
        status=400,
    )


def sku_price(sku: AgentSku, rail: str) -> int | None:
    if rail == "USDT":
        return sku.price_usd
    return sku.price_ton
