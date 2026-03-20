import type { OnChainRating } from '../lib/rating'

interface Props {
  rating: OnChainRating | null
  loading: boolean
  error: boolean
  onRefresh: () => void
}

function scoreColor(score: number): string {
  if (score < 4) return 'var(--error)'
  if (score < 7) return 'var(--gold)'
  return 'var(--success)'
}

export function RatingBlock({ rating, loading, error, onRefresh }: Props) {
  if (loading && !rating) {
    return (
      <div className="rating-block rating-block--loading">
        <div className="rating-head">
          <span className="rating-star" style={{ color: 'var(--text-muted)' }}>★ ···</span>
          <span className="rating-meta">loading rating...</span>
        </div>
        <div className="rating-bar">
          <div className="rating-bar-fill rating-bar-fill--pulse" style={{ width: '0%' }} />
        </div>
      </div>
    )
  }

  if (error && !rating) {
    return (
      <div className="rating-block">
        <div className="rating-head">
          <span className="rating-star" style={{ color: 'var(--text-muted)' }}>★ —</span>
          <span className="rating-meta">couldn't load rating</span>
          <button className="rating-refresh" onClick={(e) => { e.stopPropagation(); onRefresh(); }} title="Retry">↻</button>
        </div>
      </div>
    )
  }

  if (!rating) return null

  if (rating.status === 'empty') {
    return (
      <div className="rating-block">
        <div className="rating-head">
          <span className="rating-star rating-star--new">★ NEW</span>
          <span className="rating-meta">no activity yet</span>
        </div>
      </div>
    )
  }

  if (rating.status === 'new') {
    return (
      <div className="rating-block">
        <div className="rating-head">
          <span className="rating-star rating-star--new">★ NEW</span>
          <span className="rating-meta">
            {rating.totalTxs} txs · too few to rate
          </span>
        </div>
      </div>
    )
  }

  const color = scoreColor(rating.score!)
  const pct = (rating.score! / 10) * 100

  return (
    <div className="rating-block">
      <div className="rating-head">
        <span className="rating-star" style={{ color }}>★ {rating.score!.toFixed(1)}</span>
        <span className="rating-meta">
          {rating.totalTxs} txs{rating.reviews > 0 && ` · ${rating.reviews} review${rating.reviews !== 1 ? 's' : ''}`}
        </span>
        <button className="rating-refresh" onClick={(e) => { e.stopPropagation(); onRefresh(); }} title="Refresh rating">↻</button>
      </div>
      <div className="rating-bar">
        <div className="rating-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}
