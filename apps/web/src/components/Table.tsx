/* ============================================================================
 * MeshGate · Т12 „Компонент Таблица" — фиксирана глава, сортиране, текстов
 * филтър, избор на колони. Нула нови зависимости; семантичен CSS върху
 * токените. БЕЗ запазени изгледа (F21 — отложено по docs/16).
 * Първи потребител: Devices (Т13); полигон: галерия ?p=ui.
 * ========================================================================== */
import { useMemo, useState } from 'react'

export interface Column<T> {
  id: string
  label: string
  /** Какво се рендерира в клетката (default: String(value)). */
  render?: (row: T) => React.ReactNode
  /** Ключ за сортиране/търсене (default: String(render)). */
  value?: (row: T) => string | number
  align?: 'left' | 'right'
  /** Скрита по подразбиране — потребителят я пали от [колони]. */
  defaultHidden?: boolean
}

interface SortState {
  id: string
  dir: 'asc' | 'desc'
}

export interface TableProps<T> {
  columns: Column<T>[]
  rows: T[]
  getKey: (row: T) => string
  /** Начален сортиращ ключ (id на колона). */
  initialSort?: string
  /** Текстов филтър по всички видими колони (текстово поле над таблицата). */
  filterable?: boolean
  placeholder?: string
  /** Празно състояние (честно — по подразбиране „няма редове"). */
  empty?: React.ReactNode
  dense?: boolean
  /** Клик на ред (rowlink списъци — Explorer и др.); клетъчните бутони
   *  спират разпространението сами. */
  onRowClick?: (row: T) => void
}

export function Table<T>({
  columns, rows, getKey, initialSort, filterable = false,
  placeholder = 'филтрирай…', empty = 'няма редове', dense = true,
  onRowClick,
}: TableProps<T>) {
  const [sort, setSort] = useState<SortState | null>(
    initialSort ? { id: initialSort, dir: 'asc' } : null)
  const [q, setQ] = useState('')
  const [hidden, setHidden] = useState<Set<string>>(
    new Set(columns.filter((c) => c.defaultHidden).map((c) => c.id)))
  const [colsOpen, setColsOpen] = useState(false)

  const visible = columns.filter((c) => !hidden.has(c.id))

  const val = (c: Column<T>, row: T): string | number =>
    c.value ? c.value(row) : String(c.render ? c.render(row) ?? '' : '')

  const view = useMemo(() => {
    let out = rows
    if (q.trim()) {
      const needle = q.trim().toLowerCase()
      out = out.filter((r) =>
        visible.some((c) => String(val(c, r)).toLowerCase().includes(needle)))
    }
    if (sort) {
      const col = columns.find((c) => c.id === sort.id)
      if (col) {
        out = [...out].sort((a, b) => {
          const va = val(col, a), vb = val(col, b)
          const cmp = typeof va === 'number' && typeof vb === 'number'
            ? va - vb
            : String(va).localeCompare(String(vb), 'bg')
          return sort.dir === 'asc' ? cmp : -cmp
        })
      }
    }
    return out
    // visible/val зависят от columns/hidden — включени през затварянето
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, q, sort, columns, hidden])

  const toggleSort = (id: string) => {
    setSort((s) =>
      s?.id === id
        ? { id, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { id, dir: 'asc' })
  }

  return (
    <div className="mg-table">
      {(filterable || columns.length > 3) && (
        <div className="mg-table__bar">
          {filterable && (
            <input className="mg-table__search" value={q} placeholder={placeholder}
                   onChange={(e) => setQ(e.target.value)}
                   aria-label="Филтър на редовете" />
          )}
          <div className="mg-table__cols">
            <button className="nav-btn" aria-expanded={colsOpen}
                    onClick={() => setColsOpen((v) => !v)}>☰ колони</button>
            {colsOpen && (
              <div className="mg-table__colsmenu" role="menu">
                {columns.map((c) => (
                  <label key={c.id}>
                    <input type="checkbox" checked={!hidden.has(c.id)}
                           onChange={() => setHidden((h) => {
                             const n = new Set(h)
                             if (n.has(c.id)) n.delete(c.id)
                             else if (n.size < columns.length - 1) n.add(c.id)
                             return n
                           })} />
                    {c.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      <div className={`mg-table__scroll${dense ? ' dense' : ''}`}>
        <table>
          <thead>
            <tr>
              {visible.map((c) => (
                <th key={c.id}
                    aria-sort={sort?.id === c.id
                      ? (sort.dir === 'asc' ? 'ascending' : 'descending')
                      : undefined}
                    style={c.align === 'right' ? { textAlign: 'right' as const } : undefined}>
                  <button className="mg-table__sort" onClick={() => toggleSort(c.id)}>
                    {c.label}
                    <span aria-hidden className={sort?.id === c.id ? 'on' : ''}>
                      {sort?.id === c.id ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ◇'}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.length === 0 ? (
              <tr><td colSpan={visible.length}><div className="empty">{empty}</div></td></tr>
            ) : view.map((r) => (
              <tr key={getKey(r)} className={onRowClick ? 'rowlink' : undefined}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}>
                {visible.map((c) => (
                  <td key={c.id}
                      style={c.align === 'right' ? { textAlign: 'right' as const } : undefined}>
                    {c.render ? c.render(r) : String(val(c, r))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
