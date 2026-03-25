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
    "args_schema": {
      "field_name": {
        "type": "string | number | boolean | file",
        "description": "Human-readable description",
        "required": true | false
      }
    },
    "result_schema": {"type": "string | file | json | bagid | url", "mime_type": "image/png"}
  }

Таймаут: 3 сек.

### 2. execute (обязательный)

stdin: {"capability": "translate", "body": {"text": "Hello", "target_language": "ru"}}
stdout (string): {"result": {"type": "string", "data": "Привет"}}
stdout (file): {"result": {"type": "file", "data": "<base64>", "mime_type": "image/png", "file_name": "output.png"}}
stdout (json): {"result": {"type": "json", "data": {"key": "value"}}}

Таймаут: AGENT_FINAL_TIMEOUT (default 1200 сек).

### 3. quote (опциональный, AGENT_HAS_QUOTE=true)

stdin: {"mode": "quote", "capability": "orchestrate", "body": {"task": "..."}}
stdout: {"price": 150000000, "plan": "Step 1...", "ttl": 300}

## Ошибки

- stderr + exit code != 0 → сайдкар авто-рефанд клиенту
- Причины: timeout, invalid_response, execution_failed, internal_error
- Сумма рефанда = оплата - 0.0005 TON
"""

def register_agent_contract(mcp: FastMCP) -> None:
    @mcp.resource("catallaxy://spec/agent-contract")
    def agent_contract() -> str:
        return CONTENT
