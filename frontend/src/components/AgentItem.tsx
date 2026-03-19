import { useState, useEffect, useRef } from 'react'
import { useTonConnectUI, useTonAddress } from '@tonconnect/ui-react'
import { Address } from '@ton/core'
import { invokeAgent, pollResult, fetchQuote, fetchSidecarId } from '../lib/agentClient'
import type { QuoteResult } from '../lib/agentClient'
import { generateNonce, buildCommentPayload, bocToMsgHash } from '../lib/crypto'
import type { Agent, AgentRating } from '../types'
import { TESTNET } from '../config'

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

function timeAgo(ts: number) {
  const s = Math.floor(Date.now() / 1000) - ts
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min. ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h. ago`
  return `${Math.floor(s / 86400)} d. ago`
}

export function AgentItem({ agent, rating, expanded, onToggle }: Props) {
  const [tonConnectUI] = useTonConnectUI()
  const walletAddress = useTonAddress()

  const [sidecarId, setSidecarId] = useState<string | null>(null)
  const [fields, setFields] = useState<Record<string, string>>({})
  const [status, setStatus] = useState<CallStatus>('idle')
  const [result, setResult] = useState<any>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [quote, setQuote] = useState<QuoteResult | null>(null)
  const [quoteSecondsLeft, setQuoteSecondsLeft] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    fetchSidecarId(agent.endpoint).then(setSidecarId)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (countdownRef.current) clearInterval(countdownRef.current)
    }
  }, [agent.endpoint])

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

    if (!sidecarId) {
      setStatus('error')
      setErrorMsg('Sidecar ID not loaded yet, please retry')
      return
    }

    const payAmount = quote ? quote.price : agent.price
    const nonce = generateNonce(sidecarId)
    let txBoc: string
    try {
      const recipientAddress = Address.parse(agent.address).toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
      const res = await tonConnectUI.sendTransaction({
        validUntil: Math.floor(Date.now() / 1000) + 300,
        messages: [{ address: recipientAddress, amount: String(payAmount), payload: buildCommentPayload(nonce) }],
      })
      txBoc = bocToMsgHash(res.boc)
    } catch (err: any) {
      setStatus('error')
      setErrorMsg(err?.message === 'Reject request' ? 'Payment cancelled' : 'Payment failed')
      return
    }

    setStatus('invoking')
    try {
      const body = buildBody()
      const res = await invokeAgent(agent.endpoint, txBoc, nonce, agent.capabilities[0] ?? '', body, quote?.quoteId)

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

  const busy = status === 'quoting' || status === 'paying' || status === 'invoking' || status === 'polling'
  const hasSchema = Object.keys(inputSchema).length > 0

  const isLive = (Date.now() / 1000 - agent.lastHeartbeat) < 300

  return (
    <div className={`agent-item ${expanded ? 'agent-item--open' : ''}`}>
      {/* Row — always visible */}
      <button className="agent-row" onClick={onToggle} aria-expanded={expanded}>
        <div className="agent-row-left">
          <span className="agent-row-name">{agent.name || agent.address.slice(0, 10) + '…'}</span>
          <div className="agent-row-meta">
            {isLive && <span className="agent-live-dot" title="Online" />}
            {agent.capabilities.map(c => <span key={c} className="tag">{c}</span>)}
            {rating && <span className="tag tag--gold">★ {rating.avgScore.toFixed(1)}</span>}
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

      {/* Expanded body */}
      {expanded && (
        <div className="agent-body">
          {agent.description && <p className="agent-desc">{agent.description}</p>}

          <div className="agent-body-meta">
            <div className="meta-item">
              <span className="meta-label">Endpoint</span>
              <a href={agent.endpoint} target="_blank" rel="noopener noreferrer" className="link">{agent.endpoint}</a>
            </div>
            <div className="meta-item">
              <span className="meta-label">Last heartbeat</span>
              <span>{timeAgo(agent.lastHeartbeat)}</span>
            </div>
          </div>

          <div className="agent-divider" />

          {/* Call form */}
          {!walletAddress ? (
            <div className="alert alert-info">Connect your wallet to call this agent.</div>
          ) : status === 'done' && result ? (
            <div className="result-box">
              <span className="meta-label">Result</span>
              <pre className="result-content">{typeof result === 'string' ? result : JSON.stringify(result, null, 2)}</pre>
              <button className="btn btn-outline btn-sm" onClick={() => { setStatus('idle'); setResult(null); setQuote(null) }}>
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
                      <input type={arg.type === 'number' ? 'number' : 'text'}
                        value={fields[name] ?? ''} required={arg.required} disabled={busy || status === 'quoted'}
                        onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
                    )}
                  </div>
                ))
              ) : (
                <p className="state-msg state-msg--sm">No schema available</p>
              )}

              {status === 'quoted' && quote && (
                <div className="quote-box">
                  <div className="quote-plan">{quote.plan}</div>
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
                      <input type={arg.type === 'number' ? 'number' : 'text'}
                        value={fields[name] ?? ''} required={arg.required} disabled={busy}
                        onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
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
