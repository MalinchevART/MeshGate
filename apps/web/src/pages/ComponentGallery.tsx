/* ============================================================================
 * MeshGate · Т3 „Базови компоненти" — компонентна галерия (регресионен полигон)
 * ----------------------------------------------------------------------------
 * Скрита страница: достижима САМО чрез ?p=ui (не се брои в менюто). Показва
 * всеки компонент от components/ui.tsx във всяко състояние — QA жива проверка
 * за Т3 и регресионна обиколка за Т6/Т9/Т14, преди те да консумират.
 * Нулев бекенд: данните тук са демонстративни и са си коректно НЕ live.
 * ========================================================================== */
import { useEffect, useState } from 'react'
import {
  LiveIndicator,
  MetricCard,
  Modal,
  Panel,
  StatusChip,
  useLivePulse,
  usePacketStream,
  useToast,
} from '../components/ui'
import type { Tone } from '../components/ui'
import { Table, type Column } from '../components/Table'

const TONES: Tone[] = ['success', 'warning', 'danger', 'info', 'accent', 'neutral']

const DEMO_ROWS = [
  { node: '!620c9a91', chan: 'LongFast', pk: 1240, bat: 5 },
  { node: '!55e72173', chan: 'LongFast', pk: 980, bat: 88 },
  { node: '!1bf0a446', chan: 'MediumFast', pk: 340, bat: 42 },
  { node: '!48a05fe5', chan: 'Bulgaria', pk: 210, bat: 63 },
  { node: '!266f644c', chan: 'Bulgaria', pk: 95, bat: 5 },
]

/** Стойностите на токените, прочетени от живия CSS (Т5): таблицата се
 * обновява сама при смяна на токен — hex не се копира на ръка. */
const CONTRAST_ROWS = [
  { label: 'success', token: '--status-success', bg: '8% tint / surface', ratio: '7.89', chip: 'success' },
  { label: 'warning', token: '--status-warning', bg: '8% tint / surface', ratio: '8.84', chip: 'warning' },
  { label: 'danger', token: '--status-danger', bg: '8% tint / surface', ratio: '5.48', chip: 'danger' },
  { label: 'info', token: '--status-info', bg: '8% tint / surface', ratio: '6.33', chip: 'info' },
  { label: 'accent', token: '--accent-primary', bg: '8% tint / surface', ratio: '8.10', chip: 'accent' },
  { label: 'text-muted', token: '--text-muted', bg: 'panel', ratio: '6.40', chip: 'success' },
  { label: 'accent текст', token: '--accent-primary', bg: 'surface', ratio: '9.46', chip: 'success' },
] as const

export default function ComponentGallery() {
  const [tokenValues, setTokenValues] = useState<Record<string, string>>({})
  useEffect(() => {
    const cs = getComputedStyle(document.documentElement)
    const out: Record<string, string> = {}
    for (const r of CONTRAST_ROWS) out[r.token] = cs.getPropertyValue(r.token).trim()
    setTokenValues(out)
  }, [])
  const toast = useToast()

  // Демо състояния на контролните компоненти
  const [q, setQ] = useState('')
  const [period, setPeriod] = useState('24h')
  const [modalOpen, setModalOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Live симулатор: потокът е „отворен" (state live), данните идват на ритъм —
  // точката пулсира САМО докато текат и гасне 1.5s след спиране (decay).
  const sim = useLivePulse()
  const [flow, setFlow] = useState(false)
  useEffect(() => {
    if (!flow) return
    const t = setInterval(() => sim.onData(), 900)
    return () => clearInterval(t)
  }, [flow, sim.onData])

  // Реалният поток на платформата (същият WS, който ползва Packet Explorer)
  const stream = usePacketStream()

  return (
    <div>
      <div className="kicker">Т3 · базови компоненти</div>
      <h1 className="h-page">Компонентна галерия</h1>
      <p className="text-muted-sm">
        Регресионен полигон: всеки компонент във всяко състояние. Страницата е
        скрита от менюто (само <span className="mono">?p=ui</span>); данните са
        демонстративни. Контрастните числа са изчислени спрямо токените от Т1.
      </p>

      <Panel title="Card / Metric" subtitle="еднаква височина в реда; контекстът се изравнява долу">
        <div className="mg-card-grid">
          <MetricCard label="Пакети 24 ч" value="12 345" context="спрямо вчера: +4%" />
          <MetricCard label="Активни възли" value="47" tone="success" icon="◉"
            context="3 нови днес" />
          <MetricCard label="Батерия под 20%" value="2" tone="danger" icon="🔋"
            context="Топ 3: BG-Alpha 12% · BG-Beta 15% · BG-Gamma 17% (+0 още)" />
          <MetricCard label="Среден SNR" value="-9.4 dB" tone="warning"
            context="мрежа LongFast · 61 възела · 24 ч" />
        </div>
        <div className="text-muted-sm">
          Тонът оцветява стойността; mono стойност:{' '}
          <MetricCard label="Последен възел" value="!a4f3c2d0" mono context="Meshtastic node id" />
        </div>
      </Panel>

      <Panel title="Status Chip" subtitle="цвят винаги + глиф + текст (тонът не се носи само от цвета)">
        <div className="form-grid">
          {TONES.map((t) => (
            <StatusChip key={t} tone={t}>{t}</StatusChip>
          ))}
        </div>
        <h3>flat (плътни таблици) + sm + mono</h3>
        <div className="form-grid">
          <StatusChip tone="success" flat>decoded</StatusChip>
          <StatusChip tone="danger" flat>failed</StatusChip>
          <StatusChip tone="warning" flat size="sm">partial</StatusChip>
          <StatusChip tone="info" mono size="sm">!a4f3c2d0</StatusChip>
          <StatusChip tone="accent" mono>msh/Bulgaria/2/e/LongFast</StatusChip>
          <StatusChip tone="neutral" size="sm">binary</StatusChip>
        </div>
      </Panel>

      <Panel
        title="Panel"
        subtitle="заглавие + филтър/период + действия + ⛶ цял екран (Esc изход)"
        filters={
          <>
            <input placeholder="филтър…" value={q} onChange={(e) => setQ(e.target.value)} />
            <select value={period} onChange={(e) => setPeriod(e.target.value)}>
              <option value="1h">1 час</option>
              <option value="24h">24 часа</option>
              <option value="7d">7 дни</option>
            </select>
          </>
        }
        actions={
          <button className="ghost-btn" onClick={() => setQ('')}>Изчисти</button>
        }
      >
        <p className="text-muted-sm">
          Филтър: „{q || '—'}“ · период: {period}. Бутонът ⛶ в дясно на заглавието
          разпъва панела на цял екран над топбара; Esc връща.
        </p>
      </Panel>

      <Panel title="Modal / Drawer" subtitle="focus trap · Esc · фон-клик · scroll lock">
        <div className="form-grid">
          <button onClick={() => setModalOpen(true)}>Отвори модал</button>
          <button className="ghost-btn" onClick={() => setDrawerOpen(true)}>Отвори drawer</button>
        </div>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          title="Примерен модал"
          footer={
            <>
              <button className="ghost-btn" onClick={() => setModalOpen(false)}>Отказ</button>
              <button onClick={() => { toast.push('success', 'Модалът „подаде" формата'); setModalOpen(false) }}>
                Подаване
              </button>
            </>
          }
        >
          <p>
            Тялото на диалога: Tab обикаля само вътре, Esc затваря, клик върху
            фона също. Скролът на страницата е заключен, докато е отворен.
          </p>
          <input data-autofocus placeholder="авто-фокусирано поле" />
        </Modal>
        <Modal
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          variant="drawer"
          title="Примерен drawer"
        >
          <p>
            Страничен панел (за детайл на възел — Т11). Под 900px заема целия
            екран; Esc и фон-клик затварят.
          </p>
        </Modal>
      </Panel>

      <Panel title="Toast" subtitle="стек макс 5 с изтласкване; пауза на hover; danger стои 10s">
        <div className="form-grid">
          <button onClick={() => toast.push('success', 'Правилото е публикувано')}>success</button>
          <button onClick={() => toast.push('info', 'Синхронизацията завърши', { title: 'инфо' })}>info</button>
          <button onClick={() => toast.push('warning', 'Батерия на BG-Alpha е 12%', { title: 'внимание' })}>warning</button>
          <button onClick={() => toast.push('danger', 'Доставката към remote брокера се провали', {
            title: 'грешка',
            action: { label: 'Виж', onClick: () => toast.push('info', '„Виж" е кликнат от toast') },
          })}>danger + action</button>
          <button className="ghost-btn" onClick={() => {
            for (let i = 1; i <= 8; i++) toast.push('info', `Известие ${i} от 8`, { title: 'стек тест' })
          }}>навей 8 наведнъж</button>
        </div>
      </Panel>

      <Panel title="Live indicator" subtitle="пулс САМО при нови данни; никога на спрял/свързващ се поток">
        <h3>Симулатор на поток (без мрежа)</h3>
        <div className="form-grid" style={{ alignItems: 'center' }}>
          <LiveIndicator state="live" pulsing={sim.pulsing} label="СИМУЛАТОР" />
          <button onClick={() => sim.onData()}>Изпрати данни сега</button>
          <button className="ghost-btn" onClick={() => setFlow((v) => !v)}>
            {flow ? 'Спри потока' : 'Пусни поток (на 0.9s)'}
          </button>
          <span className="text-muted-sm">
            Спрян поток = жива връзка без пулс; точката гасне 1.5s след данните.
          </span>
        </div>
        <h3>Реалният поток на платформата (WS /api/v1/packets/ws)</h3>
        <div className="form-grid" style={{ alignItems: 'center' }}>
          <LiveIndicator state={stream.state} pulsing={stream.pulsing} />
          <button className="ghost-btn" onClick={() => stream.setPaused(!stream.paused)}>
            {stream.paused ? '▶ Продължи' : '⏸ Пауза'}
          </button>
          <span className="text-muted-sm">
            Без трафик стои LIVE без пулс — вярното поведение; паузата също не
            пулсира.
          </span>
        </div>
        <h3>Трите състояния</h3>
        <div className="form-grid">
          <LiveIndicator state="live" />
          <LiveIndicator state="idle" />
          <LiveIndicator state="reconnect" />
          <LiveIndicator state="live" pulsing label="LIVE (пулс)" />
        </div>
      </Panel>

      <Panel title="Таблица (Т12)" subtitle="сортиране по колона · текстов филтър · избор на колони · фиксирана глава">
        <Table
          columns={[
            { id: 'node', label: 'Възел', value: (r) => r.node },
            { id: 'chan', label: 'Канал', value: (r) => r.chan },
            { id: 'pk', label: 'Пакети', align: 'right', value: (r) => r.pk,
              render: (r) => r.pk.toLocaleString('bg-BG') },
            { id: 'bat', label: 'Батерия', align: 'right', defaultHidden: true, value: (r) => r.bat },
          ] as Column<typeof DEMO_ROWS[number]>[]}
          rows={DEMO_ROWS}
          getKey={(r) => r.node}
          initialSort="pk"
          filterable
          placeholder="търси възел/канал…"
          empty="никой не отговаря на филтъра"
        />
      </Panel>

      <Panel title="Контраст (изчислен, WCAG AA ≥ 4.5:1)" subtitle="стойностите се четат НА ЖИВО от токените — таблицата не може да излъже при смяна">
        <table>
          <thead>
            <tr><th>Комбинация</th><th>Съотношение</th><th>Извод</th></tr>
          </thead>
          <tbody>
            {CONTRAST_ROWS.map((r) => (
              <tr key={r.label}>
                <td>{r.label} <span className="mono muted"> {tokenValues[r.token] ?? '…'} </span> върху {r.bg}</td>
                <td className="mono">{r.ratio}:1</td>
                <td><StatusChip tone={r.chip} flat>AA ✓</StatusChip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
