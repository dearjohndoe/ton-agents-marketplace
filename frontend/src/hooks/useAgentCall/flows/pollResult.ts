import { pollResult } from '../../../lib/agentClient'

export interface PollHandlers {
  onDone: (result: any) => void
  onRefund: (reason: string, refundTx: string) => void
  onError: (message: string) => void
}

export function startPolling(
  endpoint: string,
  jobId: string,
  handlers: PollHandlers,
  intervalMs = 1000,
): () => void {
  const id = setInterval(async () => {
    try {
      const r = await pollResult(endpoint, jobId)
      if (r.status === 'pending') return
      clearInterval(id)
      if (r.status === 'done') handlers.onDone(r.result)
      else if (r.status === 'refunded_out_of_stock')
        handlers.onRefund(r.reason ?? '', r.refundTx ?? '')
      else handlers.onError(r.error ?? 'Error')
    } catch {
      clearInterval(id)
      handlers.onError('Connection lost')
    }
  }, intervalMs)
  return () => clearInterval(id)
}
