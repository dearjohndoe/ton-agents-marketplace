from __future__ import annotations

import argparse
import json

from settings import load_settings


async def handle_stock_command(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    from stock import StockStore
    store = StockStore(settings.stock_db_path)
    await store.init(settings.skus)
    try:
        if args.stock_command == "show":
            views = await store.list_views()
            rows = []
            for v in views:
                rows.append({
                    "sku": v.sku_id,
                    "title": v.title,
                    "price_ton": v.price_ton,
                    "price_usd": v.price_usd,
                    "total": v.total,
                    "sold": v.sold,
                    "reserved": v.reserved,
                    "stock_left": v.stock_left,
                })
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0

        if args.stock_command == "set":
            total: int | None
            raw = args.total.strip().lower()
            if raw in {"none", "infinite", "inf"}:
                total = None
            else:
                try:
                    total = int(raw)
                except ValueError:
                    print(f"Invalid total value: {args.total}")
                    return 1
                if total < 0:
                    print("total must be >= 0")
                    return 1
            await store.set_total(args.sku, total, reason="cli_set")
            view = await store.get_view(args.sku)
            print(json.dumps({"sku": view.sku_id, "total": view.total, "sold": view.sold, "stock_left": view.stock_left}, ensure_ascii=False))
            return 0

        if args.stock_command == "add":
            try:
                delta = int(args.delta)
            except ValueError:
                print(f"Invalid delta value: {args.delta}")
                return 1
            new_total = await store.adjust_total(args.sku, delta, reason="cli_add")
            view = await store.get_view(args.sku)
            print(json.dumps({"sku": view.sku_id, "total": new_total, "sold": view.sold, "stock_left": view.stock_left}, ensure_ascii=False))
            return 0

        print("Unknown stock command")
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        await store.close()
