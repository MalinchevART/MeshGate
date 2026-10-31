/**
 * T2 Вариант 3 — „Изцяло inline, без нови файлове"
 * Фрагмент за топбара в apps/web/src/App.tsx (~ред 115–119).
 *
 * ЗАМЕНЯ:
 *   <div className="brand">
 *     <span className="brand-mark">◈</span> MeshGate
 *     <span className="pill">{me.role}</span>
 *   </div>
 *
 * СЪЩЕСТВУВАЩИЯТ CSS (.brand в styles.css) ВЕЧЕ ПОКРИВА:
 *   display:flex, align-items:center, gap:var(--space-2), fs-16,
 *   fw-semibold, letter-spacing:0.4px → НЕ трябва нов CSS.
 * Единственото ново: <span> около „Gate" за акцентния цвят
 * (доскоро .brand-mark оцветяваше само глифа ◈, а не сегмент от текста).
 *
 * Приемане = copy/paste на JSX-a по-долу в App.tsx. Файлът тук е
 * само артефакт за ревю; export-ът го прави валиден/прегледаем TSX.
 */

export default function TopbarBrand({ role }: { role: string }) {
  return (
    <div className="brand">
      {/* „Mesh Triangle" — символ 1:1; tight viewBox 29 40 180 133
          (граници: stroke 35–202 x / възли 48–173 y, с ширините) */}
      <svg
        width="24"
        height="17.7"
        viewBox="29 40 180 133"
        aria-hidden="true"
        focusable="false"
      >
        {/* два преплитащи се триъгълника */}
        <path d="M35 166 L102 48 L170 166" fill="none" stroke="#22D3D9" strokeWidth={12} />
        <path d="M73 166 L137 58 L202 166" fill="none" stroke="#22D3D9" strokeWidth={12} />
        {/* вътрешни релсови връзки от реле-възела (73,119) надолу */}
        <path d="M73 119 L48 166 M73 119 L102 166" fill="none" stroke="#22D3D9" strokeWidth={4} />
        {/* възли */}
        <circle cx="102" cy="48" r="8" fill="#22D3D9" />
        <circle cx="137" cy="58" r="7" fill="#22D3D9" />
        <circle cx="73" cy="119" r="10" fill="#22D3D9" />
        <circle cx="170" cy="166" r="7" fill="#22D3D9" />
        <circle cx="202" cy="166" r="7" fill="#22D3D9" />
      </svg>
      Mesh<span style={{ color: 'var(--accent-primary)' }}>Gate</span>
      <span className="pill">{role}</span>
    </div>
  )
}
