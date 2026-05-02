import { TESTNET } from '../../config'

export function RefundedBlock({ reason, reasonCode: _reasonCode, refundTx, onReset }: {
  reason: string
  reasonCode: string
  refundTx: string
  onReset: () => void
}) {
  return (
    <div className="result-box result-box--refund">
      <span className="meta-label">Refunded</span>
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
      <button className="btn btn-outline btn-sm" onClick={onReset}>Try again</button>
    </div>
  )
}
