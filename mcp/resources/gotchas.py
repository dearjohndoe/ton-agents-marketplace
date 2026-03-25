from mcp.server.fastmcp import FastMCP

CONTENT = """# Известные грабли при разработке агентов

## TonAPI: объекты могут приходить как строки

TonAPI иногда возвращает вложенные объекты (nft, collection, contract) как строку-адрес
вместо объекта — если сущность неизвестна или не индексирована.

Пример из /v2/accounts/{address}/events:

```json
// Ожидаешь:
{"nft": {"address": "EQ...", "metadata": {"name": "Cool NFT"}}}

// Получаешь для неизвестных NFT:
{"nft": "EQ..."}
```

Защита обязательна для полей: nft, collection, contract, jetton, account:

```python
# НЕПРАВИЛЬНО — упадёт с AttributeError:
name = event["nft"]["metadata"]["name"]

# ПРАВИЛЬНО:
nft = event.get("nft")
name = nft.get("metadata", {}).get("name", "NFT") if isinstance(nft, dict) else "NFT"

col_raw = item.get("collection")
col = (col_raw.get("name") if isinstance(col_raw, dict) else None) or "Unknown Collection"
```

Правило: всегда делай isinstance(x, dict) перед .get() для вложенных объектов TonAPI.

---

## test_agent игнорирует AGENT_COMMAND, всегда запускает `python agent.py`

MCP tool `test_agent` использует захардкоженный `python` вместо SIDECAR_PYTHON.
Если системный python не имеет нужных пакетов — тест упадёт даже если агент работает корректно.

Воркараунд: проверяй через `doctor` или запускай агент вручную:
```bash
echo '{"mode":"describe"}' | $SIDECAR_PYTHON agent.py
echo '{"capability":"...", "body":{...}}' | $SIDECAR_PYTHON agent.py
```

---

## Workdir сайдкара при `run`

Сайдкар ищет agent.py относительно своего CWD. Если запускаешь из другой директории:

```bash
# Неправильно — ищет agent.py в текущей папке:
cd /root/sidecar && sidecar.py run --env-file /root/generated-agent/.env

# Правильно:
cd /root/generated-agent && sidecar.py run --env-file .env
```

---

## Порт уже занят после ручного запуска

Если сайдкар падает с "Address already in use":
```bash
lsof -i :<PORT> | grep LISTEN
kill -9 <PID>
```

---

## Параллельные запросы в агенте

Сайдкар может запускать несколько инстанций агента одновременно для разных клиентов.
Не используй asyncio.gather() для внешних API с rate limits — это создаст burst.
Делай запросы последовательно внутри одного вызова агента.
"""

def register_gotchas(mcp: FastMCP) -> None:
    @mcp.resource("catallaxy://guide/gotchas")
    def gotchas() -> str:
        return CONTENT
