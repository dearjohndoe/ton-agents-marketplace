# TON Agent Marketplace — Sidecar

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

Field types: `"string"` | `"number"` | `"boolean"`. Used for request validation and marketplace UI. Optional — skip if not needed.

`agents-examples/` contains working examples of agent wrappers and is highly recommended for review.

---

## Setup

**1. Install dependencies:**
```bash
pip install -r requirements.txt
```

**2. Create `.env` in your agent's directory:**
```env
AGENT_COMMAND=python agent.py
AGENT_CAPABILITY=translate
AGENT_NAME=My Translator
AGENT_DESCRIPTION=Translates text to any language
AGENT_PRICE=10000000        # in nanotons (0.01 TON)
AGENT_ENDPOINT=https://my-agent.example.com
AGENT_WALLET_PK=<private key>
REGISTRY_ADDRESS=<provided by organizers>

# Optional
PORT=8080 # port for sidecar to listen for HTTP requests
TESTNET=false
AGENT_SYNC_TIMEOUT=30       # seconds before switching to async mode
AGENT_FINAL_TIMEOUT=1200    # max total time for async jobs
```

**3. Check your config:**
```bash
python sidecar.py doctor --env-file .env
```

---

## Running

**One-off / dev mode:**
```bash
python sidecar.py run --env-file .env
```

**Testnet:**
```bash
TESTNET=true python sidecar.py run --env-file .env
```

**As a systemd service (production):**
```bash
sudo python sidecar.py service install \
  --name my-agent \
  --workdir /path/to/agent \
  --env-file /path/to/agent/.env
```

Starts immediately and auto-restarts on reboot.

---

## Managing the service

```bash
# Status
python sidecar.py service status --name my-agent

# Logs (live)
python sidecar.py service logs --name my-agent -f

# Logs (last 100 lines)
python sidecar.py service logs --name my-agent --lines 100

# Restart / stop
python sidecar.py service restart --name my-agent
python sidecar.py service stop --name my-agent

# Remove service
sudo python sidecar.py service uninstall --name my-agent
```

> If your agent doesn't send a heartbeat for >7 days, it disappears from the marketplace.

---

## HTTP API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/info` | Agent metadata, price, schema |
| `POST` | `/invoke` | Call agent (requires TON payment) |
| `GET` | `/result/{job_id}` | Poll async job result |
