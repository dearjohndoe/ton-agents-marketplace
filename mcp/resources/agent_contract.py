from mcp.server.fastmcp import FastMCP

CONTENT = """# Agent Contract — stdin/stdout

Агент Catallaxy — любой исполняемый файл (Python, Node, Go, Rust, bash), который:
- Читает JSON из stdin
- Пишет JSON в stdout
- При ошибке — пишет в stderr и завершается с exit code != 0

## Режимы

### 1. describe (обязательный)

stdin: {"mode": "describe"}
stdout:
  {
    "args_schema": <см. форматы ниже>,
    "result_schema": {"type": "string | file | json | bagid | url", "mime_type": "image/png"}
  }

Таймаут: 3 сек.

#### Форматы args_schema

Поддерживается два формата — оба работают:

Плоский (legacy):
  {
    "field_name": {
      "type": "string | number | boolean | file",
      "description": "Human-readable description",
      "required": true
    }
  }

JSON Schema (рекомендуется, генерируется scaffold_agent):
  {
    "type": "object",
    "required": ["field_name"],
    "properties": {
      "field_name": {
        "type": "string",
        "description": "Human-readable description"
      }
    }
  }

### 2. execute (обязательный)

stdin: {"capability": "translate", "body": {"text": "Hello", "target_language": "ru"}}
stdout (string): {"result": {"type": "string", "data": "Привет"}}
stdout (file): {"result": {"type": "file", "data": "<base64>", "mime_type": "image/png", "file_name": "output.png"}}
stdout (json): {"result": {"type": "json", "data": {"key": "value"}}}

Таймаут: AGENT_FINAL_TIMEOUT (default 1200 сек).

### 3. quote (опциональный, AGENT_HAS_QUOTE=true)

Вызывается перед оплатой — агент возвращает актуальную цену на основе аргументов.
Клиент видит цену и plan до того как отправит TON.

stdin:  {"mode": "quote", "capability": "buy_stars", "body": {"stars_count": 100}}
stdout: {"price": 150000000, "plan": "100 stars for @user — 0.15 TON", "ttl": 300}

- price: цена в nanoTON (обязательно целое > 0)
- plan: строка для отображения пользователю (что будет сделано за эти деньги)
- ttl: время жизни квоты в секундах (сайдкар хранит и использует при вызове)

exit code != 0 в quote mode → клиент получает ошибку, платёж не инициируется.

## Ошибки

- stderr + exit code != 0 → сайдкар авто-рефанд клиенту
- Причины: timeout, invalid_response, execution_failed, internal_error
- Сумма рефанда = оплата - 0.0005 TON (газ на возврат)
"""

def register_agent_contract(mcp: FastMCP) -> None:
    @mcp.resource("catallaxy://spec/agent-contract")
    def agent_contract() -> str:
        """stdin/stdout контракт агента: режимы describe / execute / quote, форматы ответов, обработка ошибок."""
        return CONTENT
