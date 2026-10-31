// Цветно рендване на Meshtastic теми/шаблони: регион · канал · устройство.
// Целта: операторът да ВИЖДА кое е какво в msh/<регион>/2/e/<канал>/!<възел>.

// Стойностите са категорни променливи от 4.11 DATA-VIZ (Т5) — системата
// със значения (регион/канал/възел/шаблон/структура) е от R3.1 и НЕ се
// смесва със статусните токени.
const COLORS = {
  region: 'var(--tok-region)',    // регион — циан
  channel: 'var(--tok-channel)',  // канал — оранжево
  device: 'var(--tok-device)',    // устройство — зелено
  wildcard: 'var(--tok-wildcard)', // + / * (който и да е) — лилаво
  sep: 'var(--tok-sep)',          // структура (msh, 2, e, json) — сиво
} as const

function tokenColor(tok: string, i: number, toks: string[]): string {
  if (tok === '+' || tok === '*') return COLORS.wildcard
  if (tok.startsWith('!')) return COLORS.device
  if (i === 1) return COLORS.region
  if (i > 0 && (toks[i - 1] === 'e' || toks[i - 1] === 'c' || toks[i - 1] === 'json')) return COLORS.channel
  return COLORS.sep
}

export default function TopicTokens({ value }: { value: string }) {
  const toks = value.split('/')
  return (
    <span className="mg-tok" style={{ fontSize: 12, wordBreak: 'break-all' }}>
      {toks.map((t, i) => (
        <span key={i}>
          {i > 0 && <span style={{ color: 'var(--tok-sep)' }}>/</span>}
          <span style={{ color: tokenColor(t, i, toks) }}>{t}</span>
        </span>
      ))}
    </span>
  )
}

export function TopicLegend() {
  return (
    <span className="muted small" style={{ display: 'inline-flex', gap: 12, flexWrap: 'wrap' }}>
      <span style={{ color: COLORS.region }}>■ регион</span>
      <span style={{ color: COLORS.channel }}>■ канал</span>
      <span style={{ color: COLORS.device }}>■ устройство</span>
      <span style={{ color: COLORS.wildcard }}>■ + / който и да е</span>
    </span>
  )
}
