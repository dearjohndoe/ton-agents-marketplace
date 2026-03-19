export interface ArgSchema {
  type: 'string' | 'number' | 'boolean'
  description: string
  required: boolean
}

export interface Agent {
  address: string       // sender of heartbeat TX (raw format)
  sidecarId: string     // unique per sidecar instance, used as dedup key
  name: string
  description: string
  capabilities: string[]
  price: number         // nanotons
  endpoint: string
  argsSchema: Record<string, ArgSchema>
  lastHeartbeat: number // unix timestamp
  hasQuote?: boolean
}

export interface AgentRating {
  avgScore: number
  totalRatings: number
}
