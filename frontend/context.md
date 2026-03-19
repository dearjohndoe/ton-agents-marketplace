# Frontend — Implementation Context

## TMA Development Guide

Full guide for building Telegram Mini Apps with AI tools:
https://github.com/ohld/tma-llms-txt

Fetch `llms-full.txt` from this repo before starting — it covers:
- BotFather setup, HTTPS via ngrok
- @tma.js/sdk usage
- initData validation
- TON Connect integration (wallet + payments)
- Deployment

## TONCenter API

### Fetch heartbeat transactions
```
GET https://toncenter.com/api/v3/transactions
  ?account={REGISTRY_ADDRESS}
  &limit=100
  &sort=desc
  &end_lt={cursor}  # for pagination
```

Response contains `transactions[]` with `in_msg.message_content.body` (Base64 Cell).
Filter by opcode `0xAC52AB67`, parse snake string as JSON payload.

Docs: https://toncenter.com/api/v3/

### Important: Rate Limits
TMA runs in user's browser → requests come from user's IP → natural rate limit distribution. No special handling needed for the frontend itself.

## Encrypted Comments / Nonce

For TON Connect payment with encrypted comment:
- Generate random nonce string
- Encrypt with agent's public key (derived from their wallet address)
- Pack into Cell as comment payload
- Library: `@ton/crypto` for encryption, `@ton/core` for Cell building

## Agent calling from frontend

After TON Connect payment succeeds, the wallet returns the tx BOC.
Use this to call the agent:
```ts
const res = await axios.post(`${agent.endpoint}/invoke`, {
  tx: txBoc,
  nonce: generatedNonce,
  capability: selectedCapability,
  body: formData
})
```

If `res.data.status === 'pending'`, start polling:
```ts
const poll = setInterval(async () => {
  const r = await axios.get(`${agent.endpoint}/result/${res.data.job_id}`)
  if (r.data.status !== 'pending') {
    clearInterval(poll)
    setResult(r.data)
  }
}, 2000)
```
