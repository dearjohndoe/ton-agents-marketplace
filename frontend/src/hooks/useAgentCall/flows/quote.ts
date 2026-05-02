import { fetchQuote } from '../../../lib/agentClient'
import type { QuoteResult } from '../../../lib/agentClient'
import type { FlowResult } from '../types'

export async function runQuote(args: {
  endpoint: string
  capability: string
  body: Record<string, string | number | boolean>
  skuId?: string
}): Promise<FlowResult<QuoteResult>> {
  try {
    const q = await fetchQuote(args.endpoint, args.capability, args.body, args.skuId)
    return { kind: 'ok', value: q }
  } catch (err: any) {
    return {
      kind: 'error',
      message: err?.response?.data?.error ?? err?.message ?? 'Failed to get quote',
    }
  }
}
