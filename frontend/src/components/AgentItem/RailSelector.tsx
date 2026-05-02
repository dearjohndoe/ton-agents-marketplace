export function RailSelector({ rails, selected, onSelect, disabled }: {
  rails: string[]
  selected: string
  onSelect: (rail: string) => void
  disabled: boolean
}) {
  if (!(rails.includes('TON') && rails.includes('USDT'))) return null
  return (
    <div className="rail-selector">
      <label className="rail-option">
        <input type="radio" name="rail" value="TON"
          checked={selected === 'TON'}
          onChange={() => onSelect('TON')}
          disabled={disabled} />
        <span>TON</span>
      </label>
      <label className="rail-option">
        <input type="radio" name="rail" value="USDT"
          checked={selected === 'USDT'}
          onChange={() => onSelect('USDT')}
          disabled={disabled} />
        <span>USDT</span>
      </label>
    </div>
  )
}
