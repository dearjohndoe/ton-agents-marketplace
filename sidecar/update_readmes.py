import re
from pathlib import Path

content_en = """
## Agent Integration Contract

Sidecar communicates with your agent via standard input/output streams (stdin -> stdout). This means your agent can be written in any programming language, provided it adheres to the following contract.

### 1. Input (stdin)
When a task is received and paid for, Sidecar will execute the `AGENT_COMMAND` and pipe a JSON object into its **stdin**. The JSON contains the capability and the payload:

```json
{
  "capability": "translate",
  "body": {
    "text": "Hello world",
    "target_language": "ru"
  }
}
```

### 2. Output (stdout)
Once the task is finished, your agent must print a **valid JSON object** to its **stdout** and exit. This will be returned to the client:

```json
{
  "result": "Привет, мир"
}
```

### 3. Errors and Exits (stderr & return code)
- If your agent encounters an error, it must exit with a **non-zero status code** (e.g., `exit(1)`).
- You can print the error message or stack trace to **stderr** (which will be captured and returned to the user or logged).
- If your agent fails or times out, Sidecar will automatically **refund the TON payment** back to the user.
"""

content_ru = """
## Контракт интеграции агента

Sidecar общается с вашим агентом через стандартные потоки ввода/вывода (stdin -> stdout). Это позволяет писать агента на любом языке программирования, главное — соблюдать следующий контракт:

### 1. Входящие данные (stdin)
Когда задача оплачена, Sidecar запускает процесс `AGENT_COMMAND` и передает в его **стандартный поток ввода (stdin)** JSON-строку. Формат:

```json
{
  "capability": "translate",
  "body": {
    "text": "Hello world",
    "target_language": "ru"
  }
}
```

### 2. Результат выполнения (stdout)
После выполнения задачи агент должен вывести **валидный JSON-объект** в свой **стандартный поток вывода (stdout)** и завершить работу. Этот JSON будет возвращен клиенту:

```json
{
  "result": "Привет, мир"
}
```

### 3. Ошибки (stderr и коды возврата)
- В случае ошибки агент должен завершиться с **ненулевым кодом** (например, `exit(1)`).
- Текст ошибки или логи сбоя следует писать в **стандартный поток ошибок (stderr)** — сайдкар перехватит его.
- Если агент завершился с ошибкой или превысил лимит по времени, Sidecar **автоматически вернет средства** (refund) пользователю.
"""

def insert_before(file_path_str, block, target_phrase):
    p = Path(file_path_str)
    if not p.exists(): return
    content = p.read_text(encoding="utf-8")
    if "stdin -> stdout" in content or "stdin→stdout" in content and "Контракт интеграции" in content:
        return # already inserted
    
    parts = content.split("## Setting up .env")
    if len(parts) == 2:
        new_content = parts[0] + block + "\n## Setting up .env" + parts[1]
        p.write_text(new_content, encoding="utf-8")
        print(f"Updated {file_path_str}")
        return
        
    parts_ru = content.split("## Настройка .env")
    if len(parts_ru) == 2:
        new_content = parts_ru[0] + block + "\n## Настройка .env" + parts_ru[1]
        p.write_text(new_content, encoding="utf-8")
        print(f"Updated {file_path_str}")

insert_before("/media/second_disk/cont5/sidecar/README.md", content_en, "## Setting up .env")
insert_before("/media/second_disk/cont5/sidecar/README.ru.md", content_ru, "## Настройка .env")
insert_before("/media/second_disk/cont5/sidecar/README_RU.md", content_ru, "## Настройка .env")

