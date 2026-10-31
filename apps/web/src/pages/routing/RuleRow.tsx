import { Component, useEffect, useState } from 'react'
import { api, fmtTime } from '../../api'
import RuleDiagram from './RuleDiagram'
import type { Me } from '../../App'
import Helper from '../Helper'
import RuleCanvas from '../RuleCanvas'
import TopicTokens, { TopicLegend } from '../TopicTokens'
import {
  OPS, normalizeDefinition, topicVerdict, suggestPattern, payloadPaths, familyOf,
} from '../RoutingRulesHelpers'
import type { Definition, Rule, Template, Bridge, Sample } from '../RoutingRulesHelpers'


/** Т19: RuleRow (редът в списъка с панел-действия) — извлечен 1:1 от
 *  RoutingRules.tsx; нула функционална промяна. */
export default function RuleRow({ rule, canOperate, isAdmin, onToggle, onEdit, onRemove, onRollback, panel, setPanel, reload, bridges, onCanvas }: any) {
  const [execs, setExecs] = useState<any[] | null>(null)
  const [versions, setVersions] = useState<any[] | null>(null)
  // Т23: audit изглед — кой/кога/какво с ТОЗИ път (от audit_log)
  const [auditRows, setAuditRows] = useState<any[] | null>(null)
  const open = panel?.ruleId === rule.id

  useEffect(() => {
    setExecs(null); setVersions(null); setAuditRows(null)
    if (!open) return
    if (panel.kind === 'exec') api(`/v1/routing/${rule.id}/executions?limit=50`).then(setExecs).catch(() => setExecs([]))
    if (panel.kind === 'ver') api(`/v1/routing/${rule.id}/versions`).then(setVersions).catch(() => setVersions([]))
    if (panel.kind === 'audit') api(`/v1/audit?limit=100`).then((rows: any[]) =>
      setAuditRows((rows ?? []).filter((r: any) => r.entity === 'routing_rule' && r.entity_id === rule.name))
    ).catch(() => setAuditRows([]))
  }, [open, panel?.kind])

  return <>
    <tr className="rowlink">
      <td onClick={() => isAdmin && onEdit(rule)}>
        <strong>{rule.name}</strong>
        {rule.draft && <span className="tag" title="име незапазена редакция"> чернова</span>}
      </td>
      <td>
        <button className={rule.enabled ? 'tag ok' : 'tag bad'} disabled={!canOperate}
          onClick={() => onToggle(rule)}>
          {rule.enabled ? 'включено' : 'изключено'}
        </button>
      </td>
      <td className="mono">{rule.priority}</td>
      <td className="mono">{rule.stats.matched}</td>
      <td className="mono">{rule.stats.forwarded}</td>
      <td className="mono">{rule.stats.errors || '·'}</td>
      <td className="small muted">{rule.stats.last_fired_at ? fmtTime(rule.stats.last_fired_at) : '—'}</td>
      <td className="mono">v{rule.current_version}{rule.draft ? '*' : ''}</td>
      <td className="small">
        {onCanvas && (
          <button className="ghost-btn" title="редактирай на жив канвас (R3.2)"
            onClick={() => onCanvas(rule.id)}>🎨</button>
        )}
        <button className="ghost-btn" title="правилото като диаграма"
          onClick={() => setPanel(open ? null : { kind: 'diag', ruleId: rule.id })}>📊</button>
        <button className="ghost-btn" title="журнал на изпълненията"
          onClick={() => setPanel(open ? null : { kind: 'exec', ruleId: rule.id })}>🕘</button>
        {isAdmin && (
          <button className="ghost-btn" title="audit: кой/кога/какво с това правило (Т23)"
                  onClick={() => setPanel(open && panel?.kind === 'audit' ? null : { kind: 'audit', ruleId: rule.id })}>🛡</button>
        )}
        <button className="ghost-btn" title="версии и rollback"
          onClick={() => setPanel(open ? null : { kind: 'ver', ruleId: rule.id })}>⎌</button>
        {isAdmin && <button className="ghost-btn" title="изтриване" onClick={() => onRemove(rule)}>🗑</button>}
      </td>
    </tr>
    {open && panel.kind === 'diag' && (
      <tr><td colSpan={9}>
        <RuleDiagram def={rule.draft ?? rule.definition} bridges={bridges || []} />
      </td></tr>
    )}
    {open && panel.kind === 'exec' && (
      <tr><td colSpan={9}>
        {!execs ? <span className="muted">зарежда…</span> : !execs.length ? (
          <div className="empty">Още няма изпълнения — правилото не е мръквало съобщение (или е изключено).</div>
        ) : (
          execs.slice(0, 12).map((e: any, i: number) => (
            <div key={i} className="small" style={{ borderBottom: '1px solid var(--line)', padding: '4px 0' }}>
              <span className={e.decision === 'match_forward' ? 'tag ok' : e.decision === 'error' ? 'tag bad' : 'tag'}>
                {e.decision}
              </span>{' '}
              <span className="mono">{e.input_topic}</span>{' '}
              <span className="muted">{fmtTime(e.ts)}</span>
              <div className="muted small">
                {e.error && <span className="deny">{e.error} </span>}
                {e.steps?.map((s: any, j: number) => <span key={j}>· {s.step} </span>)}
              </div>
            </div>
          ))
        )}
      </td></tr>
    )}
    {open && panel.kind === 'audit' && (
      <tr><td colSpan={9}>
        {!auditRows ? <span className="muted">зарежда…</span> : (
          auditRows.length === 0 ? <div className="empty">Няма audit записи за това правило.</div> : (
            <table>
              <thead><tr><th>Час</th><th>Кой</th><th>Действие</th><th>Детайли</th></tr></thead>
              <tbody>
                {auditRows.map((a: any, i: number) => (
                  <tr key={i}>
                    <td className="mono small">{fmtTime(a.ts)}</td>
                    <td>{a.username ?? 'система'}</td>
                    <td className="mono small">{a.action}</td>
                    <td className="small muted">{JSON.stringify(a.details).slice(0, 80)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </td></tr>
    )}
    {open && panel.kind === 'ver' && (
      <tr><td colSpan={9}>
        {!versions ? <span className="muted">зарежда…</span> : versions.map((v: any) => (
          <div key={v.version} className="small" style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '4px 0' }}>
            <span className="mono">v{v.version}</span>
            <span className="muted">{v.note}</span>
            <span className="muted small">{v.published_by} · {fmtTime(v.published_at)}</span>
            <span style={{ flex: 1 }} />
            {isAdmin && v.version !== rule.current_version && (
              <button className="ghost-btn" onClick={() => onRollback(rule, v.version)}>върни</button>
            )}
          </div>
        ))}
      </td></tr>
    )}
  </>
}

// ---------- wizard ----------
