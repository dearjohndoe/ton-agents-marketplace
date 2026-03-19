# Sidecar — Implementation Context

## TONCenter API

Base URL: `https://toncenter.com/api/v3`

Key endpoints:
- `GET /transactions?account=<address>&limit=1&sort=desc` — get latest TX to check heartbeat
- `GET /transactions?hash=<tx_hash>` — verify a specific transaction

Docs: https://toncenter.com/api/v3/

## TX Comment Encryption

TON supports encrypted comments in transactions. The caller encrypts the nonce with the agent's public key. The agent decrypts with its private key.

Python libraries:
- `https://github.com/nessshon/tonutils` — may have better support for encryption/decryption.

## Heartbeat scheduling

Use `asyncio` background task:
```python
async def heartbeat_loop():
    while True:
        await send_heartbeat_if_needed()
        await asyncio.sleep(3600)  # check every hour
```

## Subprocess timeout

For sync responses, use a configurable timeout (default 30s). If subprocess doesn't finish in time, switch to async mode (return pending + job_id).
