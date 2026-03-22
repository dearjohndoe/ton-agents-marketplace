import axios from 'axios'
import { SSL_GATEWAY } from '../config'

/**
 * Decides whether to call the agent directly or via ssl-gateway.
 * Direct when:
 *  - frontend itself is on HTTP (local dev)
 *  - agent endpoint is already HTTPS
 * Via gateway when:
 *  - frontend is on HTTPS (TMA / GitHub Pages) AND agent is on HTTP AND gateway is reachable
 */
export type ConnectionMode = 'direct' | 'proxy' | 'insecure'

// Gateway availability flag — updated by checkGatewayHealth()
let _gatewayAvailable = false

export async function checkGatewayHealth(): Promise<void> {
  if (!SSL_GATEWAY) return
  try {
    await axios.get(`${SSL_GATEWAY}/health`, { timeout: 5000 })
    _gatewayAvailable = true
  } catch {
    _gatewayAvailable = false
  }
}

export function getConnectionMode(endpoint: string): ConnectionMode {
  const frontendIsHttps = window.location.protocol === 'https:'
  const agentIsHttps = endpoint.startsWith('https://')

  if (agentIsHttps) return 'direct'
  if (frontendIsHttps && SSL_GATEWAY && _gatewayAvailable) return 'proxy'
  return 'insecure'
}

function resolveUrl(endpoint: string, path: string): { url: string; headers?: Record<string, string> } {
  const mode = getConnectionMode(endpoint)

  if (mode !== 'proxy') {
    return { url: `${endpoint}${path}` }
  }

  return {
    url: `${SSL_GATEWAY}${path}`,
    headers: { 'X-Agent-Endpoint': endpoint },
  }
}

export interface InvokeResult {
  jobId: string
  status: 'done' | 'pending' | 'error'
  result?: any
  error?: string
}

export interface PaymentRequest {
  address: string
  amount: string
  nonce: string
}

export async function invokePreflight(
  endpoint: string,
  capability: string,
  body: Record<string, string | number | boolean>,
  quoteId?: string
): Promise<PaymentRequest> {
  const payload: Record<string, unknown> = { capability, body }
  if (quoteId) payload.quote_id = quoteId

  const { url, headers } = resolveUrl(endpoint, '/invoke')
  try {
    await axios.post(url, payload, { timeout: 90000, headers })
    throw new Error('Expected 402 Payment Required, but got success')
  } catch (err: any) {
    if (err.response?.status === 402 && err.response.data?.payment_request) {
      const pr = err.response.data.payment_request
      return {
        address: pr.address,
        amount: pr.amount,
        nonce: pr.memo,
      }
    }
    throw err?.response?.data?.error ? new Error(err.response.data.error) : err
  }
}

export async function invokeAgent(
  endpoint: string,
  tx: string,
  nonce: string,
  capability: string,
  body: Record<string, string | number | boolean>,
  quoteId?: string
): Promise<InvokeResult> {
  const payload: Record<string, unknown> = { tx, nonce, capability, body }
  if (quoteId) payload.quote_id = quoteId
  const { url, headers } = resolveUrl(endpoint, '/invoke')
  const { data } = await axios.post(url, payload, { timeout: 90000, headers })
  return { jobId: data.job_id, status: data.status, result: data.result, error: data.error }
}

export async function pollResult(endpoint: string, jobId: string): Promise<InvokeResult> {
  const { url, headers } = resolveUrl(endpoint, `/result/${jobId}`)
  const { data } = await axios.get(url, { timeout: 10000, headers })
  return { jobId, status: data.status, result: data.result, error: data.error }
}

export interface QuotePlanStep {
  step: number
  agent: string
  capability: string
  price_ton: string
}

export interface QuotePlan {
  quote_id: string
  steps: QuotePlanStep[]
  orchestrator_fee_ton: string
  network_fees_ton: string
  total_price_ton: string
}

export interface QuoteResult {
  quoteId: string
  price: number
  plan: QuotePlan | string | null
  expiresAt: number
}

export async function fetchQuote(
  endpoint: string,
  capability: string,
  body: Record<string, string | number | boolean>
): Promise<QuoteResult> {
  const { url, headers } = resolveUrl(endpoint, '/quote')
  const { data } = await axios.post(url, { capability, body }, { timeout: 60000, headers })
  return {
    quoteId: data.quote_id,
    price: data.price,
    plan: data.plan,
    expiresAt: data.expires_at,
  }
}
