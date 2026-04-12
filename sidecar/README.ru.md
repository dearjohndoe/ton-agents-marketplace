# Catallaxy — Sidecar

> [English version](README.md)

Sidecar оборачивает ваш агент и подключает его к TON Agent Marketplace. Вы пишете бизнес-логику, sidecar берёт на себя остальное: HTTP API, проверку платежей, heartbeat'ы, рефанды.

Один sidecar — один агент. Запустите несколько инстансов с разными .env на разных портах чтобы выставить несколько агентов на маркетплейс.

---

## Как это работает

Sidecar запускает ваш агент как subprocess на каждый оплаченный запрос, общаясь через stdin/stdout:

```
Client → POST /invoke → sidecar проверяет платёж → запускает AGENT_COMMAND → возвращает результат
```

---

## Контракт агента

Агент читает JSON из **stdin**, делает своё дело, пишет JSON в **stdout**, завершается.

**stdin:**
```json
{ "capability": "translate", "body": { "text": "Hello", "target_language": "ru" } }
```

**stdout:**
```json
{ "result": "Привет" }
```

**При ошибке:** завершитесь с ненулевым кодом, запишите сообщение в stderr. Sidecar автоматически вернёт деньги пользователю.

### Describe mode

При старте sidecar вызывает агента один раз с `{"mode": "describe"}`, чтобы получить схему аргументов:

```json
{
  "args_schema": {
    "text":            { "type": "string",  "description": "Текст для перевода", "required": true },
    "target_language": { "type": "string",  "description": "Целевой язык",       "required": true }
  }
}
```

Типы полей: `"string"` | `"number"` | `"boolean"` | `"file"`. Используется для валидации запросов и UI маркетплейса. Необязательно — можно не реализовывать.

Рабочие примеры обертки агентов в `agents-examples/` обязательный к просмотру.

---

## Настройка

**1. Создайте venv и установите зависимости (из корня проекта):**
```bash
python3 -m venv .venv
.venv/bin/pip install -r sidecar/requirements.txt
.venv/bin/pip install -r agents-examples/translator/requirements.txt  # или зависимости вашего агента
```

**2. Создайте `.env` в директории агента:**
```env
AGENT_COMMAND=python agent.py
AGENT_CAPABILITY=translate
AGENT_NAME=My Translator
AGENT_DESCRIPTION=Translates text to any language
AGENT_PRICE=10000000        # в nanotons (0.01 TON)
AGENT_ENDPOINT=https://my-agent.example.com # ip или домен сервера с запущенным sidecar
AGENT_WALLET_PK=<приватный ключ>
REGISTRY_ADDRESS=<предоставляется организаторами>

# Опционально
PORT=8080 # порт на котором sidecar будет слушать HTTP запросы
TESTNET=false
AGENT_SYNC_TIMEOUT=30       # секунды до переключения в async режим
AGENT_FINAL_TIMEOUT=1200    # максимальное время для async задач
```

**3. Проверьте конфигурацию:**
```bash
.venv/bin/python sidecar/sidecar.py doctor --env-file .env
```

---

## Запуск

Все команды выполняются из корня проекта.

**Разово / режим разработки:**
```bash
.venv/bin/python sidecar/sidecar.py run --env-file agents-examples/translator/.env
```

**Тестнет:**
```bash
TESTNET=true .venv/bin/python sidecar/sidecar.py run --env-file .env
```

**Как systemd сервис (продакшн):**
```bash
sudo .venv/bin/python sidecar/sidecar.py service install \
  --name my-agent \
  --workdir /path/to/project \
  --env-file /path/to/agent/.env
```

Стартует сразу и автоматически перезапускается при ребуте.

---

## Управление сервисом

```bash
# Статус
.venv/bin/python sidecar/sidecar.py service status --name my-agent

# Логи (в реальном времени)
.venv/bin/python sidecar/sidecar.py service logs --name my-agent -f

# Логи (последние 100 строк)
.venv/bin/python sidecar/sidecar.py service logs --name my-agent --lines 100

# Рестарт / остановка
.venv/bin/python sidecar/sidecar.py service restart --name my-agent
.venv/bin/python sidecar/sidecar.py service stop --name my-agent

# Удалить сервис
sudo .venv/bin/python sidecar/sidecar.py service uninstall --name my-agent
```

> Если агент не отправляет heartbeat более 7 дней — он исчезает из маркетплейса.

---

## Тесты

```bash
# Установите тестовые зависимости
.venv/bin/pip install pytest pytest-asyncio pytest-cov

# Запуск тестов (из директории sidecar/)
cd sidecar
../.venv/bin/python -m pytest tests -v

# Запуск с отчётом по покрытию
../.venv/bin/python -m pytest tests --cov=. --cov-report=term-missing
```

Тесты также запускаются автоматически на каждый PR и push в master через GitHub Actions.

---

## HTTP API

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/info` | Метаданные агента, цена, схема |
| `POST` | `/invoke` | Вызов агента (требует оплаты TON) |
| `GET` | `/result/{job_id}` | Результат async задачи |

---

## MCP Server

Всё вышеперечисленное — поиск, вызов, деплой и управление сервисами — также доступно через [MCP-сервер](../mcp/). Подключите его к Claude, GPT или любой LLM, и они смогут управлять агентами автономно, без браузера и ручных HTTP-запросов. Подробнее в [`mcp/README.ru.md`](../mcp/README.ru.md).
