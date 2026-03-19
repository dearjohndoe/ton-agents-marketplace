import axios from 'axios'


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

  try {
    await axios.post(`${endpoint}/invoke`, payload, { timeout: 35000 })
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
