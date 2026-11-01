import { describe, expect, it } from 'vitest'

import {
  TRACK_ORDER, allClipIds, clipEnd, diffRevisions, edlDurationMs, edlToMs,
  findClip, formatMs, formatSecond, msToEdl, sourceOf, trackOf, videoClips,
} from './edl'
import { makeEdl } from '../timeline/fixtures/edlFixture'

describe('second <-> millisecond conversion', () => {
  it('round-trips EDL seconds through integer ms', () => {
    for (const s of [0, 0.001, 7.2, 12.345, 61.5]) {
      const ms = edlToMs(s)
      expect(Number.isInteger(ms)).toBe(true)
      expect(msToEdl(ms)).toBeCloseTo(s, 6)
    }
  })

  it('rejects junk instead of producing NaN', () => {
    expect(edlToMs('nope')).toBeNull()
    expect(edlToMs(undefined)).toBeNull()
    expect(msToEdl('nope')).toBe(0)
  })
})

describe('labels', () => {
  it('formats mm:ss.cc', () => {
    expect(formatMs(0)).toBe('00:00.00')
    expect(formatMs(12345)).toBe('00:12.34')
    expect(formatMs(61500)).toBe('01:01.50')
    expect(formatMs(-100)).toBe('00:00.00')
    expect(formatSecond(7.2)).toBe('00:07.20')
  })
})

describe('lookups', () => {
  it('keeps the canonical track order and labels', () => {
    expect(TRACK_ORDER).toEqual(['v1', 'c1', 'a1', 'm1', 's1'])
    const edl = makeEdl()
    expect(trackOf(edl, 'c1').type).toBe('caption')
    expect(trackOf(edl, 'nope')).toBeNull()
    expect(sourceOf(edl, 'img-b').path).toBe('/media/b.png')
    expect(sourceOf(edl, 'missing')).toBeNull()
    expect(findClip(edl, 'v1-03')).toMatchObject({ track: 'v1', type: 'video' })
    expect(findClip(edl, 'ghost')).toBeNull()
  })

  it('derives clip end, project duration, and clip ids', () => {
    const edl = makeEdl()
    expect(clipEnd({ start: 5, duration: 5 })).toBe(10)
    expect(clipEnd(undefined)).toBe(0)
    expect(edlDurationMs(edl)).toBe(15000)
    expect(allClipIds(edl)).toEqual(['v1-01', 'v1-02', 'v1-03', 'c1-01'])
  })

  it('sorts video clips by start then id', () => {
    const edl = makeEdl()
    edl.tracks[0].clips = [
      { id: 'v1-b', start: 5, duration: 2 },
      { id: 'v1-a', start: 5, duration: 2 },
      { id: 'v1-0', start: 0, duration: 5 },
    ]
    expect(videoClips(edl).map((c) => c.id)).toEqual(['v1-0', 'v1-a', 'v1-b'])
  })
})

describe('revision diffing (presentational pulses only)', () => {
  it('reports added, changed, and removed clip ids', () => {
    const prev = makeEdl()
    const next = makeEdl()
    next.revision = 2
    next.tracks[0].clips = [
      { id: 'v1-01', source_id: 'img-a', start: 0, duration: 2.2, in: 0 },   // changed
      { id: 'v1-09', source_id: 'img-x', start: 2.2, duration: 2.8, in: 2.2 }, // added
    ]
    const diff = diffRevisions(prev, next)
    expect(diff.added).toEqual(['v1-09'])
    expect(diff.removed.sort()).toEqual(['v1-02', 'v1-03'])
    expect(diff.changed).toEqual(['v1-01'])
  })

  it('is empty for identical revisions and never mutates its inputs', () => {
    const edl = makeEdl()
    const before = JSON.stringify(edl)
    expect(diffRevisions(edl, makeEdl())).toEqual({ added: [], changed: [], removed: [] })
    expect(JSON.stringify(edl)).toBe(before)
  })
})
