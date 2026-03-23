import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { TypedResult } from '../types'

interface Props {
  result: TypedResult
  downloadUrl: (path: string) => string
}

export function ResultRenderer({ result, downloadUrl }: Props) {
  if (result.type === 'json' && isOrchestratorData(result.data)) {
    return <OrchestratorResult data={result.data} downloadUrl={downloadUrl} />
  }
  switch (result.type) {
    case 'string':
      return <StringResult data={String(result.data)} />
    case 'int':
    case 'float':
      return <NumberResult data={Number(result.data)} type={result.type} />
    case 'file':
      return <FileResult result={result} downloadUrl={downloadUrl} />
    case 'url':
      return <UrlResult data={String(result.data)} />
    case 'bagid':
      return <BagIdResult data={String(result.data)} />
    case 'json':
    default:
      return <JsonResult data={result.data ?? result} />
  }
}

function isOrchestratorData(data: any): data is { steps: any[]; final: TypedResult | null } {
  return data != null && Array.isArray(data.steps) && 'final' in data
}

function OrchestratorResult({
  data,
  downloadUrl,
}: {
  data: { steps: any[]; final: TypedResult | null }
  downloadUrl: (path: string) => string
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="orch-result">
      {data.steps.length > 0 && (
        <details className="orch-steps" open={open} onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
          <summary className="orch-steps-summary">
            <span className="orch-steps-label">{data.steps.length} steps</span>
            <span className="orch-chevron">{open ? '▲' : '▼'}</span>
          </summary>
          <div className="orch-steps-list">
            {data.steps.map((step, i) => (
              <div key={i} className="orch-step">
                <div className="orch-step-header">
                  <span className="orch-step-num">{i + 1}</span>
                  <span className="orch-step-agent">{step.agent}</span>
                </div>
                {step.error && <div className="orch-step-error">{step.error}</div>}
                {step.result && (
                  <div className="orch-step-result">
                    <ResultRenderer result={step.result} downloadUrl={downloadUrl} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </details>
      )}
      {data.final && (
        <ResultRenderer result={data.final} downloadUrl={downloadUrl} />
      )}
    </div>
  )
}

function StringResult({ data }: { data: string }) {
  return (
    <div className="result-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{data}</ReactMarkdown>
    </div>
  )
}

function NumberResult({ data, type }: { data: number; type: 'int' | 'float' }) {
  const formatted = type === 'int'
    ? Math.round(data).toLocaleString()
    : Number(data).toLocaleString(undefined, { maximumFractionDigits: 6 })
  return (
    <div className="result-number">
      <span className="result-number-value">{formatted}</span>
    </div>
  )
}

function FileResult({ result, downloadUrl }: { result: TypedResult; downloadUrl: (path: string) => string }) {
  const [secondsLeft, setSecondsLeft] = useState(result.expires_in ?? 0)

  useEffect(() => {
    if (!result.expires_in) return
    setSecondsLeft(result.expires_in)
    const id = setInterval(() => setSecondsLeft(s => Math.max(0, s - 1)), 1000)
    return () => clearInterval(id)
  }, [result.expires_in])

  const url = result.url ? downloadUrl(result.url) : ''
  const mime = result.mime_type ?? ''
  const fileName = result.file_name ?? 'download'
  const expired = result.expires_in != null && secondsLeft === 0

  return (
    <div className="result-file">
      {!expired && mime.startsWith('image/') && (
        <img src={url} alt={fileName} className="result-file-preview" />
      )}
      {!expired && mime.startsWith('audio/') && (
        <audio controls src={url} className="result-file-audio" />
      )}
      {!expired && mime.startsWith('video/') && (
        <video controls src={url} className="result-file-video" />
      )}
      <div className="result-file-meta">
        {!expired ? (
          <a href={url} download={fileName} className="btn btn-outline btn-sm result-file-download">
            Download {fileName}
          </a>
        ) : (
          <span className="btn btn-outline btn-sm result-file-download result-file-download--disabled">
            {fileName}
          </span>
        )}
        {!expired && secondsLeft > 0 && (
          <span className="result-file-expires">
            Expires in {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, '0')}
          </span>
        )}
        {expired && (
          <span className="result-file-expired">File expired</span>
        )}
      </div>
    </div>
  )
}

function UrlResult({ data }: { data: string }) {
  return (
    <div className="result-url">
      <a href={data} target="_blank" rel="noopener noreferrer" className="link">{data}</a>
    </div>
  )
}

function BagIdResult({ data }: { data: string }) {
  return (
    <div className="result-bagid">
      <span className="result-bagid-label">Bag ID</span>
      <a
        href={`https://tonscan.org/bags/${data}`}
        target="_blank"
        rel="noopener noreferrer"
        className="link"
      >
        {data}
      </a>
    </div>
  )
}

function JsonResult({ data }: { data: any }) {
  return (
    <pre className="result-content">
      {typeof data === 'string' ? data : JSON.stringify(data, null, 2)}
    </pre>
  )
}
