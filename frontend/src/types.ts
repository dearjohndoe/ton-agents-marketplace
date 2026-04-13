export interface ArgSchema {
  type: 'string' | 'number' | 'boolean' | 'file'
  description: string
  required: boolean
}

export type ResultType = 'string' | 'int' | 'float' | 'file' | 'url' | 'bagid' | 'json'

export interface ResultSchema {
  type: ResultType
  mime_type?: string
  encoding?: string
}

export interface TypedResult {
  type: ResultType
  data: any
  url?: string
  mime_type?: string
  file_name?: string
  expires_in?: number
}

export interface Agent {
  address: string       // sender of heartbeat TX (raw format)
  sidecarId: string     // unique per sidecar instance, used as dedup key
  name: string
  description: string
  capabilities: string[]
  price: number         // nanotons
  priceUsdt?: number    // micro-USDT (6 decimals)
  endpoint: string
  argsSchema: Record<string, ArgSchema>
  lastHeartbeat: number // unix timestamp
  hasQuote?: boolean
  resultSchema?: ResultSchema
}

