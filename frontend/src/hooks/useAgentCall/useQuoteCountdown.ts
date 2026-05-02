import { useEffect } from 'react'
import type { MutableRefObject } from 'react'
import type { QuoteResult } from '../../lib/agentClient'
import type { CallStatus } from './types'

export function useQuoteCountdown(
  status: CallStatus,
  quote: QuoteResult | null,
  setQuoteSecondsLeft: (n: number) => void,
  countdownRef: MutableRefObject<ReturnType<typeof setInterval> | null>,
) {
  useEffect(() => {
    if (status !== 'quoted' || !quote) return
    const update = () => {
      const left = Math.max(0, quote.expiresAt - Math.floor(Date.now() / 1000))
      setQuoteSecondsLeft(left)
    }
    update()
    countdownRef.current = setInterval(update, 1000)
    return () => { if (countdownRef.current) clearInterval(countdownRef.current) }
  }, [status, quote])
}
