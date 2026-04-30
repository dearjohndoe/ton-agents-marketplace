export const PAYMENT_TIMEOUT_MS = 60_000
export const QUOTE_TTL_MS = 120_000
export const FAKE_REFUND_TX = () => 'mockrefund_' + Math.random().toString(16).slice(2, 10)
export const PERSIST_KEY = 'mock-backend-state-v1'
