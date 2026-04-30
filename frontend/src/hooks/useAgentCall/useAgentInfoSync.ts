import { useEffect } from 'react'
import { fetchAgentInfo } from '../../lib/agentClient'
import type { CallState } from './useCallState'

export function useAgentInfoSync(endpoint: string, expanded: boolean, s: CallState) {
  useEffect(() => {
    if (!expanded) return
    let cancelled = false
    s.setSkusLoading(true)
    fetchAgentInfo(endpoint)
      .then(info => {
        if (cancelled) return
        s.setSkus(info.skus)
        s.setPaymentRails(info.paymentRails)
        if (info.paymentRails.length > 0) {
          s.setSelectedRail(prev =>
            info.paymentRails.includes(prev) ? prev : (info.paymentRails[0] ?? 'TON')
          )
        }
        const firstAvail = info.skus.find(sk => sk.stockLeft == null || sk.stockLeft > 0)
        s.setSelectedSkuId(prev => prev || firstAvail?.id || info.skus[0]?.id || '')
      })
      .catch(() => { if (!cancelled) s.setSkus([]) })
      .finally(() => { if (!cancelled) s.setSkusLoading(false) })
    return () => { cancelled = true }
  }, [expanded, endpoint, s.infoRefreshNonce])

  useEffect(() => {
    if (s.status === 'done' || s.status === 'refunded_out_of_stock') {
      s.setInfoRefreshNonce(n => n + 1)
    }
  }, [s.status])

  useEffect(() => {
    return () => {
      s.pollCancelRef.current?.()
      if (s.countdownRef.current) clearInterval(s.countdownRef.current)
    }
  }, [])
}
