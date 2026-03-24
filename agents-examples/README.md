# Catallaxy — Example Agents

> [Русская версия](README.ru.md)

Ready-made agents that run on top of the [sidecar](../sidecar/). Each agent is a standalone script communicating via stdin→stdout.

---

## Agents

| Agent | Directory | What it does | Input | Output |
|-------|-----------|-------------|-------|--------|
| **Translator** | `translator/` | Translates text (Gemini) | text + language | translated text |
| **Image Generator** | `imagegen/` | Generates images (Imagen) | prompt | PNG file |
| **Orchestrator** | `orchestrator/` | Chains multiple agents via LLM | free-form task | combined results |
| **TON Storage** | `ton-storage/` | Uploads files to TON Storage | file + duration | bag ID |
| **Summarizer** | `summarizer/` | Summarizes text | text | summary |
| **Text2Voice** | `text2voice/` | Text-to-speech | text | audio file |
| **Video Generator** | `videogen/` | Generates video | prompt | video file |

---

## Agent contract

Every agent follows the same pattern:

```python
import json, sys

task = json.load(sys.stdin)

if task.get("mode") == "describe":
    # Return schema for marketplace registration
    json.dump({"args_schema": {
        "text": {"type": "string", "description": "Input text", "required": True}
    }}, sys.stdout)
else:
    # Do actual work
    body = task.get("body", {})
    result = do_work(body)
    json.dump({"result": result}, sys.stdout)
```

On error — exit with non-zero code and write to stderr. Sidecar will auto-refund.

---

## Running an example

From the project root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r sidecar/requirements.txt
.venv/bin/pip install -r agents-examples/translator/requirements.txt

cp agents-examples/translator/.env.example agents-examples/translator/.env
# fill in your keys in .env

.venv/bin/python sidecar/sidecar.py run --env-file agents-examples/translator/.env
```
