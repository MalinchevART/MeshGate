/**
 * T2 Вариант 3 — „Изцяло inline, без нови файлове"
 * Фрагмент за Login формата в apps/web/src/App.tsx (~ред 211–212).
 *
 * ЗАМЕНЯ:
 *   <h1><span className="brand-mark">◈</span> MeshGate</h1>
 *   <p className="muted">MQTT Gateway & Management</p>
 *
 * h1 наследява съществуващия си стил (fs-20, fw-semibold); таглайнът
 * ползва само дизайн-токени (var(--font-mono), var(--fs-12),
 * var(--text-muted)) → нула нов CSS. Символът е същият SVG като в
 * топбара, само мащабиран на 40px височина (дублиране по дизайн —
 * виж NOTES.md, минуси).
 */

export default function LoginBrand() {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 'var(--space-2)',
        marginBottom: 'var(--space-2)',
      }}
    >
      <svg
        width="54.1"
        height="40"
        viewBox="29 40 180 133"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M35 166 L102 48 L170 166" fill="none" stroke="#22D3D9" strokeWidth={12} />
        <path d="M73 166 L137 58 L202 166" fill="none" stroke="#22D3D9" strokeWidth={12} />
        <path d="M73 119 L48 166 M73 119 L102 166" fill="none" stroke="#22D3D9" strokeWidth={4} />
        <circle cx="102" cy="48" r="8" fill="#22D3D9" />
        <circle cx="137" cy="58" r="7" fill="#22D3D9" />
        <circle cx="73" cy="119" r="10" fill="#22D3D9" />
        <circle cx="170" cy="166" r="7" fill="#22D3D9" />
        <circle cx="202" cy="166" r="7" fill="#22D3D9" />
      </svg>
      <h1 style={{ margin: 0 }}>
        Mesh<span style={{ color: 'var(--accent-primary)' }}>Gate</span>
      </h1>
      <p
        style={{
          margin: 0,
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--fs-12)',
          letterSpacing: '2.2px',
          color: 'var(--text-muted)',
        }}
      >
        MONITOR / MANAGE / CONNECT
      </p>
    </div>
  )
}
