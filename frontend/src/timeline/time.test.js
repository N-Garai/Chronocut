import { describe, expect, it } from 'vitest'

import {
  PPS_DEFAULT, PPS_MAX, PPS_MIN,
  clampPps, pxToSecond, pxToTime, rulerTicks, tickLabel, timeToPx, timelineWidthMs,
} from './time'

describe('pps clamping', () => {
  it('clamps zoom into 10..200 and defaults garbage to 50', () => {
    expect(clampPps(0)).toBe(PPS_DEFAULT)     // 0 is unrepresentable -> default
    expect(clampPps(5)).toBe(PPS_MIN)
    expect(clampPps(-40)).toBe(PPS_MIN)
    expect(clampPps(9999)).toBe(PPS_MAX)
    expect(clampPps('abc')).toBe(PPS_DEFAULT)
    expect(clampPps(73.6)).toBe(74)
  })
})

describe('time <-> pixel scale', () => {
  it('is linear and stable at 50 px/s', () => {
    expect(timeToPx(1000, 50)).toBe(50)
    expect(timeToPx(7200, 50)).toBe(360)
    expect(pxToTime(360, 50)).toBe(7200)
  })

  it('zoom changes pixels but never the underlying time', () => {
    for (const pps of [10, 25, 50, 100, 200]) {
      expect(pxToTime(timeToPx(7200, pps), pps)).toBe(7200)
    }
  })

  it('keeps a 20-operation pointer round-trip inside 1 ms', () => {
    // ruler click -> px -> ms -> px -> ms, repeated, must not drift
    let ms = 12000
    for (let i = 0; i < 20; i += 1) {
      const px = timeToPx(ms, 50)
      ms = pxToTime(px, 50)
    }
    expect(Math.abs(ms - 12000)).toBeLessThanOrEqual(1)
  })

  it('converts px to 3-decimal EDL seconds', () => {
    expect(pxToSecond(360, 50)).toBe(7.2)
    expect(pxToSecond(0, 50)).toBe(0)
  })
})

describe('labels and ruler', () => {
  it('formats mm:ss', () => {
    expect(tickLabel(0)).toBe('00:00')
    expect(tickLabel(65000)).toBe('01:05')
    expect(tickLabel(-5)).toBe('00:00')
  })

  it('picks ticks at least 70 px apart at every zoom', () => {
    for (const pps of [10, 20, 50, 100, 200]) {
      const { major, minor, minorsPerMajor } = rulerTicks(pps)
      expect(major * pps).toBeGreaterThanOrEqual(70)
      expect(minor * pps).toBeGreaterThanOrEqual(14)
      expect(major).toBe(minor * minorsPerMajor)
    }
  })

  it('sizes the scroll canvas from the project duration', () => {
    const edl = { project: { duration: 15 } }
    expect(timelineWidthMs(edl, 50)).toBe(10500)      // (15000 + 6000) / 2
    expect(timelineWidthMs({ project: { duration: 0 } }, 100)).toBeGreaterThanOrEqual(10000)
  })
})
