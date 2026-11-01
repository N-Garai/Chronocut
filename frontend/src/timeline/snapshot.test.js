import { describe, expect, it } from 'vitest'

import { buildSnapshot, summarizeChips } from './snapshot'
import { makeEdl } from './fixtures/edlFixture'

describe('state chips', () => {
  it('serializes a compact, numbers-only summary', () => {
    const payload = JSON.parse(buildSnapshot({
      revision: 4, clips: 3, captions: 1, durationMs: 15234.6,
      playheadMs: 7200, selection: ['v1-02', 'v1-03'], dirty: true, stale: false,
      renderState: 'stale',
    }))
    expect(payload).toEqual({
      revision: '4',
      clips: 3,
      captions: 1,
      duration_s: 15.235,
      playhead_s: 7.2,
      selection: '2',
      dirty: true,
      stale: false,
      renderState: 'stale',
    })
  })

  it('summarizes an EDL without leaking media paths or secrets', () => {
    const edl = makeEdl()
    const text = summarizeChips(edl, {
      revision: 1, playheadMs: 500, selectedClipIds: ['v1-01'], dirty: false, stale: true,
    })
    expect(JSON.parse(text).clips).toBe(3)
    expect(JSON.parse(text).captions).toBe(1)
    expect(text).not.toContain('/media/')
    expect(text).not.toContain('token')
    expect(text).not.toContain('https://')
  })

  it('stays far below the 12k context budget for a 500-clip project', () => {
    const edl = makeEdl()
    edl.tracks[0].clips = Array.from({ length: 500 }, (_, i) => ({
      id: `v1-${i}`, source_id: 'img-a', start: i * 0.5, duration: 0.5, in: 0,
    }))
    edl.project.duration = 250
    const text = summarizeChips(edl, { revision: 7, playheadMs: 1000, selectedClipIds: [] })
    expect(text.length).toBeLessThan(12000)
    expect(JSON.parse(text).clips).toBe(500)
  })

  it('defaults a missing state without throwing', () => {
    const text = summarizeChips(undefined, undefined)
    expect(JSON.parse(text).clips).toBe(0)
    expect(JSON.parse(text).duration_s).toBe(0)
  })
})
