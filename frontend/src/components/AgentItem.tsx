import { useState } from 'react'
import { useWalletUI, useWalletAddress } from '../lib/wallet'
import { Address } from '@ton/core'
import { resolveDownloadUrl } from '../lib/agentClient'
import { resolveImageSrc } from '../lib/imageProxy'
import type { ConnectionMode } from '../lib/agentClient'
import { ResultRenderer } from './ResultRenderer'
import type { Agent, ArgSchema, Sku } from '../types'
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
  locked?: boolean
}

function nanoToTon(n: number) {
  const t = n / 1e9
  return t < 0.001 ? t.toExponential(2) : t.toFixed(3).replace(/\.?0+$/, '')
}

function microToUsdt(n: number) {
  const t = n / 1e6
  return t < 0.01 ? t.toExponential(2) : t.toFixed(2).replace(/\.?0+$/, '')
}

function PriceBadge({ agent }: { agent: Agent }) {
  const hasTon = agent.price > 0
  const hasUsdt = agent.priceUsdt != null && agent.priceUsdt > 0
  if (!hasTon && !hasUsdt) return <span>--</span>
  return (
    <>
      {hasTon && <span className="price-ton">{nanoToTon(agent.price)} TON</span>}
      {hasTon && hasUsdt && <span className="price-sep"> / </span>}
      {hasUsdt && <span className="price-usdt">{microToUsdt(agent.priceUsdt!)} USDT</span>}
    </>
  )
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

function AgentThumb({ url }: { url: string }) {
  const [failed, setFailed] = useState(false)
  const src = resolveImageSrc(url)
  if (!src || failed) return null
  return (
    <img
      className="agent-thumb"
      src={src}
      alt=""
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      crossOrigin="anonymous"
      onError={() => setFailed(true)}
    />
  )
}

function AgentGallery({ images }: { images: string[] }) {
  const [failed, setFailed] = useState<Set<number>>(new Set())
  const visible = images
    .map((url, i) => ({ url, i }))
    .filter(({ i }) => !failed.has(i))
  if (visible.length === 0) return null
  return (
    <div className="agent-gallery">
      {visible.map(({ url, i }) => {
        const src = resolveImageSrc(url)
        if (!src) return null
        return (
          <a
            key={i}
            className="agent-gallery-item"
            href={src}
            target="_blank"
            rel="noopener noreferrer"
          >
            <img
              src={src}
              alt=""
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
              crossOrigin="anonymous"
              onError={() => setFailed(prev => new Set(prev).add(i))}
            />
          </a>
        )
      })}
    </div>
  )
}

function normalizeDesc(s: string): string {
  return s.replace(/\\n/g, '\n')
}

function AgentDesc({ description, full }: { description: string; full: boolean }) {
  const text = normalizeDesc(description)
  if (full) {
    return <p className="agent-summary-desc agent-summary-desc--full">{text}</p>
  }
  const preview = text.length > 150 ? text.slice(0, 150) + '…' : text
  return <p className="agent-summary-desc">{preview}</p>
}

function ShareButton({ sidecarId }: { sidecarId: string }) {
  const [copied, setCopied] = useState(false)
  function handleShare() {
    const url = `${window.location.origin}${import.meta.env.BASE_URL}agents/${sidecarId}`
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button className="share-btn" onClick={handleShare} title="Copy share link">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
      </svg>
      <span>{copied ? 'Copied!' : 'Copy link'}</span>
    </button>
  )
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

function SkuSelector({ skus, selectedId, onSelect, disabled }: {
  skus: Sku[]
  selectedId: string
  onSelect: (id: string) => void
  disabled: boolean
}) {
  return (
    <div className="sku-selector">
      <span className="meta-label">Variant</span>
      <div className="sku-list">
        {skus.map(s => {
          const soldOut = s.stockLeft != null && s.stockLeft <= 0
          const active = s.id === selectedId
          return (
            <button
              key={s.id}
              type="button"
              className={`sku-item${active ? ' sku-item--active' : ''}${soldOut ? ' sku-item--sold-out' : ''}`}
              onClick={() => !soldOut && !disabled && onSelect(s.id)}
              disabled={disabled || soldOut}
              title={soldOut ? 'Sold out' : ''}
            >
              <span className="sku-title">{s.title || s.id}</span>
              <span className="sku-price">
                {s.priceTon != null && <span className="price-ton">{nanoToTon(s.priceTon)} TON</span>}
                {s.priceTon != null && s.priceUsdt != null && <span className="price-sep"> / </span>}
                {s.priceUsdt != null && <span className="price-usdt">{microToUsdt(s.priceUsdt)} USDT</span>}
              </span>
              <span className="sku-stock">
                {soldOut ? 'Sold out'
                  : s.stockLeft != null ? `${s.stockLeft} left`
                  : '∞'}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function StockBadge({ sku }: { sku: Sku }) {
  if (sku.stockLeft == null) return null
  if (sku.stockLeft <= 0) {
    return <div className="alert alert-warn">Sold out.</div>
  }
  return <div className="stock-badge">{sku.stockLeft} in stock</div>
}

function RefundedBlock({ reason, refundTx, onReset }: {
  reason: string
  refundTx: string
  onReset: () => void
}) {
  return (
    <div className="result-box result-box--refund">
      <span className="meta-label">Refunded — out of stock</span>
      {reason && <p className="refund-reason">{reason}</p>}
      {refundTx && (
        <p className="refund-tx">
          Refund tx:{' '}
          <a
            href={`https://${TESTNET ? 'testnet.' : ''}tonviewer.com/transaction/${refundTx}`}
            target="_blank" rel="noopener noreferrer" className="link"
          >
            {refundTx.slice(0, 10)}…{refundTx.slice(-10)}
          </a>
        </p>
      )}
      <button className="btn btn-outline btn-sm" onClick={onReset}>Try another variant</button>
    </div>
  )
}

export function AgentItem({ agent, expanded, onToggle, locked }: Props) {
  const tonConnectUI = useWalletUI()
  const walletAddress = useWalletAddress()

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
  const skuTon = call.selectedSku?.priceTon ?? agent.price
  const skuUsdt = call.selectedSku?.priceUsdt ?? agent.priceUsdt
  const selectedSoldOut = call.selectedSku?.stockLeft != null && call.selectedSku.stockLeft <= 0
  const submitDisabled = call.busy || online === false || selectedSoldOut

  return (
    <div className={`agent-item ${expanded ? 'agent-item--open' : ''}${locked ? ' agent-item--locked' : ''}`}>
      {/* Row — always visible */}
      <button className="agent-row" onClick={locked ? undefined : onToggle} aria-expanded={expanded} disabled={locked}>
        {(agent.previewUrl || agent.avatarUrl) && <AgentThumb url={agent.previewUrl || agent.avatarUrl!} />}
        <div className="agent-row-left">
          {!locked && <span className="agent-row-name">{agent.name || agent.address.slice(0, 10) + '…'}</span>}
          <div className="agent-row-meta">
            {online === true && !pinging && <span className="tag" style={{color: 'var(--success)', borderColor: 'var(--success)'}}>online</span>}
            {online === false && !pinging && <span className="agent-offline-badge">offline</span>}
            {pinging && <span className="tag">…</span>}
            {agent.capabilities.map(c => <span key={c} className="tag">{c}</span>)}
          </div>
        </div>
        <div className="agent-row-right">
          <span className="agent-row-price">{agent.hasQuote && 'from '}<PriceBadge agent={agent} /></span>
          <span className={`chevron ${expanded ? 'chevron--open' : ''}`}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </span>
        </div>
      </button>

      {/* Summary — always visible */}
      {(onChainRating || ratingLoading || ratingError || agent.description) && (
        <div className="agent-summary" onClick={locked ? undefined : onToggle}>
          <RatingBlock rating={onChainRating} loading={ratingLoading} error={ratingError} onRefresh={ratingRefresh} />
          {agent.description && <AgentDesc description={agent.description} full={!!locked || expanded} />}
        </div>
      )}

      {/* Expanded body */}
      {expanded && (
        <div className="agent-body">
          {agent.images && agent.images.length > 0 && <AgentGallery images={agent.images} />}
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
            <div className="meta-item">
              <span className="meta-label">Share</span>
              <ShareButton sidecarId={agent.sidecarId} />
            </div>
          </div>

          <div className="agent-divider" />

          {!walletAddress ? (
            <div className="alert alert-info">Connect your wallet to call this agent.</div>
          ) : call.status === 'refunded_out_of_stock' ? (
            <RefundedBlock
              reason={call.refundReason}
              refundTx={call.refundTx}
              onReset={handleReset}
            />
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

              {call.skus.length > 1 && (
                <SkuSelector
                  skus={call.skus}
                  selectedId={call.selectedSkuId}
                  onSelect={call.setSelectedSkuId}
                  disabled={fieldsDisabled}
                />
              )}
              {call.skus.length === 1 && call.skus[0] && (
                <StockBadge sku={call.skus[0]} />
              )}

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
                    <span className="quote-price">{nanoToTon(call.quote.price)} TON{skuUsdt ? ` / ${microToUsdt(skuUsdt)} USDT` : ''}</span>
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
                  <button type="submit" className="btn btn-primary" disabled={submitDisabled || call.quoteSecondsLeft === 0}>
                    {call.status === 'paying' ? 'Waiting for payment…'
                      : call.status === 'invoking' ? 'Calling agent…'
                      : call.status === 'polling' ? 'Waiting for result…'
                      : call.quoteSecondsLeft === 0 ? 'Quote expired'
                      : selectedSoldOut ? 'Sold out'
                      : call.selectedRail === 'USDT' && skuUsdt
                        ? `Approve & Pay ${microToUsdt(skuUsdt)} USDT`
                        : `Approve & Pay ${nanoToTon(call.quote!.price)} TON`}
                  </button>
                  <button type="button" className="btn btn-outline btn-sm" onClick={() => call.resetQuote()}>
                    Get new quote
                  </button>
                </div>
              ) : agent.hasQuote ? (
                <button type="submit" className="btn btn-primary" disabled={submitDisabled}>
                  {call.status === 'quoting' ? 'Getting quote…'
                    : selectedSoldOut ? 'Sold out'
                    : 'Get Quote'}
                </button>
              ) : (
                <>
                  {call.paymentRails.includes('TON') && call.paymentRails.includes('USDT') && (
                    <div className="rail-selector">
                      <label className="rail-option">
                        <input type="radio" name="rail" value="TON"
                          checked={call.selectedRail === 'TON'}
                          onChange={() => call.setSelectedRail('TON')}
                          disabled={call.busy} />
                        <span>TON</span>
                      </label>
                      <label className="rail-option">
                        <input type="radio" name="rail" value="USDT"
                          checked={call.selectedRail === 'USDT'}
                          onChange={() => call.setSelectedRail('USDT')}
                          disabled={call.busy} />
                        <span>USDT</span>
                      </label>
                    </div>
                  )}
                  <button type="submit" className="btn btn-primary" disabled={submitDisabled}>
                    {call.status === 'paying' ? 'Waiting for payment…'
                      : call.status === 'invoking' ? 'Calling agent…'
                      : call.status === 'polling' ? 'Waiting for result…'
                      : selectedSoldOut ? 'Sold out'
                      : call.selectedRail === 'USDT' && skuUsdt
                        ? `Pay ${microToUsdt(skuUsdt)} USDT & Execute`
                        : `Pay ${nanoToTon(skuTon)} TON & Execute`}
                  </button>
                </>
              )}
            </form>
          )}
        </div>
      )}
    </div>
  )
}
