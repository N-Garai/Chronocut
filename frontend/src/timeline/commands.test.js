import { describe, expect, it } from 'vitest'

import {
  APPLIED_OPS, applyBatch, applyOp, cmdAddCaption, cmdBatch, cmdDelete,
  cmdDeleteRipple, cmdEnsureCaptions, cmdMove, cmdRemoveSilence, cmdSetProfile,
  cmdSetSpeed, cmdSplit, cmdSplitEvery, cmdTrim, cmdUpdateCaption,
} from './commands'
import { clipsOf, idsOf, makeEdl } from './fixtures/edlFixture'

describe('command factories map to server ops', () => {
  it('converts client milliseconds to EDL seconds', () => {
    expect(cmdSplit('v1-02', 7200)).toEqual({ op: 'split', args: { clip_id: 'v1-02', at: 7.2 } })
    expect(cmdTrim('v1-02', 'start', 6200)).toEqual(
      { op: 'trim', args: { clip_id: 'v1-02', edge: 'start', time: 6.2 } },
    )
    expect(cmdMove('v1-02', 1234)).toEqual({ op: 'move', args: { clip_id: 'v1-02', to: 1.234 } })
  })

  it('carries ripple and macro defaults', () => {
    expect(cmdDelete('v1-01').args).toEqual({ clip_id: 'v1-01', ripple: true })
    expect(cmdDeleteRipple('v1-01')).toEqual(cmdDelete('v1-01'))
    expect(cmdSplitEvery(3)).toEqual({ op: 'split_every', args: { seconds: 3 } })
    expect(cmdRemoveSilence().args).toEqual({ min_duration: 0.4, noise_db: -35 })
    expect(cmdSetProfile('reel_vertical').args).toEqual({ profile: 'reel_vertical' })
    expect(cmdEnsureCaptions()).toEqual({ op: 'ensure_captions', args: {} })
  })

  it('clamps caption text and speed to the schema bounds', () => {
    expect(cmdAddCaption(0, 1000, 'x'.repeat(400)).args.text).toHaveLength(240)
    expect(cmdUpdateCaption('c1-01', 'y'.repeat(400)).args.text).toHaveLength(240)
    // the server clamps 0.25..4; the local draft clamps identically
    const out = applyOp(makeEdl(), cmdSetSpeed('v1-01', 99))
    expect(clipsOf(out)[0].speed).toBe(4)
  })

  it('only exposes ops the server understands', () => {
    expect(APPLIED_OPS).toEqual(expect.arrayContaining([
      'split', 'split_every', 'trim', 'delete', 'move',
      'set_effect', 'set_grade_all', 'set_transition_all', 'set_motion_all',
      'set_speed', 'add_caption', 'update_caption', 'replace_music',
      'ensure_captions', 'remove_silence', 'set_profile',
    ]))
    expect(cmdBatch([[cmdSplit('v1-01', 1000)], null, []]).length).toBe(1)
  })
})

describe('local draft application', () => {
  it('splits at 7.2 s into correct halves with a source in-offset', () => {
    const out = applyOp(makeEdl(), cmdSplit('v1-02', 7200))
    const clips = clipsOf(out)
    expect(idsOf(out)).toEqual(['v1-01', 'v1-02', 'v1-04', 'v1-03'])
    const [left, right] = [clips[1], clips[2]]
    expect(left.start).toBe(5)
    expect(left.duration).toBe(2.2)
    expect(right.start).toBe(7.2)
    expect(right.duration).toBe(2.8)
    expect(right.in).toBe(2.2)
  })

  it('never mutates the input EDL', () => {
    const edl = makeEdl()
    const snapshot = JSON.stringify(edl)
    applyOp(edl, cmdSplit('v1-02', 7200))
    expect(JSON.stringify(edl)).toBe(snapshot)
  })

  it('rejects a split outside the clip bounds', () => {
    expect(() => applyOp(makeEdl(), cmdSplit('v1-02', 5000))).toThrow(/outside clip/)
    expect(() => applyOp(makeEdl(), cmdSplit('nope', 1000))).toThrow(/not found/)
    expect(() => applyOp(makeEdl(), { op: 'nonsense', args: {} })).toThrow(/unknown op/)
  })

  it('ripple delete closes the gap and shortens the project', () => {
    const out = applyOp(makeEdl(), cmdDeleteRipple('v1-02'))
    expect(idsOf(out)).toEqual(['v1-01', 'v1-03'])
    expect(clipsOf(out)[1].start).toBe(5)
    expect(out.project.duration).toBe(10)
  })

  it('non-ripple delete leaves the gap open', () => {
    const out = applyOp(makeEdl(), cmdDelete('v1-02', { ripple: false }))
    expect(clipsOf(out)[1].start).toBe(10)
    expect(out.project.duration).toBe(15)
  })

  it('trims head and tail within shot bounds', () => {
    const head = clipsOf(applyOp(makeEdl(), cmdTrim('v1-01', 'start', 2000)))[0]
    expect(head.start).toBe(2)
    expect(head.duration).toBe(3)
    expect(head.in).toBe(2)
    const tail = clipsOf(applyOp(makeEdl(), cmdTrim('v1-01', 'end', 3000)))[0]
    expect(tail.duration).toBe(3)
    expect(() => applyOp(makeEdl(), cmdTrim('v1-01', 'start', 0))).toThrow(/head room/)
    expect(() => applyOp(makeEdl(), cmdTrim('v1-01', 'end', 0))).toThrow(/tail room/)
  })

  it('splits every N seconds from the playhead-independent boundaries', () => {
    const out = applyOp(makeEdl(), cmdSplitEvery(3))
    expect(idsOf(out).length).toBe(4)                       // one cut applied per call
    expect(clipsOf(out).some((c) => c.start === 3)).toBe(true)
    expect(out.project.duration).toBe(15)
    expect(() => applyOp(makeEdl(), cmdSplitEvery(0.1))).toThrow(/range/)
  })

  it('adds and updates captions on the caption track', () => {
    const withCap = applyOp(makeEdl(), cmdAddCaption(4000, 2000, 'a 1962 courtyard'))
    expect(clipsOf(withCap, 'c1').length).toBe(2)
    const updated = applyOp(withCap, cmdUpdateCaption('c1-02', 'edited line'))
    expect(clipsOf(updated, 'c1')[1].text).toBe('edited line')
  })

  it('queues server-side macro ops untouched', () => {
    for (const operation of [cmdEnsureCaptions(), cmdRemoveSilence(), cmdSetProfile('reel_vertical')]) {
      const out = applyOp(makeEdl(), operation)
      expect(idsOf(out)).toEqual(['v1-01', 'v1-02', 'v1-03'])
      expect(out.project.duration).toBe(15)
    }
  })

  it('applies a batch in order and stops on the first bad op', () => {
    const out = applyBatch(makeEdl(), [cmdSplit('v1-02', 7200), cmdDeleteRipple('v1-04')])
    expect(idsOf(out)).toEqual(['v1-01', 'v1-02', 'v1-03'])
    expect(clipsOf(out)[2].start).toBe(7.2)
    expect(() => applyBatch(makeEdl(), [cmdSplit('v1-02', 7200), cmdSplit('ghost', 1000)]))
      .toThrow(/not found/)
  })
})
