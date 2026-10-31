// MeshGate — built by the N&M Control team.
import { Component, useEffect, useState } from 'react'
import { api, Unauthorized } from './api'
import { BrandMark } from './components/Brand'
import { Shell, PAGES } from './components/Shell'
import type { Me, PageId } from './components/Shell'

// Me живее в components/Shell.tsx от Т6 — ре-експорт, за да останат
// непипнати страниците с `import type { Me } from '../App'`
export type { Me }

import Overview from './pages/Overview'
import Monitor from './pages/Monitor'
import Devices from './pages/Devices'
import PacketExplorer from './pages/PacketExplorer'
import MapPage from './pages/MapPage'
import Broker from './pages/Broker'
import Bridges from './pages/Bridges'
import RoutingRules from './pages/RoutingRules'
import Notifications from './pages/Notifications'
import Integrations from './pages/Integrations'
import PlanPage from './pages/Plan'
import Onboarding from './pages/Onboarding'
import Profiles from './pages/Profiles'
import SystemPage from './pages/System'
import ChangePassword from './pages/ChangePassword'
import ComponentGallery from './pages/ComponentGallery'

/** Авариен кожух: грешка в ЕДНА страница не бели целия интерфейс —
 * показва причина + презареждане (урок от 2026-10-22: бутон в Интеграции
 * крашваше цялото приложение заради липсващо поле в API отговора). */
class PageBoundary extends Component<{ children: React.ReactNode }, { err: string | null }> {
  state = { err: null as string | null }
  static getDerivedStateFromError(e: any) { return { err: String(e?.message || e) } }
  render() {
    if (this.state.err) {
      return (
        <div className="panel">
          <div className="error">
            Страницата срещна грешка: {this.state.err}. Данните не са загубени —
            презареди и опитай отново (ако се повтаря, виж логовете на api).
          </div>
          <button onClick={() => location.reload()}>Презареди</button>
        </div>
      )
    }
    return this.props.children
  }
}

export default function App() {
  const [me, setMe] = useState<Me | null | 'loading'>('loading')
  const [page, setPage] = useState<PageId>('overview')
  const [pwOpen, setPwOpen] = useState(false)
  const [onbOpen, setOnbOpen] = useState(false)

  async function refreshMe() {
    try {
      setMe(await api('/v1/auth/me'))
    } catch {
      setMe(null)
    }
  }

  useEffect(() => {
    const q = new URLSearchParams(location.search)
    const p = q.get('p') as PageId | null
    if (p && PAGES.some((x) => x.id === p)) setPage(p)
    refreshMe()
  }, [])

  // първоначален съветник: докато началната парола е в сила (освен ако не е
  // отказан експортно) — води оператора през парола + разходка
  useEffect(() => {
    if (me && me !== 'loading' && me.default_password && !localStorage.getItem('mg_onboarding_done')) {
      setOnbOpen(true)
    }
  }, [me])

  if (me === 'loading') return <div className="center muted">MeshGate зарежда…</div>
  if (!me) return <Login onOk={() => refreshMe()} />

  // шел-ът (топбар + LIVE WS + sidebar + брояч аларми) е компонент от Т6:
  // components/Shell.tsx; App пази сесията, ?p= навигацията и модалите
  return (
    <Shell
      me={me}
      page={page}
      onPage={setPage}
      onPassword={() => setPwOpen(true)}
      overlays={
        <>
          {pwOpen && <ChangePassword onClose={() => setPwOpen(false)} onDone={refreshMe} />}
          {onbOpen && (
            <Onboarding
              me={me}
              refreshMe={refreshMe}
              onClose={() => setOnbOpen(false)}
            />
          )}
        </>
      }
    >
      <PageBoundary>
        {page === 'overview' && <Overview />}
        {/* Т27: Мониторинг таб-шел — трите ?p= id сочат една страница */}
        {(page === 'monitor' || page === 'monitor-time' || page === 'monitor-utility') && (
          <Monitor
            tab={page === 'monitor-time' ? 'time' : page === 'monitor-utility' ? 'utility' : 'overview'}
            onPage={setPage}
          />
        )}
        {page === 'devices' && <Devices me={me} />}
        {page === 'packets' && <PacketExplorer />}
        {page === 'map' && <MapPage />}
        {page === 'broker' && <Broker me={me} />}
        {page === 'bridges' && <Bridges me={me} />}
        {page === 'routing' && <RoutingRules me={me} />}
        {page === 'notifications' && <Notifications me={me} />}
        {page === 'integrations' && <Integrations me={me} />}
        {page === 'plan' && <PlanPage />}
        {page === 'ui' && <ComponentGallery />}
        {page === 'profiles' && <Profiles />}
        {page === 'system' && <SystemPage me={me} onChanged={refreshMe} />}
      </PageBoundary>
    </Shell>
  )
}

function Login({ onOk }: { onOk: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      onOk()
    } catch (err: any) {
      setError(err.message || 'входът неуспешен')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="center">
      <form className="login card" onSubmit={submit}>
        <h1 className="h-page"><BrandMark size={30} /> Mesh<span className="brand-word-gate">Gate</span></h1>
        <div className="brand-tagline">MONITOR / MANAGE / CONNECT</div>
        <input
          autoFocus placeholder="потребител" value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          type="password" placeholder="парола" value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="error">{error}</div>}
        <button disabled={busy || !username || !password}>{busy ? '…' : 'Вход'}</button>
      </form>
    </div>
  )
}
