import axios from 'axios'

export async function fetchSidecarId(endpoint: string): Promise<string | null> {
  try {
    const { data } = await axios.get(`${endpoint}/info`, { timeout: 5000 })
    return data.sidecar_id ?? null
  } catch {
    return null
  }
}

export interface InvokeResult {
  jobId: string
  status: 'done' | 'pending' | 'error'
  result?: any
  error?: string
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
  const { data } = await axios.post(`${endpoint}/invoke`, payload, { timeout: 35000 })
  return { jobId: data.job_id, status: data.status, result: data.result, error: data.error }
}

export async function pollResult(endpoint: string, jobId: string): Promise<InvokeResult> {
  const { data } = await axios.get(`${endpoint}/result/${jobId}`, { timeout: 10000 })
  return { jobId, status: data.status, result: data.result, error: data.error }
}

export interface QuoteResult {
  quoteId: string
  price: number
  plan: string
  expiresAt: number
}

export async function fetchQuote(
  endpoint: string,
  capability: string,
  body: Record<string, string | number | boolean>
): Promise<QuoteResult> {
  const { data } = await axios.post(`${endpoint}/quote`, { capability, body }, { timeout: 35000 })
  return {
    quoteId: data.quote_id,
    price: data.price,
    plan: data.plan,
    expiresAt: data.expires_at,
  }
}
