import { describe, expect, it } from 'vitest'

import { mergeRows, normalizeRow, statusTone } from './agentTelemetry'

const replayRow = (seq, action = 'stage') => ({
  seq,
  action_id: `a-${seq}`,
  agent: 'director',
  action,
  status: 'succeeded',
  revision_after: 2,
})

describe('row parsing', () => {
  it('normalizes the server row shape and defaults missing fields', () => {
    const row = normalizeRow({
      seq: 3, action_id: 'abc', agent: 'editor', parent_agent: 'supervisor',
      action: 'apply_plan', status: 'succeeded', detail: 'split at 7.2',
      revision_before: 1, revision_after: 2, duration_ms: 420,
      clip_ids: ['v1-02', 'v1-03', 'v1-04', 'x', 'y', 'z', 'ignored'],
    })
    expect(row.seq).toBe(3)
    expect(row.parentAgent).toBe('supervisor')
    expect(row.revisionBefore).toBe(1)
    expect(row.revisionAfter).toBe(2)
    expect(row.durationMs).toBe(420)
    expect(row.clipIds).toHaveLength(5)              // capped for the chip row
    expect(normalizeRow(null)).toBeNull()
    expect(normalizeRow({}).agent).toBe('timeline_agent')
    expect(normalizeRow({}).status).toBe('queued')
  })

  it('never carries prompt or transcript payloads into a row', () => {
    const row = normalizeRow({
      seq: 1, action: 'agent_requested',
      prompt: 'make it cinematic', transcript: 'grandmother: we left at dawn',
      detail: 'agent_requested',
    })
    const blob = JSON.stringify(row)
    expect(blob).not.toContain('make it cinematic')
    expect(blob).not.toContain('grandmother')
  })

  it('parses the plan operation list for the expandable feed row', () => {
    const row = normalizeRow({
      seq: 7, action: 'plan',
      operations: [
        { op: 'delete', target: 'v1-02' },
        { op: 'set_profile', target: 'shorts' },
        { op: 'split' },
        { target: 'no-op-name' },
        { op: 'delete', target: 'v1-09', text: 'private caption line' },
      ],
    })
    expect(row.operations).toEqual([
      { op: 'delete', target: 'v1-02' },
      { op: 'set_profile', target: 'shorts' },
      { op: 'split', target: '' },
      { op: 'delete', target: 'v1-09' },
    ])
    expect(JSON.stringify(row)).not.toContain('private caption line')
    expect(normalizeRow({ seq: 1 }).operations).toEqual([])
  })
})

describe('dedupe and ordering', () => {
  it('replays then appends live rows ordered by seq', () => {
    const merged = mergeRows(
      [normalizeRow({ ...replayRow(1), source: 'replay' }), normalizeRow({ ...replayRow(2), source: 'replay' })],
      [replayRow(4), replayRow(3)],
      'live',
    )
    expect(merged.map((r) => r.seq)).toEqual([1, 2, 3, 4])
    expect(merged[0].source).toBe('replay')
    expect(merged[3].source).toBe('live')
  })

  it('dedupes the same row arriving twice (seq + action_id)', () => {
    const once = mergeRows([], [replayRow(5)], 'live')
    const twice = mergeRows(once, [replayRow(5)], 'live')
    expect(twice).toHaveLength(1)
    // a replayed row keeps its replay provenance when the live copy lands
    const replayed = mergeRows([normalizeRow({ ...replayRow(5), source: 'replay' })], [replayRow(5)], 'live')
    expect(replayed).toHaveLength(1)
    expect(replayed[0].source).toBe('replay')
  })

  it('caps the visible ring at 200 rows', () => {
    const rows = Array.from({ length: 260 }, (_, i) => replayRow(i))
    const merged = mergeRows([], rows, 'live')
    expect(merged).toHaveLength(200)
    expect(merged[merged.length - 1].seq).toBe(259)
  })
})

describe('model usage badge', () => {
  it('joins provider and model for the row badge', () => {
    expect(normalizeRow({ seq: 1, provider: 'meta', model: 'muse-spark-1.3' }).modelBadge)
      .toBe('meta · muse-spark-1.3')
    expect(normalizeRow({ seq: 1, model: 'flux-1-schnell' }).modelBadge).toBe('flux-1-schnell')
    expect(normalizeRow({ seq: 1 }).modelBadge).toBe('')
  })

  it('survives the replay/live merge', () => {
    const rows = mergeRows([], [{ seq: 1, agent: 'editor', provider: 'meta', model: 'muse-spark-1.3' }])
    expect(rows[0].modelBadge).toBe('meta · muse-spark-1.3')
  })
})

describe('status tones', () => {
  it('maps every terminal state to a dot tone', () => {
    expect(statusTone('succeeded')).toBe('ok')
    expect(statusTone('failed')).toBe('error')
    expect(statusTone('rejected')).toBe('hashtag')
    expect(statusTone('stale')).toBe('warn')
    expect(statusTone('degraded')).toBe('warn')
    expect(statusTone('running')).toBe('busy')
    expect(statusTone('queued')).toBe('idle')
    expect(statusTone(undefined)).toBe('idle')
  })
})
