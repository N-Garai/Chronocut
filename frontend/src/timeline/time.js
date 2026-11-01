/**
 * timeline/time.js — the one time↔pixel scale.
 *
 * `pps` (pixels per second) is clamped 10–200 so zoom can never make clips
 * or ruler labels unrepresentable. All conversions avoid float drift by
 * rounding to integers at the ms boundary.
 */
export const PPS_MIN = 10
export const PPS_MAX = 200
export const PPS_DEFAULT = 50

export const clampPps = (pps) => Math.min(PPS_MAX, Math.max(PPS_MIN, Math.round(Number(pps) || PPS_DEFAULT)))

/** ms -> px, relative to the timeline origin. */
export function timeToPx(ms, pps) {
  return (Math.round(ms) / 1000) * pps
}

/** px -> integer ms. */
export function pxToTime(px, pps) {
  return Math.round((Number(px) / pps) * 1000)
}

/** px -> EDL seconds (3 decimals). */
export function pxToSecond(px, pps) {
  const ms = pxToTime(px, pps)
  return Math.round(ms / 10) / 100
}

/** ms -> "01:23.45" short label. */
export function tickLabel(ms) {
  const t = Math.max(0, Math.round(ms))
  const m = Math.floor(t / 60000)
  const s = Math.floor((t % 60000) / 1000)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/**
 * Adaptive ruler tick distances (px between major ticks) that read well at any
 * zoom: choose from px-scaled candidate intervals.
 */
export function rulerTicks(pps) {
  const candidates = [50, 100, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000]
  // major ticks should be >= 70px apart; minor ticks >= 14px
  let major = candidates.find((c) => c * pps >= 70) || candidates[candidates.length - 1]
  const minorsPerMajor = [2, 4, 5, 10].find((n) => (major / n) * pps >= 14) || 10
  return { major, minor: major / minorsPerMajor, minorsPerMajor }
}

export function timelineWidthMs(edl, pps) {
  const dur = Math.round(Number(edl?.project?.duration || 0) * 1000)
  return Math.max(10000, Math.round((dur + 6000) * (pps / 100)))
}
