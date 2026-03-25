from mcp.server.fastmcp import FastMCP

CONTENT = """# Создание агента для Catallaxy — пошаговое руководство

## 1. Scaffold

Используй tool `scaffold_agent` с параметрами:
- name: kebab-case имя (my-translator)
- capability: одно слово (translate)
- description: описание для маркетплейса
- price: цена в nanoTON (10000000 = 0.01 TON)
- args_schema: схема аргументов
- result_type: string | file | json | bagid | url

## 2. Реализуй логику

Открой agents-examples/{name}/agent.py и заполни секцию YOUR LOGIC HERE.

## 3. Создай .env

Скопируй .env.example в .env и заполни:
- AGENT_WALLET_PK — приватный ключ кошелька (hex)
- REGISTRY_ADDRESS — адрес реестра Catallaxy
- AGENT_ENDPOINT — публичный URL где будет доступен сайдкар

## 4. Проверь конфиг через doctor

```bash
sidecar.py doctor --env-file .env
```

Запускает describe-mode агента и проверяет что .env корректен. Запускай перед деплоем.

## 5. Протестируй

Используй tool `test_agent`:
- agent_dir: путь к директории агента
- test_body: тестовые аргументы

## 6. Валидируй

Используй tool `validate_agent` — проверит все обязательные параметры.

## 7. Деплой

Используй tool `deploy_agent` — установит и запустит systemd сервис.

ВАЖНО: флаг `--name` должен стоять ДО subcommand:
```bash
# Правильно:
sidecar.py service --name my-agent install

# Неправильно (ошибка):
sidecar.py service install --name my-agent
```

## 8. Мониторинг

- `agent_status` — статус сервиса
- `agent_logs` — логи
- `stop_agent` — остановить

## Архитектура агента (stdin/stdout)

Агент читает JSON из stdin и пишет JSON в stdout.
При ошибке — пишет в stderr и завершается с exit code != 0.
Сайдкар автоматически делает refund при ошибке агента.
"""

def register_create_guide(mcp: FastMCP) -> None:
    @mcp.resource("catallaxy://guide/create-agent")
    def create_guide() -> str:
        return CONTENT
