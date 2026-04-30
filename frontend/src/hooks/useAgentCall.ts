import { useState, useEffect, useRef } from 'react'
import type { FormEvent } from 'react'
import { Address, toNano } from '@ton/core'
import { invokeAgent, pollResult, fetchQuote, invokePreflight, getConnectionMode, checkGatewayHealth, fetchAgentInfo } from '../lib/agentClient'
import type { QuoteResult, PaymentRequest, PaymentOption, ConnectionMode } from '../lib/agentClient'
import { buildPaymentPayload, buildJettonTransferPayload, bocToMsgHash, resolveJettonWallet } from '../lib/crypto'
import type { Agent, Sku } from '../types'
import { TESTNET, TONCENTER_BASE } from '../config'

export type CallStatus = 'idle' | 'quoting' | 'quoted' | 'paying' | 'invoking' | 'polling' | 'done' | 'error' | 'refunded_out_of_stock'

export function useAgentCall(
  agent: Agent,
  expanded: boolean,
  tonConnectUI: { sendTransaction: (params: any) => Promise<{ boc: string }>; account?: { address: string } | null },
) {
  const [fields, setFields] = useState<Record<string, string>>({})
  const [fileFields, setFileFields] = useState<Record<string, File>>({})
  const [status, setStatus] = useState<CallStatus>('idle')
  const [result, setResult] = useState<any>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [quote, setQuote] = useState<QuoteResult | null>(null)
  const [quoteSecondsLeft, setQuoteSecondsLeft] = useState(0)
  const [lastNonce, setLastNonce] = useState('')
  const [paymentOptions, setPaymentOptions] = useState<PaymentOption[]>([])
  const [selectedRail, setSelectedRail] = useState<string>(() =>
    agent.price > 0 ? 'TON' : agent.priceUsdt ? 'USDT' : 'TON'
  )
  const [paymentRails, setPaymentRails] = useState<string[]>([])
  const [connMode, setConnMode] = useState<ConnectionMode>(() => getConnectionMode(agent.endpoint))
  const [skus, setSkus] = useState<Sku[]>([])
  const [selectedSkuId, setSelectedSkuId] = useState<string>('')
  const [skusLoading, setSkusLoading] = useState(false)
  const [refundReason, setRefundReason] = useState('')
  const [refundTx, setRefundTx] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!expanded) return
    checkGatewayHealth().then(() => {
      setConnMode(getConnectionMode(agent.endpoint))
    })
  }, [expanded, agent.endpoint])

  const [infoRefreshNonce, setInfoRefreshNonce] = useState(0)
  function refreshInfo() { setInfoRefreshNonce(n => n + 1) }

  useEffect(() => {
    if (!expanded) return
    let cancelled = false
    setSkusLoading(true)
    fetchAgentInfo(agent.endpoint)
      .then(info => {
        if (cancelled) return
        setSkus(info.skus)
        setPaymentRails(info.paymentRails)
        // Reset rail if the current selection isn't supported by this agent.
        if (info.paymentRails.length > 0) {
          setSelectedRail(prev =>
            info.paymentRails.includes(prev) ? prev : (info.paymentRails[0] ?? 'TON')
          )
        }
        // Default selection: first in-stock sku, falling back to first.
        const firstAvail = info.skus.find(s => s.stockLeft == null || s.stockLeft > 0)
        setSelectedSkuId(prev => prev || firstAvail?.id || info.skus[0]?.id || '')
      })
      .catch(() => { if (!cancelled) setSkus([]) })
      .finally(() => { if (!cancelled) setSkusLoading(false) })
    return () => { cancelled = true }
  }, [expanded, agent.endpoint, infoRefreshNonce])

  // Re-pull /info after a sale finalises so stock_left reflects the new state.
  useEffect(() => {
    if (status === 'done' || status === 'refunded_out_of_stock') refreshInfo()
  }, [status])

  const selectedSku: Sku | null = skus.find(s => s.id === selectedSkuId) ?? null

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
      const q = await fetchQuote(agent.endpoint, agent.capabilities[0] ?? '', buildBody(), selectedSkuId || undefined)
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
    let rail = selectedRail
    let preflightOptions: PaymentOption[] = []

    try {
      const preflight = await invokePreflight(agent.endpoint, agent.capabilities[0] ?? '', body, quote?.quoteId, selectedSkuId || undefined)
      paymentRequest = preflight.paymentRequest
      preflightOptions = preflight.paymentOptions
      setPaymentOptions(preflightOptions)

      const chosen = preflightOptions.find(o => o.rail === rail)
      if (!chosen) {
        const available = preflightOptions.map(o => o.rail).join(', ')
        throw new Error(`Rail "${rail}" not offered by agent for this SKU. Available: ${available || 'none'}`)
      }
      rail = chosen.rail
      paymentRequest = { address: chosen.address, amount: chosen.amount, nonce: chosen.memo, rail: chosen.rail }
    } catch (err: any) {
      setStatus('error')
      const data = err?.response?.data
      if (err?.response?.status === 409 && data?.error === 'out_of_stock') {
        setErrorMsg(`Out of stock${data.sku ? ` (${data.sku})` : ''}`)
      } else {
        setErrorMsg(err?.message ?? 'Failed to reach agent')
      }
      return
    }

    setLastNonce(paymentRequest.nonce)

    let txBoc: string
    try {
      if (rail === 'USDT') {
        // Jetton transfer: send to user's USDT jetton wallet
        const usdtOption = paymentRequest
        const userAddr = Address.parse(tonConnectUI.account?.address ?? '').toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
        const usdtPaymentOption = preflightOptions.find(o => o.rail === 'USDT')
        const master = usdtPaymentOption?.token?.master ?? ''
        if (!master) throw new Error('USDT master address not available')

        const userJettonWallet = await resolveJettonWallet(TONCENTER_BASE, master, userAddr)
        const payload = buildJettonTransferPayload(
          usdtOption.address,
          BigInt(usdtOption.amount),
          usdtOption.nonce,
          userAddr,
        )
        const res = await tonConnectUI.sendTransaction({
          validUntil: Math.floor(Date.now() / 1000) + 300,
          messages: [{
            address: userJettonWallet,
            amount: toNano('0.1').toString(),  // gas for jetton transfer
            payload,
          }],
        })
        txBoc = bocToMsgHash(res.boc)
      } else {
        // Native TON transfer
        const recipientAddress = Address.parse(paymentRequest.address).toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
        const res = await tonConnectUI.sendTransaction({
          validUntil: Math.floor(Date.now() / 1000) + 300,
          messages: [{ address: recipientAddress, amount: paymentRequest.amount, payload: buildPaymentPayload(paymentRequest.nonce) }],
        })
        txBoc = bocToMsgHash(res.boc)
      }
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.message === 'Reject request' ? 'Payment cancelled' : 'Payment failed')
      return
    }

    setStatus('invoking')
    try {
      const res = await invokeAgent(agent.endpoint, txBoc, paymentRequest.nonce, agent.capabilities[0] ?? '', body, quote?.quoteId, fileFields, rail, selectedSkuId || undefined)

      if (res.status === 'done') {
        setResult(res.result); setStatus('done')
      } else if (res.status === 'refunded_out_of_stock') {
        setRefundReason(res.reason ?? '')
        setRefundTx(res.refundTx ?? '')
        setStatus('refunded_out_of_stock')
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
              else if (r.status === 'refunded_out_of_stock') {
                setRefundReason(r.reason ?? '')
                setRefundTx(r.refundTx ?? '')
                setStatus('refunded_out_of_stock')
              }
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
    setPaymentOptions([])
    setRefundReason('')
    setRefundTx('')
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
    paymentOptions, selectedRail, setSelectedRail, paymentRails,
    skus, skusLoading, selectedSkuId, setSelectedSkuId, selectedSku,
    refundReason, refundTx,
    busy, hasSchema,
    handleGetQuote, handleSubmit, reset, resetQuote,
  }
}
