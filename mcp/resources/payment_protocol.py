from mcp.server.fastmcp import FastMCP

CONTENT = """# HTTP 402 Payment Protocol

## Flow

1. Client POST /invoke {capability, body} (без tx)
2. Sidecar → 402:
   {"error": "Payment required", "payment_request": {"address": "UQ...", "amount": "10000000", "memo": "uuid:sidecar_id"}}
   Headers: x-ton-pay-address, x-ton-pay-amount, x-ton-pay-nonce

3. Client отправляет TON TX:
   - destination: address, amount: amount
   - body: Cell(uint32=0x50415900, string=nonce)

4. Client POST /invoke {tx, nonce, capability, body}
5. Sidecar верифицирует: TX существует, сумма >= price, nonce совпадает, TX не использована
6. Sidecar запускает агента и возвращает результат

## Opcodes

| Opcode | Hex | Назначение |
|--------|-----|-----------|
| Payment | 0x50415900 | Оплата вызова агента |
| Heartbeat | 0xAC52AB67 | Регистрация агента в реестре |
| Refund | 0x52464E44 | Возврат средств при ошибке |
| Rating | 0x52617465 | Оценка агента |

## Quote flow

1. POST /quote {capability, body} → {price, plan, quote_id, ttl}
2. POST /invoke {capability, body, quote_id} → 402 с ценой из quote
3. Оплата и вызов как обычно
"""

def register_payment_protocol(mcp: FastMCP) -> None:
    @mcp.resource("catallaxy://spec/payment-protocol")
    def payment_protocol() -> str:
        return CONTENT
