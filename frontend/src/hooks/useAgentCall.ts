import { useState, useEffect, useRef } from 'react'
import type { FormEvent } from 'react'
import { Address } from '@ton/core'
import { invokeAgent, pollResult, fetchQuote, invokePreflight, getConnectionMode, checkGatewayHealth } from '../lib/agentClient'
import type { QuoteResult, PaymentRequest, ConnectionMode } from '../lib/agentClient'
import { buildPaymentPayload, bocToMsgHash } from '../lib/crypto'
import type { Agent } from '../types'
import { TESTNET } from '../config'

export type CallStatus = 'idle' | 'quoting' | 'quoted' | 'paying' | 'invoking' | 'polling' | 'done' | 'error'

export function useAgentCall(
  agent: Agent,
  expanded: boolean,
  tonConnectUI: { sendTransaction: (params: any) => Promise<{ boc: string }> },
) {
  const [fields, setFields] = useState<Record<string, string>>({})
  const [fileFields, setFileFields] = useState<Record<string, File>>({})
  const [status, setStatus] = useState<CallStatus>('idle')
  const [result, setResult] = useState<any>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [quote, setQuote] = useState<QuoteResult | null>(null)
  const [quoteSecondsLeft, setQuoteSecondsLeft] = useState(0)
  const [lastNonce, setLastNonce] = useState('')
  const [connMode, setConnMode] = useState<ConnectionMode>(() => getConnectionMode(agent.endpoint))
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!expanded) return
    checkGatewayHealth().then(() => {
      setConnMode(getConnectionMode(agent.endpoint))
    })
  }, [expanded, agent.endpoint])

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (countdownRef.current) clearInterval(countdownRef.current)
    }
  }, [])

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

  function buildBody(): Record<string, string | number | boolean> {
    const body: Record<string, string | number | boolean> = {}
    for (const [k, v] of Object.entries(fields)) {
      const s = agent.argsSchema[k]
      if (!s || s.type === 'file') continue
      body[k] = s.type === 'number' ? Number(v) : s.type === 'boolean' ? v === 'true' : v
    }
    return body
  }

  async function handleGetQuote(e: FormEvent) {
    e.preventDefault()
    setStatus('quoting')
    setErrorMsg('')
    setQuote(null)
    try {
      const q = await fetchQuote(agent.endpoint, agent.capabilities[0] ?? '', buildBody())
      setQuote(q)
      if (q.plan && typeof q.plan === 'object' && 'quote_id' in q.plan) {
        const planQuoteId = (q.plan as { quote_id: string }).quote_id
        setFields(f => ({ ...f, quote_id: planQuoteId }))
      }
      setStatus('quoted')
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.response?.data?.error ?? err?.message ?? 'Failed to get quote')
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setStatus('paying')
    setErrorMsg('')
    setResult(null)

    const body = buildBody()
    let paymentRequest: PaymentRequest

    try {
      paymentRequest = await invokePreflight(agent.endpoint, agent.capabilities[0] ?? '', body, quote?.quoteId)
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.message ?? 'Failed to reach agent')
      return
    }

    setLastNonce(paymentRequest.nonce)

    let txBoc: string
    try {
      const recipientAddress = Address.parse(paymentRequest.address).toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
      const res = await tonConnectUI.sendTransaction({
        validUntil: Math.floor(Date.now() / 1000) + 300,
        messages: [{ address: recipientAddress, amount: paymentRequest.amount, payload: buildPaymentPayload(paymentRequest.nonce) }],
      })
      txBoc = bocToMsgHash(res.boc)
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.message === 'Reject request' ? 'Payment cancelled' : 'Payment failed')
      return
    }

    setStatus('invoking')
    try {
      const res = await invokeAgent(agent.endpoint, txBoc, paymentRequest.nonce, agent.capabilities[0] ?? '', body, quote?.quoteId, fileFields)

      if (res.status === 'done') {
        setResult(res.result); setStatus('done')
      } else if (res.status === 'error') {
        setStatus('error'); setErrorMsg(res.error ?? 'Agent returned an error')
      } else {
        setStatus('polling')
        pollRef.current = setInterval(async () => {
          try {
            const r = await pollResult(agent.endpoint, res.jobId)
            if (r.status !== 'pending') {
              clearInterval(pollRef.current!)
              if (r.status === 'done') { setResult(r.result); setStatus('done') }
              else { setStatus('error'); setErrorMsg(r.error ?? 'Error') }
            }
          } catch { clearInterval(pollRef.current!); setStatus('error'); setErrorMsg('Connection lost') }
        }, 1000)
      }
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.response?.data?.error ?? err?.message ?? 'Failed to call agent')
    }
  }

  const busy = status === 'quoting' || status === 'paying' || status === 'invoking' || status === 'polling'
  const hasSchema = Object.keys(agent.argsSchema).length > 0

  function reset() {
    setStatus('idle')
    setResult(null)
    setQuote(null)
    setLastNonce('')
  }

  function resetQuote() {
    setStatus('idle')
    setQuote(null)
  }

  return {
    fields, setFields,
    fileFields, setFileFields,
    status, result, errorMsg,
    quote, quoteSecondsLeft,
    lastNonce, connMode,
    busy, hasSchema,
    handleGetQuote, handleSubmit, reset, resetQuote,
  }
}
