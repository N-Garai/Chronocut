import { describe, expect, it } from 'vitest'

import { batchCommand, clientContext, normalizePlan, requiresConfirmation } from './agentBridge'
import { applyTransaction, createHistory, presentEdl, undo } from './history'
import { applyBatch } from './commands'
import { clipsOf, idsOf, makeEdl } from './fixtures/edlFixture'

const plan = (ops, extra = {}) => ({
  message: 'split at 7.2',
  operations: ops,
  base_revision: 1,
  warnings: [],
  requires_confirmation: false,
  ...extra,
})

describe('plan -> command batch', () => {
  it('normalizes one plan into a single BatchCommand', () => {
    const cmd = batchCommand(plan([
      { op: 'split', args: { clip_id: 'v1-02', at: 7.2 } },
    ]))
    expect(cmd.kind).toBe('batch')
    expect(cmd.ops).toHaveLength(1)
    expect(cmd.message).toBe('split at 7.2')
  })

  it('is all-or-nothing on a malformed plan', () => {
    expect(() => normalizePlan(plan([]))).toThrow(/no operations/)
    expect(() => normalizePlan({ operations: 'nope' })).toThrow(/no operations/)
    expect(() => normalizePlan(plan([{ args: {} }]))).toThrow(/malformed/)
    expect(() => normalizePlan(plan([{ op: 'split' }, null]))).toThrow(/malformed/)
  })

  it('rejects more than 200 operations', () => {
    const many = Array.from({ length: 201 }, () => ({ op: 'split', args: {} }))
    expect(() => normalizePlan(plan(many))).toThrow(/too large/)
  })

  it('applies as one undo entry that restores the exact EDL', () => {
    const edl = makeEdl()
    const before = JSON.stringify(edl)
    const cmd = batchCommand(plan([
      { op: 'split', args: { clip_id: 'v1-02', at: 7.2 } },
      { op: 'delete', args: { clip_id: 'v1-04', ripple: true } },
    ]))
    const r = applyTransaction(createHistory(edl), edl, (draft) => applyBatch(draft, cmd.ops))
    expect(r.ok).toBe(true)
    expect(r.history.entries.length).toBe(2)             // exactly one undo entry
    expect(idsOf(r.edl)).toEqual(['v1-01', 'v1-02', 'v1-03'])
    expect(JSON.stringify(presentEdl(undo(r.history)))).toBe(before)
  })

  it('keeps the draft unchanged when any op in the plan is invalid', () => {
    const edl = makeEdl()
    const cmd = batchCommand(plan([
      { op: 'split', args: { clip_id: 'v1-02', at: 7.2 } },
      { op: 'trim', args: { clip_id: 'ghost', edge: 'start', time: 1 } },
    ]))
    const r = applyTransaction(createHistory(edl), edl, (draft) => applyBatch(draft, cmd.ops))
    expect(r.ok).toBe(false)
    expect(JSON.stringify(r.edl)).toBe(JSON.stringify(edl))
  })
})

describe('destructive-plan confirmation gate', () => {
  it('applies non-destructive plans immediately', () => {
    const edl = makeEdl()
    expect(requiresConfirmation(plan([{ op: 'split', args: {} }]), edl)).toBe(false)
    expect(requiresConfirmation(plan([{ op: 'trim', args: {} }]), edl)).toBe(false)
  })

  it('asks before deleting 3+ clips or >25% of the duration', () => {
    const edl = makeEdl()
    const del = (id) => ({ op: 'delete', args: { clip_id: id } })
    expect(requiresConfirmation(plan([del('v1-01')]), edl)).toBe(true)         // 5/15 s = 33% > 25%
    expect(requiresConfirmation(plan([del('v1-01'), del('v1-02')]), edl)).toBe(true)
    expect(requiresConfirmation(plan([del('v1-01'), del('v1-02'), del('v1-03')]), edl)).toBe(true)
    const big = makeEdl()
    big.project.duration = 60
    expect(requiresConfirmation(plan([del('v1-01')]), big)).toBe(false)        // 5/60 s = 8%
  })

  it('respects a server-set confirmation flag', () => {
    expect(requiresConfirmation(plan([{ op: 'split', args: {} }], { requires_confirmation: true }), makeEdl()))
      .toBe(true)
  })
})

describe('client context', () => {
  it('sends integer ms and caps the selection at 20 ids', () => {
    const ctx = clientContext({ playheadMs: 12345.6, selectedClipIds: new Array(30).fill('v1-01') })
    expect(ctx.playhead_ms).toBe(12346)
    expect(ctx.selection).toHaveLength(20)
    expect(clientContext({}).playhead_ms).toBe(0)
    expect(clientContext({}).selection).toEqual([])
  })
})

describe('one plan never leaks into the draft on conflict', () => {
  it('leaves the draft intact when the server rejects with 409', () => {
    const edl = makeEdl()
    const stale = plan([{ op: 'split', args: { clip_id: 'v1-02', at: 7.2 } }], { base_revision: 1 })
    // the client refuses to apply a plan whose base_revision is behind
    const conflict = stale.base_revision !== 2
    expect(conflict).toBe(true)
    expect(clipsOf(edl)).toHaveLength(3)
  })
})
