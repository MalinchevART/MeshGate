import { Component, useEffect, useState } from 'react'
import { api, fmtTime } from '../../api'
import type { Me } from '../../App'
import Helper from '../Helper'
import RuleCanvas from '../RuleCanvas'
import TopicTokens, { TopicLegend } from '../TopicTokens'
import {
  OPS, normalizeDefinition, topicVerdict, suggestPattern, payloadPaths, familyOf,
} from '../RoutingRulesHelpers'
import type { Definition, Rule, Template, Bridge, Sample } from '../RoutingRulesHelpers'


/** Т19: RuleDiagram (R3.1 блок-диаграмата) — извлечен 1:1 от RoutingRules.tsx;
 *  нула функционална промяна (механично разпадане за Т20-Т23 паритета). */
export default function RuleDiagram({ def, bridges }: { def: Definition; bridges: Bridge[] }) {
  const blocks: { title: string; lines: string[]; kind: 'src' | 'cond' | 'transform' | 'dst' }[] = []
  blocks.push({ title: '📡 Източник', lines: [def.source.topic_filter], kind: 'src' })

  const inc = def.conditions.topic.include
  const exc = def.conditions.topic.exclude
  if (inc.length || exc.length) {
    blocks.push({
      title: '⚑ Тема',
      kind: 'cond',
      lines: [
        ...(inc.length ? [`include: ${inc[0]}${inc.length > 1 ? ` +${inc.length - 1}` : ''}`] : []),
        ...(exc.length ? [`exclude: ${exc[0]}${exc.length > 1 ? ` +${exc.length - 1}` : ''}`] : []),
      ],
    })
  }
  const terms = def.conditions.payload.terms
  if (terms.length) {
    blocks.push({
      title: '🔎 Payload',
      kind: 'cond',
      lines: terms.slice(0, 2).map((t: any) =>
        Array.isArray(t?.terms)
          ? `[група ${t.mode}: ${t.terms.length}]`
          : `${t.path.replace('$.', '')} ${t.op} ${t.value ?? ''}`),
    })
  }
  const tr = def.transform
  if (tr.topic_template || Object.keys(tr.set_fields).length || tr.remove_fields.length || tr.add_envelope) {
    blocks.push({
      title: '⚙ Трансформация',
      kind: 'transform',
      lines: [
        ...(tr.topic_template ? [tr.topic_template] : []),
        ...(Object.keys(tr.set_fields).length ? [`+${Object.keys(tr.set_fields).length} поле(та)`] : []),
        ...(tr.add_envelope ? ['envelope'] : []),
        ...(tr.remove_fields.length ? [`−${tr.remove_fields.length} поле(та)`] : []),
      ],
    })
  }
  def.destinations.forEach((d) => {
    const bid = d.target.startsWith('bridge:') ? d.target.slice(7) : null
    blocks.push({
      title: bid ? `🌉 ${bridges.find((b) => b.id === bid)?.name || 'Мост'}` : '🎯 Локален брокер',
      kind: 'dst',
      lines: [d.topic_template, `qos ${d.qos}${d.retain ? ' · retain' : ''}`],
    })
  })

  const W = 170, H = 96, GAP = 34
  const width = blocks.length * W + (blocks.length - 1) * GAP
  return (
    <svg viewBox={`0 0 ${width} ${H}`} style={{ width: '100%', maxWidth: width * 1.5, height: 'auto', minHeight: 90, display: 'block' }}>
      {blocks.map((b, i) => {
        const x = i * (W + GAP)
        return (
          <g key={i} className={`mg-flow mg-kind-${b.kind}`}>
            <rect x={x} y={4} width={W} height={H - 8} rx={9} strokeWidth={1.5} className="mg-flow-box-rect" data-kind={b.kind} />
            <text x={x + 11} y={25} fontSize={11} fontWeight={600} className={`mg-flow-title mg-kind-${b.kind}`}>{b.title}</text>
            {b.lines.slice(0, 4).map((l, j) => (
              <text key={j} x={x + 11} y={44 + j * 14} fontSize={10} className="mg-flow-text">
                {l.length > 24 ? l.slice(0, 23) + '…' : l}
              </text>
            ))}
            {i < blocks.length - 1 && (
              <>
                <line x1={x + W} y1={H / 2} x2={x + W + GAP - 9} y2={H / 2} strokeWidth={1.5} className="mg-flow-link-line" />
                <polygon
                  points={`${x + W + GAP - 9},${H / 2 - 4} ${x + W + GAP - 9},${H / 2 + 4} ${x + W + GAP - 2},${H / 2}`}
                  className="mg-flow-link-arrow" />
              </>
            )}
          </g>
        )
      })}
    </svg>
  )
}
