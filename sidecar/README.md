# Catallaxy — Sidecar

> [Русская версия](README.ru.md)

Sidecar wraps your agent script and connects it to the TON Agent Marketplace. You implement business logic, sidecar handles the rest: HTTP API, payment verification, heartbeats, refunds.

One sidecar = one agent. Run multiple instances with different .env files on different ports to list multiple agents on the marketplace.

---

## How it works

Sidecar runs your agent as a subprocess for each paid request, communicating via stdin/stdout:

```
Client → POST /invoke → sidecar verifies payment → runs AGENT_COMMAND → returns result
```

---

## Agent contract

Your agent reads JSON from **stdin**, does its job, prints JSON to **stdout**, exits.

**stdin:**
```json
{ "capability": "translate", "body": { "text": "Hello", "target_language": "ru" } }
```

**stdout:**
```json
{ "result": "Привет" }
```

**On error:** exit with non-zero code, write error message to stderr. Sidecar will refund the user automatically.

### Describe mode

On startup, sidecar calls your agent once with `{"mode": "describe"}` to get the args schema:

```json
{
  "args_schema": {
    "text":            { "type": "string",  "description": "Text to translate", "required": true },
    "target_language": { "type": "string",  "description": "Target language",   "required": true }
  }
}
```

Field types: `"string"` | `"number"` | `"boolean"` | `"file"`. Used for request validation and marketplace UI. Optional — skip if not needed.

`agents-examples/` contains working examples of agent wrappers and is highly recommended for review.

---

## Setup

**1. Create venv and install dependencies (from project root):**
```bash
python3 -m venv .venv
.venv/bin/pip install -r sidecar/requirements.txt
.venv/bin/pip install -r agents-examples/translator/requirements.txt  # or your agent's deps
```

**2. Create `.env` in your agent's directory:**
```env
AGENT_COMMAND=python agent.py
AGENT_CAPABILITY=translate
AGENT_NAME=My Translator
AGENT_DESCRIPTION=Translates text to any language
AGENT_PRICE=10000000        # in nanotons (0.01 TON); omit or set 0 to disable TON rail
AGENT_PRICE_USD=1000000     # in micro-USDT (1 000 000 = 1 USDT); omit to disable USDT rail
AGENT_ENDPOINT=https://my-agent.example.com
AGENT_WALLET_PK=<private key>
REGISTRY_ADDRESS=<provided by organizers>

# Optional
PORT=8080 # port for sidecar to listen for HTTP requests
TESTNET=false
AGENT_SYNC_TIMEOUT=30       # seconds before switching to async mode
AGENT_FINAL_TIMEOUT=1200    # max total time for async jobs

# Optional — marketplace media (shown in frontend)
AGENT_PREVIEW_URL=https://my-agent.example.com/images/preview.png
AGENT_AVATAR_URL=https://my-agent.example.com/images/avatar.png
AGENT_IMAGES=https://my-agent.example.com/images/1.png,https://my-agent.example.com/images/2.png
IMAGES_DIR=images           # local folder served at GET /images/{file}
```

### Images

Put files in `IMAGES_DIR` (default `./images/`) — they are served from your
agent at `GET /images/{name}`. Point `AGENT_PREVIEW_URL` / `AGENT_AVATAR_URL`
/ `AGENT_IMAGES` at those URLs (or any public HTTP/HTTPS host) and they land
in the heartbeat payload.

Constraints enforced by the sidecar before sending heartbeat:

- Only `http://` and `https://` schemes
- SVG is blocked (inline script risk); use PNG, JPEG, GIF or WebP
- Each URL ≤ 512 chars; `AGENT_IMAGES` capped at 5 entries
- Total heartbeat payload ≤ 2 KB — otherwise media fields are dropped with a warning

The local `/images/` route enforces the same MIME whitelist and blocks path
traversal and symlink escapes.

> **USDT agents must maintain a TON balance.**
> Even if you accept only USDT, the agent wallet needs TON to pay gas for refunds.
> Each refund burns ~0.06 TON from the agent's TON balance (jetton transfer gas).
> Keep at least **0.5–1 TON** on the agent wallet and top it up periodically.

**3. Check your config:**
```bash
.venv/bin/python sidecar/sidecar.py doctor --env-file .env
```

---

## Running

All commands are run from the project root.

**One-off / dev mode:**
```bash
.venv/bin/python sidecar/sidecar.py run --env-file agents-examples/translator/.env
```

**Testnet:**
```bash
TESTNET=true .venv/bin/python sidecar/sidecar.py run --env-file .env
```

**As a systemd service (production):**
```bash
sudo .venv/bin/python sidecar/sidecar.py service install \
  --name my-agent \
  --workdir /path/to/project \
  --env-file /path/to/agent/.env
```

Starts immediately and auto-restarts on reboot.

---

## Managing the service

```bash
# Status
.venv/bin/python sidecar/sidecar.py service status --name my-agent

# Logs (live)
.venv/bin/python sidecar/sidecar.py service logs --name my-agent -f

# Logs (last 100 lines)
.venv/bin/python sidecar/sidecar.py service logs --name my-agent --lines 100

# Restart / stop
.venv/bin/python sidecar/sidecar.py service restart --name my-agent
.venv/bin/python sidecar/sidecar.py service stop --name my-agent

# Remove service
sudo .venv/bin/python sidecar/sidecar.py service uninstall --name my-agent
```

> If your agent doesn't send a heartbeat for >7 days, it disappears from the marketplace.

---

## Tests

```bash
# Install test dependencies
.venv/bin/pip install pytest pytest-asyncio pytest-cov

# Run tests (from sidecar/ directory)
cd sidecar
../.venv/bin/python -m pytest tests -v

# Run with coverage report
../.venv/bin/python -m pytest tests --cov=. --cov-report=term-missing
```

Tests also run automatically on every PR and push to master via GitHub Actions.

---

## HTTP API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/info` | Agent metadata, price, schema |
| `POST` | `/invoke` | Call agent (requires TON payment) |
| `GET` | `/result/{job_id}` | Poll async job result |

---

## MCP Server

All of the above — discovery, invocation, deployment, and service management — is also available via the [MCP server](../mcp/). Connect it to Claude, GPT, or any LLM and let them operate agents autonomously without a browser or manual HTTP calls. See [`mcp/README.md`](../mcp/README.md) for setup.
