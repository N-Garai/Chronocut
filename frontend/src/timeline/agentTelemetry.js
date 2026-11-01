/**
 * timeline/agentTelemetry.js — parse/dedupe/redact agent_activity rows
 * Rows come from (a) cold-load GET /agent/activity replay and
 * (b) live `agent_activity` SSE events. Dedupe by seq then action_id.
 */
export function normalizeRow(raw) {
  if (!raw || typeof raw !== 'object') return null
  const row = {
    seq: Number(raw.seq ?? raw.ts ?? 0),
    action_id: String(raw.action_id || ''),
    agent: String(raw.agent || raw.stage || 'timeline_agent'),
    parentAgent: raw.parent_agent ? String(raw.parent_agent) : null,
    action: String(raw.action || raw.stage || ''),
    status: String(raw.status || 'queued'),
    detail: String(raw.detail || raw.message || ''),
    revisionBefore: raw.revision_before ?? null,
    revisionAfter: raw.revision_after ?? null,
    durationMs: Number(raw.duration_ms ?? 0),
    clipIds: Array.isArray(raw.clip_ids) ? raw.clip_ids.slice(0, 5) : [],
    // Plan operation list for the expandable feed row (names + clip/profile
    // targets only; the server never sends caption or prompt text).
    operations: Array.isArray(raw.operations)
      ? raw.operations.slice(0, 20).map((o) => ({
        op: String(o?.op || ''),
        target: o?.target != null ? String(o.target) : '',
      })).filter((o) => o.op)
      : [],
    // "provider · model" badge for the row (M7: visible model usage).
    modelBadge: raw.provider
      ? [raw.provider, raw.model].filter(Boolean).join(' · ')
      : (raw.model ? String(raw.model) : ''),
    ts: raw.ts || new Date().toISOString(),
    source: raw.source || 'live',
  }
  return row
}

/** Append (or replace) rows ordered by seq, deduped. source records replay|live. */
export function mergeRows(existing = [], incoming = [], source = 'live') {
  const byKey = new Map()
  for (const row of existing) {
    const key = String(row.seq ?? '') + ':' + String(row.action_id || row.agent + row.action)
    byKey.set(key, { ...row, source: 'replay' })
  }
  for (const raw of incoming) {
    const row = normalizeRow({ ...(raw || {}), source })
    if (!row) continue
    const key = String(row.seq ?? '') + ':' + String(row.action_id || row.agent + row.action)
    const prev = byKey.get(key)
    byKey.set(key, prev ? { ...prev, ...row, source: prev.source === 'replay' ? 'replay' : source } : row)
  }
  return [...byKey.values()].sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0)).slice(-200)
}

/** Status dot color per row status. */
export function statusTone(status) {
  switch (String(status || '').toLowerCase()) {
    case 'succeeded': return 'ok'
    case 'failed': return 'error'
    case 'rejected': return 'hashtag'
    case 'stale': return 'warn'
    case 'degraded': return 'warn'
    case 'running': return 'busy'
    case 'queued':
    default: return 'idle'
  }
}
