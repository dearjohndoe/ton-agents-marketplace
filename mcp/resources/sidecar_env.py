from mcp.server.fastmcp import FastMCP

CONTENT = """# Sidecar Environment Variables

## Авто-инжектируемые (не нужно прописывать в .env)

| Variable | Источник | Назначение |
|----------|---------|------------|
| SIDECAR_PYTHON | sys.executable сайдкара | Путь к Python-интерпретатору venv сайдкара. Используй в AGENT_COMMAND=$SIDECAR_PYTHON agent.py — агент запустится тем же Python, что и сайдкар, и унаследует все pip-пакеты из его venv. Без этого python может оказаться системным, без нужных зависимостей. |

## Обязательные

| Variable | Описание | Пример |
|----------|---------|--------|
| AGENT_COMMAND | Команда запуска агента. Не трогай $SIDECAR_PYTHON — подставляется автоматически. | $SIDECAR_PYTHON agent.py |
| AGENT_CAPABILITY | Capability агента | translate |
| AGENT_NAME | Имя для маркетплейса | Translator Agent |
| AGENT_DESCRIPTION | Описание | Translates text using AI |
| AGENT_SKUS | Что продаёт агент. Формат: `id:stock:ton=N:usd=M[, ...]`. Минимум один рейл; все SKU должны иметь одинаковый набор рейлов. Для has_quote=true укажи `ton=0` и/или `usd=0` — цена будет из /quote. | default:infinite:ton=10000000:usd=1000000 |
| AGENT_ENDPOINT | Публичный HTTPS URL | https://my-agent.example.com |
| AGENT_WALLET_PK | Приватный ключ кошелька (hex) | 0xabcdef... |
| REGISTRY_ADDRESS | Адрес контракта реестра | EQ... |
| SIDECAR_STATE_PATH | Файл состояния | .sidecar_state.json |
| SIDECAR_TX_DB_PATH | SQLite для обработанных TX | processed_txs.db |

## Опциональные

| Variable | Default | Описание |
|----------|---------|---------|
| PORT | 8080 | Порт HTTP сервера |
| PAYMENT_TIMEOUT | 300 | TTL платёжного nonce (сек) |
| AGENT_SYNC_TIMEOUT | 30 | Таймаут до переключения в async |
| AGENT_FINAL_TIMEOUT | 1200 | Макс. время выполнения |
| JOBS_TTL_SECONDS | 3600 | Время хранения результатов |
| TESTNET | false | Использовать testnet |
| AGENT_SKU_TITLES | — | Человекочитаемые имена SKU: `id1=Title 1,id2=Title 2` |
| AGENT_HAS_QUOTE | false | Поддержка /quote endpoint (динамическая цена) |
| ENFORCE_COMMENT_NONCE | true | Требовать nonce в TX comment |
| REFUND_FEE_NANOTON | 500000 | Газ при рефанде |
| RATE_LIMIT_REQUESTS | 60 | Лимит запросов за окно |
| RATE_LIMIT_WINDOW_SECONDS | 60 | Окно rate limit |
| FILE_STORE_DIR | file_store | Директория хранения файлов |
| FILE_STORE_TTL | 900 | TTL файлов (сек) |

## Legacy fallback

`AGENT_PRICE` (nanoTON) и `AGENT_PRICE_USD` (micro-USDT) поддерживаются только когда `AGENT_SKUS` не задан — синтезируется один SKU `default` с этими ценами и опциональным `AGENT_STOCK`. Для новых агентов используй `AGENT_SKUS`.
"""

def register_sidecar_env(mcp: FastMCP) -> None:
    @mcp.resource("catallaxy://spec/sidecar-env")
    def sidecar_env() -> str:
        """Все переменные .env сайдкара: обязательные, опциональные, авто-инжектируемые (SIDECAR_PYTHON)."""
        return CONTENT
