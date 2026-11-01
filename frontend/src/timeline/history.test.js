import { describe, expect, it } from 'vitest'

import { MAX_HISTORY, applyTransaction, canRedo, canUndo, createHistory, presentEdl, redo, undo } from './history'
import { applyOp, cmdSplit } from './commands'
import { makeEdl } from './fixtures/edlFixture'

const splitAt = (edl) => applyOp(edl, cmdSplit('v1-02', 7200))

describe('snapshot history', () => {
  it('starts with the original EDL present and nothing to undo', () => {
    const edl = makeEdl()
    const h = createHistory(edl)
    expect(presentEdl(h)).toBe(edl)
    expect(canUndo(h)).toBe(false)
    expect(canRedo(h)).toBe(false)
  })

  it('one transaction = one undo entry that restores the exact EDL', () => {
    const edl = makeEdl()
    const before = JSON.stringify(edl)
    const r = applyTransaction(createHistory(edl), edl, splitAt)
    expect(r.ok).toBe(true)
    expect(r.history.entries.length).toBe(2)
    expect(r.history.present).toBe(1)

    const back = undo(r.history)
    expect(canUndo(back)).toBe(false)
    expect(JSON.stringify(presentEdl(back))).toBe(before)
    expect(canRedo(back)).toBe(true)
    expect(presentEdl(redo(back))).toEqual(r.edl)
  })

  it('a throwing transaction leaves state untouched', () => {
    const edl = makeEdl()
    const r = applyTransaction(createHistory(edl), edl, () => {
      throw new Error('trim: clip not found')
    })
    expect(r.ok).toBe(false)
    expect(r.error).toMatch(/not found/)
    expect(r.edl).toBe(edl)
    expect(r.history).toBeUndefined()
  })

  it('a no-op transaction does not push a snapshot', () => {
    const edl = makeEdl()
    const r = applyTransaction(createHistory(edl), edl, (e) => e)
    expect(r.ok).toBe(true)
    expect(r.history).toBeUndefined()
  })

  it('caps the stack at 30 and drops the oldest entry', () => {
    let edl = makeEdl()
    let h = createHistory(edl)
    for (let i = 0; i < MAX_HISTORY + 8; i += 1) {
      const cur = presentEdl(h)
      const r = applyTransaction(h, cur, (e) => {
        const next = structuredClone(e)
        next.revision = Number(next.revision || 1) + 1
        return next
      })
      h = r.history
      edl = r.edl
    }
    expect(h.entries.length).toBe(MAX_HISTORY)
    expect(presentEdl(h)).toEqual(edl)
    expect(presentEdl(h).revision).toBe(MAX_HISTORY + 9)      // newest survives
    // undo walks the retained window, never past its oldest snapshot
    for (let i = 0; i < MAX_HISTORY + 5; i += 1) h = undo(h)
    expect(canUndo(h)).toBe(false)
    expect(presentEdl(h).revision).toBe(10)
  })

  it('a new transaction after undo drops the redo tail', () => {
    const edl = makeEdl()
    const r1 = applyTransaction(createHistory(edl), edl, splitAt)
    const undone = undo(r1.history)
    const r2 = applyTransaction(undone, presentEdl(undone), (e) => {
      const next = structuredClone(e)
      next.revision = 9
      return next
    })
    expect(r2.history.entries.length).toBe(2)
    expect(canRedo(r2.history)).toBe(false)
    expect(presentEdl(r2.history).revision).toBe(9)
  })
})
