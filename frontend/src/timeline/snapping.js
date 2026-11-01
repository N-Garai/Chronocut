/**
 * timeline/snapping.js — pure candidate threshold snapping.
 *
 * Candidates are the boundaries of other clips in the same track plus global
 * boundaries (playhead, 0). Threshold is in px (6) converted to ms at the
 * current zoom so snapping feels identical at any zoom. Alt disables.
 */
export const SNAP_PX = 6

/** Build candidate ms boundaries near tMs for a given track (or null = any). */
export function snapCandidates(edl, tMs, trackId, { includePlayhead = false, playheadMs = 0, excludeClipIds = [] } = {}) {
  const out = new Set([0])
  for (const t of edl?.tracks || []) {
    if (trackId && t.id !== trackId) {
      // other tracks contribute boundaries only if includePlayhead-style
      // global snapping is on: (the ADR says same-track candidates)
      if (!includePlayhead) continue
    }
    for (const c of t.clips || []) {
      if (excludeClipIds.includes(String(c.id))) continue
      out.add(Math.round(Number(c.start) * 1000))
      out.add(Math.round((Number(c.start) + Number(c.duration)) * 1000))
    }
  }
  if (includePlayhead) out.add(Math.round(tMs))
  if (includePlayhead && playheadMs > 0) out.add(Math.round(playheadMs))
  return [...out].sort((a, b) => a - b)
}

/** Snap tMs to nearest candidate within threshold (px→ms via pps); returns null when no hit. */
export function snap(tMs, candidates, pps, { disabled = false } = {}) {
  if (disabled) return null
  const thresholdMs = Math.round((SNAP_PX / pps) * 1000)
  let best = null
  let bestD = Infinity
  for (const c of candidates) {
    const d = Math.abs(c - tMs)
    if (d <= thresholdMs && d < bestD) { best = c; bestD = d }
  }
  return best
}

export function snapOrRaw(tMs, candidates, pps, opts = {}) {
  const s = snap(tMs, candidates, pps, opts)
  return s == null ? Math.round(tMs) : s
}
