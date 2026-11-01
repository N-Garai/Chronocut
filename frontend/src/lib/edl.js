/**
 * lib/edl.js — client-side EDL helpers.
 *
 * The server EDL stores times in seconds rounded to 3 decimals; the client
 * works in integer milliseconds. All conversions live here and in
 * timeline/time.js so no float drift can enter through ad-hoc math.
 */
export const TRACK_ORDER = ['v1', 'c1', 'a1', 'm1', 's1']

export const TRACK_LABELS = {
  v1: 'Video',
  c1: 'Captions',
  a1: 'Narration',
  m1: 'Music',
  s1: 'SFX',
}

export const TRACK_TYPE = {
  v1: 'video',
  c1: 'caption',
  a1: 'narration',
  m1: 'music',
  s1: 'sfx',
}

// Seconds (EDL) <-> integer milliseconds (client)
export function edlToMs(s) {
  const n = Number(s)
  if (n == null || Number.isNaN(n) || !Number.isFinite(n)) return null
  return Math.round(n * 1000)
}

export function msToEdl(ms) {
  const n = Math.round(Number(ms))
  if (!Number.isFinite(n)) return 0
  // integer ms is exactly 3-decimal seconds
  return n / 1000
}

export function formatMs(ms) {
  const t = Math.max(0, Math.round(ms))
  const m = Math.floor(t / 60000)
  const s = Math.floor((t % 60000) / 1000)
  const frac = Math.floor((t % 1000) / 10)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(frac).padStart(2, '0')}`
}

export function formatSecond(s) {
  return formatMs(edlToMs(s) || 0)
}

/** All timeline clips (excluding caption rows handled separately). */
export function videoClips(edl) {
  const t = trackOf(edl, 'v1')
  return (t?.clips || []).slice().sort((a, b) => a.start - b.start || String(a.id).localeCompare(String(b.id)))
}

export function trackOf(edl, id) {
  return (edl?.tracks || []).find((t) => t.id === id) || null
}

export function findClip(edl, clipId) {
  for (const t of edl?.tracks || []) {
    const c = (t.clips || []).find((c) => String(c.id) === String(clipId))
    if (c) return { track: t.id, type: t.type, clip: c }
  }
  return null
}

export function clipEnd(clip) {
  return Math.round((Number(clip?.start || 0) + Number(clip?.duration || 0)) * 1000) / 1000
}

/** Project duration in ms. */
export function edlDurationMs(edl) {
  const d = Number(edl?.project?.duration || 0)
  return edlToMs(d) || 0
}

/**
 * Diff two EDL revisions by clip ID: added / changed / removed clip
 * ids for the presentational pulse. Presentational only; never mutates the EDL.
 */
export function diffRevisions(prev, next) {
  const ids = (e) => new Set(allClipIds(e))
  const prevIds = ids(prev)
  const nextIds = ids(next)
  const added = [...nextIds].filter((id) => !prevIds.has(id))
  const removed = [...prevIds].filter((id) => !nextIds.has(id))
  const changed = []
  for (const id of nextIds) {
    if (prevIds.has(id)) {
      const a = findClip(prev, id)?.clip
      const b = findClip(next, id)?.clip
      if (a && b && JSON.stringify(a) !== JSON.stringify(b)) changed.push(id)
    }
  }
  return { added, changed, removed }
}

export function allClipIds(edl) {
  const out = []
  for (const t of edl?.tracks || []) for (const c of t.clips || []) out.push(String(c.id))
  return out
}

/** Source still/clip lookup for the asset bin. */
export function sourceOf(edl, sourceId) {
  return (edl?.sources || []).find((s) => String(s.id) === String(sourceId)) || null
}
