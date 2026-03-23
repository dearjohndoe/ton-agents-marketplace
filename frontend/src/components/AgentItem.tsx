import { useState, useEffect, useRef } from 'react'
import { useTonConnectUI, useTonAddress } from '@tonconnect/ui-react'
import { Address } from '@ton/core'
import { invokeAgent, pollResult, fetchQuote, invokePreflight, getConnectionMode, checkGatewayHealth, resolveDownloadUrl } from '../lib/agentClient'
import type { QuoteResult, PaymentRequest, ConnectionMode } from '../lib/agentClient'
import { ResultRenderer } from './ResultRenderer'
import { buildPaymentPayload, bocToMsgHash, buildRatingPayload } from '../lib/crypto'
import type { Agent, AgentRating } from '../types'
import { TESTNET } from '../config'
import { useAgentRating } from '../hooks/useAgentRating'
import { RatingBlock } from './RatingBlock'

interface Props {
  agent: Agent
  rating?: AgentRating
  expanded: boolean
  onToggle: () => void
}

type CallStatus = 'idle' | 'quoting' | 'quoted' | 'paying' | 'invoking' | 'polling' | 'done' | 'error'

function nanoToTon(n: number) {
  const t = n / 1e9
  return t < 0.001 ? t.toExponential(2) : t.toFixed(3).replace(/\.?0+$/, '')
}

const connLabel: Record<ConnectionMode, string> = {
  direct: 'https',
  proxy: 'via proxy',
  insecure: 'http',
}
const connClass: Record<ConnectionMode, string> = {
  direct: 'conn-badge--ok',
  proxy: 'conn-badge--proxy',
  insecure: 'conn-badge--warn',
}
function ConnectionBadge({ mode }: { mode: ConnectionMode }) {
  return <span className={`conn-badge ${connClass[mode]}`} title={
    mode === 'direct' ? 'Direct encrypted connection' :
    mode === 'proxy' ? 'Routed through SSL gateway' : 'Connection is not encrypted'
  }>{connLabel[mode]}</span>
}

function formatAddr(raw: string): string {
  try {
    const friendly = Address.parse(raw).toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
    return `${friendly.slice(0, 7)}…${friendly.slice(-7)}`
  } catch {
    return `${raw.slice(0, 7)}…${raw.slice(-7)}`
  }
}

function friendlyAddr(raw: string): string {
  try {
    return Address.parse(raw).toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
  } catch {
    return raw
  }
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button className="copy-btn" onClick={handleCopy} title="Copy address">
      {copied
        ? <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M2 6.5l3.5 3.5 5.5-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
        : <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><rect x="4.5" y="1" width="7.5" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.3"/><path d="M1 4.5h3m-3 0V12h8V9.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>
      }
    </button>
  )
}

export function AgentItem({ agent, rating, expanded, onToggle }: Props) {
  const [tonConnectUI] = useTonConnectUI()
  const walletAddress = useTonAddress()

  const [fields, setFields] = useState<Record<string, string>>({})
  const [status, setStatus] = useState<CallStatus>('idle')
  const [result, setResult] = useState<any>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [quote, setQuote] = useState<QuoteResult | null>(null)
  const [quoteSecondsLeft, setQuoteSecondsLeft] = useState(0)
  const [reviewScore, setReviewScore] = useState(0)
  const [reviewHover, setReviewHover] = useState(0)
  const [reviewStatus, setReviewStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [lastNonce, setLastNonce] = useState('')
  const [connMode, setConnMode] = useState<ConnectionMode>(() => getConnectionMode(agent.endpoint))
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Re-check gateway health each time the card is expanded
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

  const inputSchema = agent.argsSchema

  function buildBody(): Record<string, string | number | boolean> {
    const body: Record<string, string | number | boolean> = {}
    for (const [k, v] of Object.entries(fields)) {
      const s = inputSchema[k]
      if (!s) continue
      body[k] = s.type === 'number' ? Number(v) : s.type === 'boolean' ? v === 'true' : v
    }
    return body
  }

  async function handleGetQuote(e: React.FormEvent) {
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

  async function handleSubmit(e: React.FormEvent) {
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
      const res = await invokeAgent(agent.endpoint, txBoc, paymentRequest.nonce, agent.capabilities[0] ?? '', body, quote?.quoteId)

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
        }, 2000)
      }
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.response?.data?.error ?? err?.message ?? 'Failed to call agent')
    }
  }

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
      // TODO: decrease when transactions become faster
      setTimeout(() => ratingRefresh(), 8000)
    } catch (err: any) {
      setReviewStatus(err?.message === 'Reject request' ? 'idle' : 'error')
    }
  }

  const busy = status === 'quoting' || status === 'paying' || status === 'invoking' || status === 'polling'
  const hasSchema = Object.keys(inputSchema).length > 0

  const isLive = (Date.now() / 1000 - agent.lastHeartbeat) < 300
  const { rating: onChainRating, loading: ratingLoading, error: ratingError, refresh: ratingRefresh } = useAgentRating(agent.address, agent.sidecarId, expanded)

  return (
    <div className={`agent-item ${expanded ? 'agent-item--open' : ''}`}>
      {/* Row — always visible */}
      <button className="agent-row" onClick={onToggle} aria-expanded={expanded}>
        <div className="agent-row-left">
          <span className="agent-row-name">{agent.name || agent.address.slice(0, 10) + '…'}</span>
          <div className="agent-row-meta">
            {isLive && <span className="agent-live-dot" title="Online" />}
            {agent.capabilities.map(c => <span key={c} className="tag">{c}</span>)}
          </div>
        </div>
        <div className="agent-row-right">
          <span className="agent-row-price">{nanoToTon(agent.price)} TON</span>
          <span className={`chevron ${expanded ? 'chevron--open' : ''}`}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </span>
        </div>
      </button>

      {/* Summary — always visible: compact rating + description */}
      {(onChainRating || ratingLoading || ratingError || agent.description) && (
        <div className="agent-summary" onClick={onToggle}>
          <RatingBlock rating={onChainRating} loading={ratingLoading} error={ratingError} onRefresh={ratingRefresh} />
          {agent.description && <p className="agent-summary-desc">{agent.description}</p>}
        </div>
      )}

      {/* Expanded body */}
      {expanded && (
        <div className="agent-body">
          <div className="agent-body-meta">
            <div className="meta-item">
              <span className="meta-label">Endpoint</span>
              <a href={agent.endpoint} target="_blank" rel="noopener noreferrer" className="link">{agent.endpoint}</a>
              <ConnectionBadge mode={connMode} />
            </div>
            <div className="meta-item">
              <span className="meta-label">Wallet</span>
              <a
                href={`https://${TESTNET ? 'testnet.' : ''}tonviewer.com/${friendlyAddr(agent.address)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="link meta-addr"
              >
                {formatAddr(agent.address)}
              </a>
              <CopyButton text={friendlyAddr(agent.address)} />
            </div>
          </div>

          <div className="agent-divider" />

          {/* Call form */}
          {!walletAddress ? (
            <div className="alert alert-info">Connect your wallet to call this agent.</div>
          ) : status === 'done' && result ? (
            <div className="result-box">
              <span className="meta-label">Result</span>
              <ResultRenderer
                result={result}
                downloadUrl={(path) => resolveDownloadUrl(agent.endpoint, path)}
              />

              {reviewStatus === 'sent' ? (
                <div className="review-done">
                  <span className="review-done-icon">✓</span>
                  <span>Thanks! Your rating is on its way on-chain.</span>
                </div>
              ) : (
                <div className="review-cta">
                  <p className="review-cta-text">
                    Enjoyed the result? Rate this agent to help others discover quality services.
                  </p>
                  <div className="review-stars">
                    {[1, 2, 3, 4, 5].map(s => (
                      <button
                        key={s}
                        type="button"
                        className={`review-star ${s <= (reviewHover || reviewScore) ? 'review-star--active' : ''}`}
                        onMouseEnter={() => setReviewHover(s)}
                        onMouseLeave={() => setReviewHover(0)}
                        onClick={() => setReviewScore(s)}
                        disabled={reviewStatus === 'sending'}
                      >
                        ★
                      </button>
                    ))}
                  </div>
                  {reviewScore > 0 && (
                    <button
                      className="btn btn-review"
                      onClick={handleReview}
                      disabled={reviewStatus === 'sending'}
                    >
                      {reviewStatus === 'sending' ? 'Submitting…' : 'Submit Rating · 0.01 TON'}
                    </button>
                  )}
                  {reviewStatus === 'error' && (
                    <p className="review-error">Failed to submit. Try again?</p>
                  )}
                </div>
              )}

              <button className="btn btn-outline btn-sm" onClick={() => { setStatus('idle'); setResult(null); setQuote(null); setReviewScore(0); setReviewStatus('idle'); setLastNonce('') }}>
                Call again
              </button>
            </div>
          ) : agent.hasQuote ? (
            <form onSubmit={status === 'quoted' ? handleSubmit : handleGetQuote} className="call-form">
              {errorMsg && <div className="alert alert-error">{errorMsg}</div>}

              {hasSchema ? (
                Object.entries(inputSchema).map(([name, arg]) => (
                  <div key={name} className="field">
                    <label>
                      {name}{arg.required && <span className="required">*</span>}
                      {arg.description && <span className="field-desc">{arg.description}</span>}
                    </label>
                    {arg.type === 'boolean' ? (
                      <select value={fields[name] ?? 'false'} disabled={busy}
                        onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))}>
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : (
                      arg.type === 'number' ? (
                        <input type="number"
                          value={fields[name] ?? ''} required={arg.required} disabled={busy || status === 'quoted'}
                          onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
                      ) : (
                        <textarea rows={3}
                          value={fields[name] ?? ''} required={arg.required} disabled={busy || status === 'quoted'}
                          onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
                      )
                    )}
                  </div>
                ))
              ) : (
                <p className="state-msg state-msg--sm">No schema available</p>
              )}

              {status === 'quoted' && quote && (
                <div className="quote-box">
                  {quote.plan && typeof quote.plan === 'object' && 'steps' in quote.plan && (
                    <div className="quote-plan">
                      {quote.plan.steps.map((s, i) => (
                        <div key={i} className="quote-step">
                          <span className="quote-step-num">{s.step + 1}</span>
                          <span className="quote-step-agent">{s.agent}</span>
                          <span className="quote-step-cap">{s.capability}</span>
                          <span className="quote-step-price">{s.price_ton}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {quote.plan && typeof quote.plan === 'string' && quote.plan && (
                    <div className="quote-plan">{quote.plan}</div>
                  )}
                  <div className="quote-meta">
                    <span className="quote-price">{nanoToTon(quote.price)} TON</span>
                    <span className={`quote-timer ${quoteSecondsLeft === 0 ? 'quote-timer--expired' : ''}`}>
                      {quoteSecondsLeft > 0 ? `Expires in ${quoteSecondsLeft}s` : 'Quote expired'}
                    </span>
                  </div>
                </div>
              )}

              {['quoted', 'paying', 'invoking', 'polling'].includes(status) ? (
                <div className="quote-actions">
                  <button type="submit" className="btn btn-primary" disabled={busy || quoteSecondsLeft === 0}>
                    {status === 'paying' ? 'Waiting for payment…'
                      : status === 'invoking' ? 'Calling agent…'
                      : status === 'polling' ? 'Waiting for result…'
                      : quoteSecondsLeft === 0 ? 'Quote expired'
                      : `Approve & Pay ${nanoToTon(quote!.price)} TON`}
                  </button>
                  <button type="button" className="btn btn-outline btn-sm"
                    onClick={() => { setStatus('idle'); setQuote(null) }}>
                    Get new quote
                  </button>
                </div>
              ) : (
                <button type="submit" className="btn btn-primary" disabled={busy}>
                  {status === 'quoting' ? 'Getting quote…' : 'Get Quote'}
                </button>
              )}
            </form>
          ) : (
            <form onSubmit={handleSubmit} className="call-form">
              {errorMsg && <div className="alert alert-error">{errorMsg}</div>}

              {hasSchema ? (
                Object.entries(inputSchema).map(([name, arg]) => (
                  <div key={name} className="field">
                    <label>
                      {name}{arg.required && <span className="required">*</span>}
                      {arg.description && <span className="field-desc">{arg.description}</span>}
                    </label>
                    {arg.type === 'boolean' ? (
                      <select value={fields[name] ?? 'false'} disabled={busy}
                        onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))}>
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : (
                      arg.type === 'number' ? (
                        <input type="number"
                          value={fields[name] ?? ''} required={arg.required} disabled={busy}
                          onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
                      ) : (
                        <textarea rows={3}
                          value={fields[name] ?? ''} required={arg.required} disabled={busy}
                          onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
                      )
                    )}
                  </div>
                ))
              ) : (
                <p className="state-msg state-msg--sm">No schema available</p>
              )}

              <button type="submit" className="btn btn-primary" disabled={busy}>
                {status === 'paying'  ? 'Waiting for payment…'
                  : status === 'invoking' ? 'Calling agent…'
                  : status === 'polling' ? 'Waiting for result…'
                  : `Pay ${nanoToTon(agent.price)} TON & Execute`}
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  )
}
