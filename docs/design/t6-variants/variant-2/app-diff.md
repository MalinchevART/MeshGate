# app-diff.md — точният diff на `apps/web/src/App.tsx` (Т6, Вариант 2)

Прилага се СЛЕД като `shell.tsx` е на място като
`apps/web/src/components/Shell.tsx`, `hooks.ts` като
`apps/web/src/hooks/useAnomalyCount.ts` и подблокът „Т6" на `shell.css` е
вмъкнат в 4.1 SHELL на `apps/web/src/styles.css` (виж notes.md §Файлове).
Diff-ът е генериран с `diff -u` срещу днешния App.tsx (237 реда) —
резултатът е 163 реда (−74), като 36 от тях са чисто изтритата SECTIONS
дефиниция (преместена в Shell.tsx с новите полета icon/badge).

## Какво се маха / добавя — ред по ред (спрямо днешния App.tsx)

| Редове (днес) | Действие | Къде отива |
| --- | --- | --- |
| 1–19 (импорти) | `BrandMark` се ЗАПАЗВА (Login го ползва, ред 222); добавят се `Shell`, `PAGES` и типовете `Me`, `PageId` от `./components/Shell` + `export type { Me }` | — |
| 21–41 `PageBoundary` | НЕ СЕ ПИПА (остава в App; изнасянето му не е част от Т6) | — |
| 43–44 коментар + 45–76 `SECTIONS` | ИЗТРИВА СЕ — мести се в Shell.tsx, item-ите получават полета `icon` (чрез карта GLYPHS) и `badge: 'alarm'` на Мониторинг | `components/Shell.tsx` §1 |
| 77 `PAGES`, 78 `type PageId` | ИЗТРИВА СЕ — същите декларации в Shell.tsx; App само импортира (валидацията на `?p=` на ред 96–101 ОСТАВА в App) | `components/Shell.tsx` §1 |
| 80 `export type Me` | ИЗТРИВА СЕ — дефиницията е в Shell.tsx; App ре-експортира (`export type { Me }`), та 8-те страници с `import type { Me } from '../App'` не се пипат | `components/Shell.tsx` §1 |
| 82–112 тяло на App | НЕ СЕ ПИПА (state, refreshMe, `?p=` ефект, onboarding ефект, guards) | — |
| 114 `const isAdmin = …` | ИЗТРИВА СЕ — Shell го изчислява от `me.role` за филтъра на Sidebar | `components/Shell.tsx` §4 |
| 117 `div.shell` | ЗАМЕНЯ СЕ с `<Shell …>` (Shell рендерира СЪЩИЯ `div.shell` отвътре) | `components/Shell.tsx` §4 |
| 118–123 банер за начална парола | ПРЕМЕСТВА СЕ вътре в Shell (проп `onPassword` отваря ChangePassword) | `components/Shell.tsx` §4 |
| 124–145 `header.topbar` | ЗАМЕНЯ С Е с `<Topbar>`: лого + приложен LIVE (LiveIndicator compact през постоянния WS) + десен блок (username + role pill + 🔑 + Изход); role pill слиза от бранда в потребителския блок | `components/Shell.tsx` §2 |
| 146 `div.body`, 147–164 `aside.sidebar` | ЗАМЕНЯТ СЕ с `<Sidebar>` — същите класове/йерархия + икони, акцент-бар, aria-current, danger badge с брояча | `components/Shell.tsx` §3 |
| 165–182 `<main><PageBoundary>…` | `<main>` е в Shell (`children` слот); PageBoundary + 14-те реда страници ОСТАВАТ В APP непипнати (167–180) | — |
| 184–191 модали (ChangePassword, Onboarding) | ПРЕМЕСТВАТ С Е в проп `overlays` на Shell — рендерират се на СЪЩОТО място в DOM дървото (край на `div.shell`); `me={me as Me}` става `me={me}` (TS вече е знае, че е Me след guards-те) | App (съдържание) → Shell (място) |
| 196–237 `Login` | НЕ СЕ ПИПА | — |

DOM дърво след миграцията — идентично на днешното (проверка с DevTools
elements diff): `div.shell > [div.banner?] > header.topbar > div.body >
(aside.sidebar + main)` + модалите в края на `div.shell`. Новите възли са
САМО вътрешни за топбара/sidebar (`.topbar-left`, `.topbar-live`,
`.topbar-user`, `.side-btn__icon/__label`, `.side-badge`, `nav` обвивката
на sidebar секциите).

## Diff (unified, прилага се с `git apply` в apps/web/)

```diff
--- apps/web/src/App.tsx	2026-10-26 21:36:04.695021000 +0200
+++ apps/web/src/App.tsx	(Т6 В2 — след миграцията)
@@ -17,6 +17,12 @@
 import SystemPage from './pages/System'
 import ChangePassword from './pages/ChangePassword'
 import ComponentGallery from './pages/ComponentGallery'
+import { Shell, PAGES } from './components/Shell'
+import type { Me, PageId } from './components/Shell'
+
+// Me живее в components/Shell.tsx от Т6 В2 — ре-експорт, за да останат
+// непипнати 8-те легаси страници с `import type { Me } from '../App'`
+export type { Me }
 
 /** Авариен кожух: грешка в ЕДНА страница не бели целия интерфейс —
  * показва причина + презареждане (урок от 2026-10-22: бутон в Интеграции
@@ -40,45 +46,6 @@
   }
 }
 
-// дървото от визията (docs/11-ui-vision-plan.md §1): секция се показва само
-// когато зад нея има реален екран
-const SECTIONS: { title: string; items: { id: string; label: string; adminOnly?: boolean; hidden?: boolean }[] }[] = [
-  { title: 'Dashboard', items: [{ id: 'overview', label: 'Overview' }] },
-  {
-    title: 'Monitoring',
-    items: [
-      { id: 'monitor', label: 'Мониторинг' },
-      { id: 'devices', label: 'Устройства и мрежа' },
-      { id: 'packets', label: 'Packet Explorer' },
-      { id: 'map', label: 'Карта' },
-    ],
-  },
-  { title: 'MQTT Brokers', items: [{ id: 'broker', label: 'Брокер' }] },
-  { title: 'Bridges', items: [{ id: 'bridges', label: 'Мостове и маршрути' }] },
-  { title: 'Routing Rules', items: [{ id: 'routing', label: 'Правила за рутиране' }] },
-  { title: 'Automation', items: [{ id: 'notifications', label: 'Известия' }] },
-  { title: 'Integrations', items: [{ id: 'integrations', label: 'Интеграции' }] },
-  {
-    title: 'Security & Settings',
-    items: [
-      { id: 'system', label: 'Система и сигурност' },
-      { id: 'profiles', label: 'Profiles', adminOnly: true },
-    ],
-  },
-  {
-    title: '',
-    items: [
-      { id: 'plan', label: 'План & Тестове' },
-      // скрит регресионен полигон на Т3 — само чрез ?p=ui, не се брои в менюто
-      { id: 'ui', label: 'Компоненти', hidden: true },
-    ],
-  },
-]
-const PAGES = SECTIONS.flatMap((s) => s.items)
-type PageId = (typeof PAGES)[number]['id']
-
-export type Me = { id: string; username: string; role: string; default_password: boolean }
-
 export default function App() {
   const [me, setMe] = useState<Me | null | 'loading'>('loading')
   const [page, setPage] = useState<PageId>('overview')
@@ -111,85 +78,44 @@
   if (me === 'loading') return <div className="center muted">MeshGate зарежда…</div>
   if (!me) return <Login onOk={() => refreshMe()} />
 
-  const isAdmin = me.role === 'admin'
-
+  // шел-ът (топбар + LIVE WS + sidebar + брояч аларми) е компонент от Т6:
+  // components/Shell.tsx; App пази сесията, ?p= навигацията и модалите
   return (
-    <div className="shell">
-      {me.default_password && (
-        <div className="banner">
-          ⚠ Използваш НАЧАЛНАТА парола на системата. Смени я сега:
-          <button onClick={() => setPwOpen(true)}>Смяна на парола</button>
-        </div>
-      )}
-      <header className="topbar">
-        <div className="brand">
-          <BrandMark size={22} />
-          <span className="brand-word">Mesh<span className="brand-word-gate">Gate</span></span>
-          <span className="pill">{me.role}</span>
-        </div>
-        <div className="topbar-right">
-          <span className="muted">{me.username}</span>
-          <button className="nav-btn ghost" title="Смяна на парола" onClick={() => setPwOpen(true)}>
-            🔑
-          </button>
-          <button
-            className="nav-btn"
-            onClick={async () => {
-              await api('/v1/auth/logout', { method: 'POST' })
-              location.reload()
-            }}
-          >
-            Изход
-          </button>
-        </div>
-      </header>
-      <div className="body">
-        <aside className="sidebar">
-          {SECTIONS.map((s, i) => (
-            <div key={i} className="side-section">
-              {s.title && <div className="side-title">{s.title}</div>}
-              {s.items
-                .filter((p) => (!p.adminOnly || isAdmin) && !p.hidden)
-                .map((p) => (
-                  <button
-                    key={p.id}
-                    className={page === p.id ? 'side-btn active' : 'side-btn'}
-                    onClick={() => setPage(p.id)}
-                  >
-                    {p.label}
-                  </button>
-                ))}
-            </div>
-          ))}
-        </aside>
-        <main>
-          <PageBoundary>
-            {page === 'overview' && <Overview />}
-          {page === 'monitor' && <Monitor />}
-          {page === 'devices' && <Devices me={me} />}
-          {page === 'packets' && <PacketExplorer />}
-          {page === 'map' && <MapPage />}
-          {page === 'broker' && <Broker me={me} />}
-          {page === 'bridges' && <Bridges me={me} />}
-          {page === 'routing' && <RoutingRules me={me} />}
-          {page === 'notifications' && <Notifications me={me} />}
-          {page === 'integrations' && <Integrations me={me as Me} />}
-          {page === 'plan' && <PlanPage />}
-          {page === 'ui' && <ComponentGallery />}
-          {page === 'profiles' && <Profiles />}
-          {page === 'system' && <SystemPage me={me} onChanged={refreshMe} />}
-          </PageBoundary>
-        </main>
-      </div>
-      {pwOpen && <ChangePassword onClose={() => setPwOpen(false)} onDone={refreshMe} />}
-      {onbOpen && (
-        <Onboarding
-          me={me as Me}
-          refreshMe={refreshMe}
-          onClose={() => setOnbOpen(false)}
-        />
-      )}
-    </div>
+    <Shell
+      me={me}
+      page={page}
+      onPage={setPage}
+      onPassword={() => setPwOpen(true)}
+      overlays={
+        <>
+          {pwOpen && <ChangePassword onClose={() => setPwOpen(false)} onDone={refreshMe} />}
+          {onbOpen && (
+            <Onboarding
+              me={me}
+              refreshMe={refreshMe}
+              onClose={() => setOnbOpen(false)}
+            />
+          )}
+        </>
+      }
+    >
+      <PageBoundary>
+        {page === 'overview' && <Overview />}
+        {page === 'monitor' && <Monitor />}
+        {page === 'devices' && <Devices me={me} />}
+        {page === 'packets' && <PacketExplorer />}
+        {page === 'map' && <MapPage />}
+        {page === 'broker' && <Broker me={me} />}
+        {page === 'bridges' && <Bridges me={me} />}
+        {page === 'routing' && <RoutingRules me={me} />}
+        {page === 'notifications' && <Notifications me={me} />}
+        {page === 'integrations' && <Integrations me={me as Me} />}
+        {page === 'plan' && <PlanPage />}
+        {page === 'ui' && <ComponentGallery />}
+        {page === 'profiles' && <Profiles />}
+        {page === 'system' && <SystemPage me={me} onChanged={refreshMe} />}
+      </PageBoundary>
+    </Shell>
   )
 }
```

Login (днешни редове 196–237) и PageBoundary (21–41) не се пипат.
