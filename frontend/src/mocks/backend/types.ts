// public — consumed by fixtures/handlers
export type AgentBehavior =
  | { kind: 'success'; result: any; delayMs?: number }
  | { kind: 'error'; message: string; delayMs?: number }
  | { kind: 'out_of_stock'; reason: string; delayMs?: number }
  | { kind: 'timeout'; delayMs?: number } // never finishes

export interface SkuFixture {
  id: string
  title?: string
  priceTon?: number
  priceUsdt?: number
  initialStock: number | null // null = infinite
}

export interface SidecarFixture {
  sidecarId: string
  endpoint: string
  agent: {
    address: string
    wallet?: string
    name: string
    description: string
    capabilities: string[]
    argsSchema: Record<string, any>
    resultSchema?: any
    hasQuote?: boolean
    previewUrl?: string
    avatarUrl?: string
    images?: string[]
  }
  paymentRails: Array<'TON' | 'USDT'>
  behavior: (req: { skuId: string; body: any; nonce: string }) => AgentBehavior
  quotePrice?: (req: { skuId: string; body: any }) => {
    price: number
    price_usdt?: number
    plan?: any
    note?: string
    ttl?: number
  }
  skus: SkuFixture[]
}

// internal — exported only so AgentState/MockSidecarBackend can share
export interface SkuState {
  id: string
  title?: string
  priceTon?: number
  priceUsdt?: number
  total: number | null
  sold: number
}

export interface Reservation {
  key: string
  skuId: string
  expiresAt: number
  jobId?: string
}

export interface QuoteEntry {
  quoteId: string
  skuId: string
  price: number
  priceUsdt?: number
  expiresAt: number
  plan?: any
  note?: string
}

export interface JobRecord {
  jobId: string
  reservationKey: string
  finishAt: number
  outcome: AgentBehavior
  result?: any
  status: 'pending' | 'done' | 'error' | 'refunded_out_of_stock'
  error?: string
  reason?: string
  refundTx?: string
}

export interface PersistedSkuState {
  id: string
  total: number | null
  sold: number
}

export interface PersistedAgentState {
  sidecarId: string
  skus: PersistedSkuState[]
}
