import { useState } from 'react'
import { Address } from '@ton/core'
import { buildRatingPayload } from '../lib/crypto'
import type { Agent } from '../types'
import { TESTNET } from '../config'

export function useAgentReview(
  agent: Agent,
  lastNonce: string,
  tonConnectUI: { sendTransaction: (params: any) => Promise<any> },
  onSubmitted?: () => void,
) {
  const [reviewScore, setReviewScore] = useState(0)
  const [reviewHover, setReviewHover] = useState(0)
  const [reviewStatus, setReviewStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')

  async function handleReview() {
    if (!reviewScore || reviewStatus === 'sending') return
    setReviewStatus('sending')
    try {
      const agentAddr = Address.parse(agent.address).toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
      await tonConnectUI.sendTransaction({
        validUntil: Math.floor(Date.now() / 1000) + 300,
        messages: [{
          address: agentAddr,
          amount: '10000000',
          payload: buildRatingPayload(agent.sidecarId, lastNonce, reviewScore),
        }],
      })
      setReviewStatus('sent')
      if (onSubmitted) setTimeout(onSubmitted, 8000)
    } catch (err: any) {
      setReviewStatus(err?.message === 'Reject request' ? 'idle' : 'error')
    }
  }

  function resetReview() {
    setReviewScore(0)
    setReviewHover(0)
    setReviewStatus('idle')
  }

  return { reviewScore, setReviewScore, reviewHover, setReviewHover, reviewStatus, handleReview, resetReview }
}
