"""list-seller — продаёт строки из захардкоженного списка по одной за вызов.

Контракт sidecar:
- describe → {"args_schema": ..., "result_schema": ...}
- quote   → {"price": <ton_nanoton>, "price_usdt": <micro_usd>?, "plan": "...", "ttl": N}
            если файл пуст — exit 1, sidecar отдаст 500 клиенту до оплаты.
- invoke success → stdout: {"result": {"type": "string", "data": "<token>"}}
- inventory empty → stdout: {"error": "out_of_stock", "reason": "..."} (exit 0)
- любая другая ошибка → exit != 0, sidecar вернёт refund

Окружение:
- TOKENS_FILE_PATH — путь до файла с токенами; в имени допустим плейсхолдер
  <sku>, который агент подставляет из body.sku (default — sku "default").
  Пример: /var/lib/list-seller/tokens-<sku>.txt
- LOG_FILE_PATH — путь до лога продаж (опц., по умолчанию рядом с agent.py).
- AGENT_SKUS — sidecar-овский конфиг, агент перепарсивает его в quote-режиме,
  чтобы достать цену для конкретного SKU.
- CALLER_ADDRESS, CALLER_TX_HASH, PAYMENT_RAIL — проставляются sidecar'ом.

Защита от оплаты впустую (quote-gate):
- Если у агента включён AGENT_HAS_QUOTE=true, фронт обязан сначала дёрнуть
  /quote. В quote-режиме агент peek'ает первую строку файла (без удаления).
  Пустой файл → exit 1 → sidecar возвращает 500 ДО формирования инвойса 402.
- Это best-effort: peek != pop, поэтому при гонке на последних позициях
  возможен сценарий «quote прошёл → к моменту invoke токен уже забрали другие
  → invoke вернёт out_of_stock и sidecar сделает рефанд». Это нормально,
  идеального гейта без правок sidecar нет.

Конкурентная безопасность:
- Эксклюзивный fcntl.flock на отдельном lock-файле (`<tokens>.lock`).
  Лок-файл никогда не переименовывается, поэтому семантика flock сохраняется
  при atomic rename файла токенов.
- Токены переписываются через tmp + os.replace + fsync директории — никаких
  частично записанных состояний при падении.
- Порядок: сначала коммитим списание (rename + fsync), пишем лог, и только
  потом печатаем результат. Если процесс падает после коммита, но до stdout —
  sidecar выдаст refund (а юнит уже потерян), но повторной выдачи не будет.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import sys
import time
from pathlib import Path

ARGS_SCHEMA: dict = {}
RESULT_SCHEMA = {"type": "string"}
DEFAULT_QUOTE_TTL = 300


def _parse_skus_env(sku_id: str) -> tuple[int | None, int | None]:
    """Перепарсивает AGENT_SKUS, чтобы достать ton/usd-цену конкретного SKU.

    Формат (как в sidecar/settings.py): 'sku:stock:ton=N:usd=M,sku2:...'.
    Возвращает (price_ton_nanoton, price_usd_microusd) или (None, None).
    """
    raw = os.environ.get("AGENT_SKUS", "").strip()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 3 or parts[0].strip() != sku_id:
            continue
        ton: int | None = None
        usd: int | None = None
        for spec in parts[2:]:
            spec = spec.strip()
            if spec.startswith("ton="):
                try:
                    ton = int(spec[4:])
                except ValueError:
                    pass
            elif spec.startswith("usd="):
                try:
                    usd = int(spec[4:])
                except ValueError:
                    pass
        return ton, usd
    return None, None


def _resolve_price(sku_id: str) -> tuple[int | None, int | None]:
    ton, usd = _parse_skus_env(sku_id)
    if ton is None and usd is None:
        # Legacy single-SKU fallback.
        ap = os.environ.get("AGENT_PRICE", "").strip()
        ap_usd = os.environ.get("AGENT_PRICE_USD", "").strip()
        if ap.isdigit():
            ton = int(ap)
        if ap_usd.isdigit():
            usd = int(ap_usd)
    return ton, usd


def _mask(token: str, n: int = 4) -> str:
    if len(token) <= 2 * n + 3:
        return "***"
    return f"{token[:n]}...{token[-n:]}"


def _resolve_tokens_path(sku: str) -> Path:
    template = os.environ.get("TOKENS_FILE_PATH")
    if not template:
        raise RuntimeError("TOKENS_FILE_PATH env var is not set")
    return Path(template.replace("<sku>", sku))


def _resolve_log_path() -> Path:
    custom = os.environ.get("LOG_FILE_PATH")
    if custom:
        return Path(custom)
    return Path(__file__).resolve().parent / "log.txt"


def _fsync_dir(path: Path) -> None:
    try:
        dir_fd = os.open(str(path), os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _peek_first_token(tokens_path: Path) -> str | None:
    """Читает первую непустую строку под flock'ом БЕЗ изменения файла.
    Используется в quote-режиме как чек «инвентарь не пуст».
    """
    if not tokens_path.exists():
        raise FileNotFoundError(f"tokens file not found: {tokens_path}")

    lock_path = tokens_path.with_name(tokens_path.name + ".lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            content = tokens_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        for ln in content.splitlines():
            if ln.strip():
                return ln
        return None
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _pop_first_token(tokens_path: Path) -> str | None:
    """Достаёт первую строку из tokens_path под эксклюзивным локом.
    Возвращает токен или None, если список пуст. Падает, если файла нет.
    """
    if not tokens_path.exists():
        raise FileNotFoundError(f"tokens file not found: {tokens_path}")

    tokens_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = tokens_path.with_name(tokens_path.name + ".lock")

    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        try:
            content = tokens_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

        lines = [ln for ln in content.splitlines() if ln.strip()]
        if not lines:
            return None

        token = lines[0]
        remaining = lines[1:]

        tmp_path = tokens_path.with_name(tokens_path.name + ".tmp")
        # O_TRUNC чтобы не подобрать чужой хвост, если tmp остался от падения.
        with os.fdopen(
            os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600),
            "w",
            encoding="utf-8",
        ) as tmpf:
            if remaining:
                tmpf.write("\n".join(remaining) + "\n")
            tmpf.flush()
            os.fsync(tmpf.fileno())

        os.replace(tmp_path, tokens_path)
        _fsync_dir(tokens_path.parent)

        return token
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _append_log(log_path: Path, entry: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_lock_path = log_path.with_name(log_path.name + ".lock")
    lock_fd = os.open(log_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        with os.fdopen(
            os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600),
            "a",
            encoding="utf-8",
        ) as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def handle_quote(task: dict) -> dict:
    """Quote-mode: peek токена + цена из AGENT_SKUS. Пустой файл → RuntimeError
    (агент валится exit 1, sidecar отдаёт 500 клиенту до 402-инвойса).
    """
    sku = (task.get("sku") or (task.get("body") or {}).get("sku") or "default").strip() or "default"
    tokens_path = _resolve_tokens_path(sku)

    token = _peek_first_token(tokens_path)
    if token is None:
        # Сигнал «нет смысла платить» через ненулевой exit. sidecar превратит
        # это в 500 на /quote — клиент инвойс 402 не получит.
        raise RuntimeError(f"out_of_stock: sku={sku} inventory is empty")

    price_ton, price_usd = _resolve_price(sku)
    # sidecar требует price > 0; если ton не задан, попробуем подставить usd
    # как primary (он лежит в `price`, поле price_usdt будет дублёром).
    primary = price_ton or price_usd
    if not primary or primary <= 0:
        raise RuntimeError(f"no price configured for sku={sku}")

    out: dict = {
        "price": primary,
        "plan": f"Deliver one item from list-seller inventory (sku={sku})",
        "ttl": DEFAULT_QUOTE_TTL,
    }
    if price_usd:
        out["price_usdt"] = price_usd
    return out


def process_task(task: dict) -> dict:
    body = task.get("body") or {}
    sku = (body.get("sku") or task.get("sku") or "default").strip() or "default"

    tokens_path = _resolve_tokens_path(sku)

    token = _pop_first_token(tokens_path)
    if token is None:
        return {
            "error": "out_of_stock",
            "reason": f"no tokens left for sku={sku}",
            "sku": sku,
        }

    # Списание уже зафиксировано на диске. Логируем и возвращаем результат.
    log_entry = {
        "ts": int(time.time()),
        "sku": sku,
        "caller_address": os.environ.get("CALLER_ADDRESS", ""),
        "caller_tx_hash": os.environ.get("CALLER_TX_HASH", ""),
        "payment_rail": os.environ.get("PAYMENT_RAIL", ""),
        "token_preview": _mask(token),
        "body": body,
    }
    try:
        _append_log(_resolve_log_path(), log_entry)
    except Exception as exc:
        # Лог — не критичный путь. На stderr — видно sidecar'у, но не валим
        # сделку: токен уже списан, пользователь должен получить его.
        print(f"warning: failed to write log: {exc}", file=sys.stderr)

    return {"result": {"type": "string", "data": token}}


def main() -> None:
    task = json.load(sys.stdin)
    mode = task.get("mode")

    if mode == "describe":
        print(json.dumps({"args_schema": ARGS_SCHEMA, "result_schema": RESULT_SCHEMA}))
        return

    if mode == "quote":
        result = handle_quote(task)
        print(json.dumps(result, ensure_ascii=False))
        return

    result = process_task(task)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
