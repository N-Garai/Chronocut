import { describe, expect, it } from 'vitest'

import { SNAP_PX, snap, snapCandidates, snapOrRaw } from './snapping'
import { makeEdl } from './fixtures/edlFixture'

describe('snap candidates', () => {
  it('collects same-track edges plus the timeline origin', () => {
    const edl = makeEdl()
    const c = snapCandidates(edl, 0, 'v1')
    expect(c).toContain(0)
    expect(c).toContain(5000)
    expect(c).toContain(10000)
    expect(c).toContain(15000)
    // caption edges stay out of a same-track snap
    expect(c).not.toContain(3000)
  })

  it('honours excluded clips (the one being dragged)', () => {
    const edl = makeEdl()
    // excluding v1-03 drops its exclusive tail edge (15000); shared edges stay
    const c = snapCandidates(edl, 0, 'v1', { excludeClipIds: ['v1-03'] })
    expect(c).not.toContain(15000)
    expect(c).toContain(5000)
    expect(c).toContain(10000)
  })
})

describe('snap threshold', () => {
  it('snaps inside the px threshold and rejects outside it', () => {
    const candidates = [0, 5000, 10000]
    // 6 px at 50 px/s = 120 ms
    expect(snap(5050, candidates, 50)).toBe(5000)
    expect(snap(5120, candidates, 50)).toBe(5000)          // exactly at the edge
    expect(snap(5130, candidates, 50)).toBeNull()
  })

  it('keeps the threshold in pixels at any zoom', () => {
    const candidates = [5000]
    // 6 px at 200 px/s = 30 ms, so 5040 ms is already too far
    expect(snap(5030, candidates, 200)).toBe(5000)
    expect(snap(5040, candidates, 200)).toBeNull()
    // 6 px at 10 px/s = 600 ms, so 5500 ms still snaps
    expect(snap(5500, candidates, 10)).toBe(5000)
  })

  it('returns the raw value when nothing is close or snapping is off', () => {
    const candidates = [0, 5000]
    expect(snapOrRaw(4321, candidates, 50)).toBe(4321)
    expect(snapOrRaw(5050, candidates, 50)).toBe(5000)
    expect(snapOrRaw(5050, candidates, 50, { disabled: true })).toBe(5050)
    expect(SNAP_PX).toBe(6)
  })
})
