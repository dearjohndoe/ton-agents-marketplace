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
| AGENT_PRICE | Цена в nanoTON (1 TON = 1e9). Для has_quote=true укажи 0 — реальная цена из /quote. | 10000000 |
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
| AGENT_HAS_QUOTE | false | Поддержка /quote endpoint (динамическая цена) |
| ENFORCE_COMMENT_NONCE | true | Требовать nonce в TX comment |
| REFUND_FEE_NANOTON | 500000 | Газ при рефанде |
| RATE_LIMIT_REQUESTS | 60 | Лимит запросов за окно |
| RATE_LIMIT_WINDOW_SECONDS | 60 | Окно rate limit |
| FILE_STORE_DIR | file_store | Директория хранения файлов |
| FILE_STORE_TTL | 900 | TTL файлов (сек) |
"""

def register_sidecar_env(mcp: FastMCP) -> None:
    @mcp.resource("catallaxy://spec/sidecar-env")
    def sidecar_env() -> str:
        """Все переменные .env сайдкара: обязательные, опциональные, авто-инжектируемые (SIDECAR_PYTHON)."""
        return CONTENT
