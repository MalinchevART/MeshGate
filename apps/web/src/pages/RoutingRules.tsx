import { Component, useEffect, useState } from 'react'
import { api, fmtTime } from '../api'
import type { Me } from '../App'
import Helper from './Helper'
import RuleCanvas from './RuleCanvas'
import TopicTokens, { TopicLegend } from './TopicTokens'
import {
  OPS, normalizeDefinition, topicVerdict, suggestPattern, payloadPaths, familyOf,
} from './RoutingRulesHelpers'
import type { Definition, Rule, Template, Bridge, Sample } from './RoutingRulesHelpers'

import RuleRow from './routing/RuleRow'
import Wizard, { WizBoundary } from './routing/Wizard'
import RuleDiagram from './routing/RuleDiagram'

/** Т19: главният списък — Wizard/RuleRow/RuleDiagram живеят в pages/routing/
 *  (механично разпадане, нула функционална промяна; тестовете на routing
 *  остават непипнати и минаващи). */
export default function RoutingRules({ me }: { me: Me }) {
  const [rules, setRules] = useState<Rule[] | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [bridges, setBridges] = useState<Bridge[]>([])
  const [recent, setRecent] = useState<{ topic: string; count: number }[]>([])
  const [samples, setSamples] = useState<Sample[]>([])
  const [error, setError] = useState<string | null>(null)
  // wizard състояние
  const [wiz, setWiz] = useState<{ ruleId: string | null; step: number; def: Definition } | null>(null)
  const [creating, setCreating] = useState<null | 'choose' | 'helper' | 'templates'>(null)
  const [panel, setPanel] = useState<{ kind: 'exec' | 'ver' | 'diag' | 'audit'; ruleId: string } | null>(null)
  // R3.2: интерактивният канвас на правилото
  const [canvasId, setCanvasId] = useState<string | null>(null)
  // „→ Рутирай канала“ от Packet Explorer: каналът идва през sessionStorage
  const [routeFamily, setRouteFamily] = useState<string | null>(null)

  const isAdmin = me.role === 'admin'
  const canOperate = me.role !== 'viewer'

  async function load() {
    try {
      const [r, t, b, rec, smp] = await Promise.all([
        api('/v1/routing'), api('/v1/routing/templates'),
        api('/v1/bridges'), api('/v1/routing/recent-topics'), api('/v1/routing/samples'),
      ])
      setRules(r); setTemplates(t); setBridges(b); setRecent(rec); setSamples(smp)
    } catch (e: any) { setError(e.message) }
  }
  useEffect(() => { load() }, [])
  useEffect(() => {
    const fam = sessionStorage.getItem('mg_route_family')
    if (fam) {
      sessionStorage.removeItem('mg_route_family')
      setRouteFamily(fam)
      setCreating('helper')
    }
  }, [])

  async function toggle(rule: Rule) {
    try {
      await api(`/v1/routing/${rule.id}/${rule.enabled ? 'disable' : 'enable'}`, { method: 'POST' })
      await load()
    } catch (e: any) { setError(e.message) }
  }

  async function remove(rule: Rule) {
    if (!confirm(`Изтриване на „${rule.name}"? Журналът и версиите също се трият.`)) return
    try {
      await api(`/v1/routing/${rule.id}`, { method: 'DELETE' })
      await load()
    } catch (e: any) { setError(e.message) }
  }

  async function rollback(rule: Rule, version: number) {
    if (!confirm(`Връщане на „${rule.name}" към v${version}?`)) return
    try {
      await api(`/v1/routing/${rule.id}/rollback`, { method: 'POST', body: JSON.stringify({ version }) })
      setPanel(null); await load()
    } catch (e: any) { setError(e.message) }
  }

  // ---------- wizard ----------

  function startCreate(fromTemplate?: Template) {
    // шаблонът идва от API-то вече нормализиран; локалната нормализация пази
    // и при частични/по-стари данни
    setWiz({ ruleId: null, step: 1, def: normalizeDefinition(fromTemplate?.definition) })
    setCreating(null)
  }

  function startEdit(rule: Rule) {
    setWiz({ ruleId: rule.id, step: 1, def: normalizeDefinition(rule.draft ?? rule.definition) })
  }

  function patchDef(fn: (d: Definition) => void) {
    setWiz((w) => {
      if (!w) return w
      const d = JSON.parse(JSON.stringify(w.def))
      fn(d)
      return { ...w, def: normalizeDefinition(d) }
    })
  }

  if (wiz) return (
    <WizBoundary onExit={() => { setWiz(null); load() }}>
      <Wizard
        wiz={wiz} setWiz={setWiz} patchDef={patchDef} bridges={bridges} recent={recent} samples={samples}
        isAdmin={isAdmin}
        onDone={() => { setWiz(null); load() }}
      />
    </WizBoundary>
  )

  // R3.2: живият канвас — същият JSON, визуално редактиране + dry-run
  if (canvasId && isAdmin) {
    const rule = rules?.find((r) => r.id === canvasId)
    if (rule) return (
      <WizBoundary onExit={() => { setCanvasId(null); load() }}>
        <RuleCanvas
          rule={rule} bridges={bridges} samples={samples}
          onDone={() => { setCanvasId(null); load() }}
        />
      </WizBoundary>
    )
  }

  if (creating === 'helper') return (
    <WizBoundary onExit={() => { setCreating(null); load() }}>
      <Helper
        recent={recent} samples={samples} bridges={bridges}
        prefillFamily={routeFamily}
        onDone={() => { setCreating(null); setRouteFamily(null); load() }}
      />
    </WizBoundary>
  )

  return (
    <>
      <div className="toolbar">
        <h2>Routing Rules</h2>
        {isAdmin && (
          <button onClick={() => setCreating('choose')}>+ Създай правило</button>
        )}
        <span className="muted small">правила за препращане: източник → условия → трансформация → дестинации</span>
      </div>
      {error && <div className="error">{error}</div>}

      {creating === 'choose' && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <h2>Как искаш да създадеш правилото?</h2>
          <div className="cards" style={{ marginBottom: 8 }}>
            <div className="card" style={{ cursor: 'pointer', borderColor: 'var(--accent)' }} onClick={() => setCreating('helper')}>
              <strong>🧭 Помощник (препоръчано)</strong>
              <p className="muted small" style={{ minHeight: 48 }}>
                Избираш какво искаш — „аларма при ниска батерия“, „препращай канала
                към външен брокер“… Каналите и данните се показват сами. Без знание
                на MQTT теми и шаблони.
              </p>
              <button>Започни</button>
            </div>
            <div className="card" style={{ cursor: 'pointer' }} onClick={() => setCreating('templates')}>
              <strong>🛠 Шаблон или експертен wizard</strong>
              <p className="muted small" style={{ minHeight: 48 }}>
                Готови шаблони + пълен 5-стъпков редактор с ръчен контрол над
                include/exclude, условия, трансформации и дестинации.
              </p>
              <button className="ghost-btn">Започни</button>
            </div>
          </div>
          <button className="ghost-btn" onClick={() => setCreating(null)}>Отказ</button>
        </div>
      )}

      {creating === 'templates' && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <h2>Откъде да започнем?</h2>
          <div className="cards" style={{ marginBottom: 8 }}>
            {templates.map((t) => (
              <div key={t.id} className="card" style={{ cursor: 'pointer' }} onClick={() => startCreate(t)}>
                <strong>{t.title}</strong>
                <p className="muted small" style={{ minHeight: 48 }}>{t.description}</p>
                <button className="ghost-btn">Избери</button>
              </div>
            ))}
            <div className="card" style={{ cursor: 'pointer', borderStyle: 'dashed' }} onClick={() => startCreate()}>
              <strong>Празно правило</strong>
              <p className="muted small" style={{ minHeight: 48 }}>От нулата — wizard-ът води стъпка по стъпка.</p>
              <button className="ghost-btn">Избери</button>
            </div>
          </div>
          <button className="ghost-btn" onClick={() => setCreating(null)}>Отказ</button>
        </div>
      )}

      <div className="panel">
        {!rules?.length ? (
          <div className="empty">Няма правила. Създай едно от шаблон — работи с реалните теми отдолу.</div>
        ) : (
          <table>
            <thead><tr>
              <th>Правило</th><th>Статус</th><th>Приоритет</th><th>Match</th><th>Forward</th><th>Грешки</th>
              <th>Последно</th><th>Версия</th><th></th>
            </tr></thead>
            <tbody>
              {rules.map((r) => (
                <RuleRow key={r.id} rule={r} canOperate={canOperate} isAdmin={isAdmin}
                  onToggle={toggle} onEdit={startEdit} onRemove={remove} onRollback={rollback}
                  panel={panel} setPanel={setPanel} reload={load} bridges={bridges}
                  onCanvas={isAdmin ? (ruleId: string) => setCanvasId(ruleId) : undefined} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h3>Последни реални теми (2 ч)</h3>
        {!recent.length ? (
          <div className="empty">Няма трафик — пусни демо възлите от менюто, за да видиш живи теми.</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {recent.map((r) => (
              <span key={r.topic} className="tag mono" title={`${r.count} съобщения`}>{r.topic}</span>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
