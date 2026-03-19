export const REGISTRY_ADDRESS = import.meta.env.VITE_REGISTRY_ADDRESS as string
export const TESTNET = import.meta.env.VITE_TESTNET === 'true'
export const TONCENTER_BASE = TESTNET
  ? 'https://testnet.toncenter.com/api/v3'
  : 'https://toncenter.com/api/v3'
export const RATINGS_BACKEND = (import.meta.env.VITE_RATINGS_BACKEND as string) ?? ''

export const CACHE_TTL_MS = import.meta.env.DEV ? 0 : 5 * 60 * 1000
export const AGENTS_PER_PAGE = 20
export const TX_PAGE_SIZE = 100
export const HEARTBEAT_OPCODE = 0xAC52AB67
export const PAYMENT_TIMEOUT_SEC = 300
