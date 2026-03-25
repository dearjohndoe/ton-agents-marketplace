import { useState } from 'react'
import { useTonConnectUI, useTonAddress } from '@tonconnect/ui-react'
import { Address } from '@ton/core'
import { resolveDownloadUrl } from '../lib/agentClient'
import type { ConnectionMode } from '../lib/agentClient'
import { ResultRenderer } from './ResultRenderer'
import type { Agent, ArgSchema } from '../types'
import { TESTNET } from '../config'
import { useAgentRating } from '../hooks/useAgentRating'
import { useAgentCall } from '../hooks/useAgentCall'
import { useAgentReview } from '../hooks/useAgentReview'
import { useAgentOnline } from '../hooks/useAgentOnline'
import { RatingBlock } from './RatingBlock'

interface Props {
  agent: Agent
  expanded: boolean
  onToggle: () => void
}

function nanoToTon(n: number) {
  const t = n / 1e9
  return t < 0.001 ? t.toExponential(2) : t.toFixed(3).replace(/\.?0+$/, '')
}

const connLabel: Record<ConnectionMode, string> = {
  direct: 'https', proxy: 'via proxy', insecure: 'http',
}
const connClass: Record<ConnectionMode, string> = {
  direct: 'conn-badge--ok', proxy: 'conn-badge--proxy', insecure: 'conn-badge--warn',
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

function InputFields({ schema, fields, setFields, setFileFields, disabled }: {
  schema: Record<string, ArgSchema>
  fields: Record<string, string>
  setFields: React.Dispatch<React.SetStateAction<Record<string, string>>>
  setFileFields: React.Dispatch<React.SetStateAction<Record<string, File>>>
  disabled: boolean
}) {
  if (Object.keys(schema).length === 0) {
    return <p className="state-msg state-msg--sm">No schema available</p>
  }
  return <>
    {Object.entries(schema).map(([name, arg]) => (
      <div key={name} className="field">
        <label>
          <span>{name}{arg.required && <span className="required">*</span>}</span>
          {arg.description && <span className="field-desc">{arg.description}</span>}
        </label>
        {arg.type === 'file' ? (
          <input type="file" disabled={disabled}
            onChange={e => {
              const f = e.target.files?.[0]
              if (f) {
                setFileFields(prev => ({ ...prev, [name]: f }))
                if ('file_name' in schema) {
                  setFields(prev => ({ ...prev, file_name: f.name }))
                }
              }
            }}
          />
        ) : arg.type === 'boolean' ? (
          <select value={fields[name] ?? 'false'} disabled={disabled}
            onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : arg.type === 'number' ? (
          <input type="number"
            value={fields[name] ?? ''} required={arg.required} disabled={disabled}
            onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
        ) : (
          <textarea rows={3}
            value={fields[name] ?? ''} required={arg.required} disabled={disabled}
            onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
        )}
      </div>
    ))}
  </>
}

export function AgentItem({ agent, expanded, onToggle }: Props) {
  const [tonConnectUI] = useTonConnectUI()
  const walletAddress = useTonAddress()

  const call = useAgentCall(agent, expanded, tonConnectUI)
  const { rating: onChainRating, loading: ratingLoading, error: ratingError, refresh: ratingRefresh } = useAgentRating(agent.address, agent.sidecarId, expanded)
  const review = useAgentReview(agent, call.lastNonce, tonConnectUI, ratingRefresh)
  const { online, pinging, recheck } = useAgentOnline(agent.endpoint, expanded)

  function handleReset() {
    call.reset()
    review.resetReview()
  }

  const inQuoteFlow = agent.hasQuote && ['quoted', 'paying', 'invoking', 'polling'].includes(call.status)
  const fieldsDisabled = call.busy || (agent.hasQuote === true && call.status === 'quoted')

  return (
    <div className={`agent-item ${expanded ? 'agent-item--open' : ''}`}>
      {/* Row — always visible */}
      <button className="agent-row" onClick={onToggle} aria-expanded={expanded}>
        <div className="agent-row-left">
          <span className="agent-row-name">{agent.name || agent.address.slice(0, 10) + '…'}</span>
          <div className="agent-row-meta">
            {online === true && !pinging && <span className="tag" style={{color: 'var(--success)', borderColor: 'var(--success)'}}>online</span>}
            {online === false && !pinging && <span className="agent-offline-badge">offline</span>}
            {pinging && <span className="tag">…</span>}
            {agent.capabilities.map(c => <span key={c} className="tag">{c}</span>)}
          </div>
        </div>
        <div className="agent-row-right">
          <span className="agent-row-price">{agent.hasQuote ? `from ${nanoToTon(agent.price)} TON` : `${nanoToTon(agent.price)} TON`}</span>
          <span className={`chevron ${expanded ? 'chevron--open' : ''}`}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </span>
        </div>
      </button>

      {/* Summary — always visible */}
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
              <ConnectionBadge mode={call.connMode} />
            </div>
            <div className="meta-item">
              <span className="meta-label">Wallet</span>
              <a
                href={`https://${TESTNET ? 'testnet.' : ''}tonviewer.com/${friendlyAddr(agent.address)}`}
                target="_blank" rel="noopener noreferrer" className="link meta-addr"
              >
                {formatAddr(agent.address)}
              </a>
              <CopyButton text={friendlyAddr(agent.address)} />
            </div>
          </div>

          <div className="agent-divider" />

          {!walletAddress ? (
            <div className="alert alert-info">Connect your wallet to call this agent.</div>
          ) : call.status === 'done' && call.result ? (
            <div className="result-box">
              <span className="meta-label">Result</span>
              <ResultRenderer result={call.result} downloadUrl={(path) => resolveDownloadUrl(agent.endpoint, path)} />

              {review.reviewStatus === 'sent' ? (
                <div className="review-done">
                  <span className="review-done-icon">✓</span>
                  <span>Thanks! Your rating is on its way on-chain.</span>
                </div>
              ) : (
                <div className="review-cta">
                  <p className="review-cta-text">Enjoyed the result? Rate this agent to help others discover quality services.</p>
                  <div className="review-stars">
                    {[1, 2, 3, 4, 5].map(s => (
                      <button key={s} type="button"
                        className={`review-star ${s <= (review.reviewHover || review.reviewScore) ? 'review-star--active' : ''}`}
                        onMouseEnter={() => review.setReviewHover(s)}
                        onMouseLeave={() => review.setReviewHover(0)}
                        onClick={() => review.setReviewScore(s)}
                        disabled={review.reviewStatus === 'sending'}>
                        ★
                      </button>
                    ))}
                  </div>
                  {review.reviewScore > 0 && (
                    <button className="btn btn-review" onClick={review.handleReview} disabled={review.reviewStatus === 'sending'}>
                      {review.reviewStatus === 'sending' ? 'Submitting…' : 'Submit Rating · 0.01 TON'}
                    </button>
                  )}
                  {review.reviewStatus === 'error' && (
                    <p className="review-error">Failed to submit. Try again?</p>
                  )}
                </div>
              )}

              <button className="btn btn-outline btn-sm" onClick={handleReset}>Call again</button>
            </div>
          ) : (
            <form
              onSubmit={agent.hasQuote && call.status !== 'quoted' ? call.handleGetQuote : call.handleSubmit}
              className="call-form"
            >
              {call.errorMsg && <div className="alert alert-error">{call.errorMsg}</div>}

              <InputFields
                schema={agent.argsSchema}
                fields={call.fields}
                setFields={call.setFields}
                setFileFields={call.setFileFields}
                disabled={fieldsDisabled}
              />

              {agent.hasQuote && call.status === 'quoted' && call.quote && (
                <div className="quote-box">
                  {call.quote.plan && typeof call.quote.plan === 'object' && 'steps' in call.quote.plan && (
                    <div className="quote-plan">
                      {call.quote.plan.steps.map((s, i) => (
                        <div key={i} className="quote-step">
                          <span className="quote-step-num">{s.step + 1}</span>
                          <span className="quote-step-agent">{s.agent}</span>
                          <span className="quote-step-cap">{s.capability}</span>
                          <span className="quote-step-price">{s.price_ton}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {call.quote.plan && typeof call.quote.plan === 'string' && call.quote.plan && (
                    <div className="quote-plan">{call.quote.plan}</div>
                  )}
                  {call.quote.note && (
                    <div className="quote-note">{call.quote.note}</div>
                  )}
                  <div className="quote-meta">
                    <span className="quote-price">{nanoToTon(call.quote.price)} TON</span>
                    <span className={`quote-timer ${call.quoteSecondsLeft === 0 ? 'quote-timer--expired' : ''}`}>
                      {call.quoteSecondsLeft > 0 ? `Expires in ${call.quoteSecondsLeft}s` : 'Quote expired'}
                    </span>
                  </div>
                </div>
              )}

              {online === false && (
                <div className="alert alert-warn">
                  <span>Agent appears to be offline. Sending payment may result in a loss of funds.</span>
                  <button type="button" className="btn btn-outline btn-sm" onClick={recheck} disabled={pinging}>
                    {pinging ? 'Checking…' : 'Check again'}
                  </button>
                </div>
              )}

              {inQuoteFlow ? (
                <div className="quote-actions">
                  <button type="submit" className="btn btn-primary" disabled={call.busy || call.quoteSecondsLeft === 0 || online === false}>
                    {call.status === 'paying' ? 'Waiting for payment…'
                      : call.status === 'invoking' ? 'Calling agent…'
                      : call.status === 'polling' ? 'Waiting for result…'
                      : call.quoteSecondsLeft === 0 ? 'Quote expired'
                      : `Approve & Pay ${nanoToTon(call.quote!.price)} TON`}
                  </button>
                  <button type="button" className="btn btn-outline btn-sm" onClick={() => call.resetQuote()}>
                    Get new quote
                  </button>
                </div>
              ) : agent.hasQuote ? (
                <button type="submit" className="btn btn-primary" disabled={call.busy || online === false}>
                  {call.status === 'quoting' ? 'Getting quote…' : 'Get Quote'}
                </button>
              ) : (
                <button type="submit" className="btn btn-primary" disabled={call.busy || online === false}>
                  {call.status === 'paying' ? 'Waiting for payment…'
                    : call.status === 'invoking' ? 'Calling agent…'
                    : call.status === 'polling' ? 'Waiting for result…'
                    : `Pay ${nanoToTon(agent.price)} TON & Execute`}
                </button>
              )}
            </form>
          )}
        </div>
      )}
    </div>
  )
}
