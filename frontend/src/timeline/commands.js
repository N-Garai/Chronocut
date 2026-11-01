/**
 * timeline/commands.js — semantic command vocabulary mapped 1:1 onto the
 * server EDL operations.
 *
 * Commands produce *server operations* (units in seconds, per
 * backend/app/edl/operations.py). The client applies the same ops locally for
 * the optimistic draft; the server is truth. Undo = full EDL snapshots.
 */
export const APPLIED_OPS = [
  'split', 'split_every', 'trim', 'delete', 'move',
  'set_effect', 'set_grade_all', 'set_transition_all', 'set_motion_all',
  'set_speed', 'add_caption', 'update_caption', 'replace_music',
  'ensure_captions', 'remove_silence', 'set_profile',
]

function op(opname, args, extra = {}) {
  return { op: opname, args, ...extra }
}

// ---------------------------------------------------------------------------
// semantic command factories — each returns a plain server op batch
// ---------------------------------------------------------------------------

/** Split a clip at project time tMs (int ms). */
export const cmdSplit = (clipId, atMs) =>
  op('split', { clip_id: clipId, at: Math.round(atMs) / 1000 })

/** List of ops: split every N seconds across the video track. */
export const cmdSplitEvery = (seconds) =>
  op('split_every', { seconds: Number(seconds) })

/**
 * Trim clip edge to tMs. edge ∈ {'start','end'}.
 */
export const cmdTrim = (clipId, edge, atMs) =>
  op('trim', { clip_id: clipId, edge, time: Math.round(atMs) / 1000 })

/** Delete clip; ripple defaults true on both sides. */
export const cmdDelete = (clipId, { ripple = true } = {}) =>
  op('delete', { clip_id: clipId, ripple })

/** "ripple" here means: delete + shift subsequent clips left (server default). */
export const cmdDeleteRipple = (clipId) => cmdDelete(clipId, { ripple: true })

/** Move clip start to tMs. */
export const cmdMove = (clipId, toMs) =>
  op('move', { clip_id: clipId, to: Math.round(toMs) / 1000 })

export const cmdSetEffect = (clipId, effect, value) =>
  op('set_effect', { clip_id: clipId, effect, value: String(value) })

export const cmdSetGradeAll = (value) => op('set_grade_all', { value: String(value) })
export const cmdSetTransitionAll = (value) => op('set_transition_all', { value: String(value) })
export const cmdSetMotionAll = (value) => op('set_motion_all', { value: String(value) })
export const cmdSetSpeed = (clipId, value) => op('set_speed', { clip_id: clipId, value: Number(value) })
export const cmdAddCaption = (startMs, durationMs, text) =>
  op('add_caption', { start: Math.round(startMs) / 1000, duration: Math.round(durationMs) / 1000, text: String(text || '').slice(0, 240) })
export const cmdUpdateCaption = (clipId, text) => op('update_caption', { clip_id: clipId, text: String(text || '').slice(0, 240) })
export const cmdReplaceMusic = (sourceId) => op('replace_music', { source_id: String(sourceId) })
export const cmdEnsureCaptions = () => op('ensure_captions', {})
export const cmdRemoveSilence = (params = {}) =>
  op('remove_silence', { min_duration: Number(params.min_duration ?? 0.4), noise_db: Number(params.noise_db ?? -35) })
export const cmdSetProfile = (profile) => op('set_profile', { profile: String(profile) })

/** Batch = {ops:[...], server expects bare list at POST /edl/operations}. */
export const cmdBatch = (ops) => ops.flat().filter(Boolean)

// ---------------------------------------------------------------------------
// local application of ops to a draft EDL (optimistic mirror of the server)
// ---------------------------------------------------------------------------

function trackOf(edl, id) {
  return (edl?.tracks || []).find((t) => t.id === id) || null
}

function findClip(edl, clipId) {
  for (const t of edl?.tracks || []) {
    const i = (t.clips || []).findIndex((c) => String(c.id) === String(clipId))
    if (i >= 0) return { t, i, clip: t.clips[i] }
  }
  return null
}

function newClipId(track, existing) {
  let seq = 1
  for (const c of existing || []) {
    const m = /^([a-z]\w*)-(\d+)$/.exec(String(c.id || ''))
    if (m && m[1] === track) seq = Math.max(seq, Number(m[2]) + 1)
  }
  return `${track}-${String(seq).padStart(2, '0')}`
}

function recomputeDuration(edl) {
  let maxEnd = 0
  for (const t of edl?.tracks || []) {
    for (const c of t.clips || []) {
      maxEnd = Math.max(maxEnd, Number(c.start || 0) + Number(c.duration || 0))
    }
  }
  if (edl?.project) edl.project.duration = Math.round(maxEnd * 1000) / 1000
  return edl
}

/**
 * Apply one op to a draft EDL (deep-copied first). Mirrors the server
 * normalization used by backend/app/edl/operations.py.
 */
export function applyOp(edlIn, operation) {
  const edl = structuredClone(edlIn || {})
  const { op: opname, args = {} } = operation || {}
  if (!opname) throw new Error('applyOp: op missing')

  switch (opname) {
    case 'split': {
      const found = findClip(edl, args.clip_id)
      if (!found) throw new Error('split: clip not found')
      const c = found.clip
      const at = Number(args.at)
      if (!(at > c.start + 0.05 && at < c.start + c.duration - 0.05)) {
        throw new Error(`split: at ${at} outside clip ${c.start}..${(c.start + c.duration).toFixed(2)}`)
      }
      const speed = Number(c.speed || 1.0)
      const inOffset = Number(c.in || 0)
      const first = { ...c, duration: Math.round((at - c.start) * 1000) / 1000 }
      // right half: source in-point advances (source-time) by left-duration*speed
      const inDelta = (first.duration * speed) || 0
      const second = {
        ...c,
        id: newClipId(found.t.id, edl.tracks.flatMap((t) => t.clips || [])),
        start: at,
        duration: Math.round((c.start + c.duration - at) * 1000) / 1000,
        in: 'in' in c ? Math.round((inOffset + inDelta) * 1000) / 1000 : undefined,
        transition_in: c.transition_in ?? undefined,
      }
      found.t.clips = found.t.clips.map((x) => (String(x.id) === String(c.id) ? first : x))
      const idx = found.t.clips.findIndex((x) => String(x.id) === String(first.id))
      found.t.clips.splice(idx + 1, 0, second)
      break
    }
    case 'split_every': {
      const seconds = Number(args.seconds)
      if (!(seconds >= 0.5 && seconds <= 30)) throw new Error('split_every: seconds range 0.5..30')
      const v1 = trackOf(edl, 'v1')
      if (!v1) break
      let cuts = []
      let k = 0
      while (k * seconds < edl.project.duration) {
        cuts.push(Math.round(k * seconds * 1000) / 1000)
        k += 1
      }
      // skip 0-width cuts at existing boundaries
      const existing = new Set((v1.clips || []).map((c) => String(c.start)))
      cuts = cuts.filter((t) => t > 0.06 && !existing.has(String(t)))
      for (const at of cuts) {
        const target = (v1.clips || []).find((c) => at > c.start + 0.06 && at < c.start + c.duration - 0.06)
        if (!target) continue
        try {
          return applyOp(edl, { op: 'split', args: { clip_id: target.id, at } })
        } catch { /* skip unusable cuts */ }
      }
      break
    }
    case 'trim': {
      const found = findClip(edl, args.clip_id)
      if (!found) throw new Error('trim: clip not found')
      const c = found.clip
      const edge = args.edge
      const time = Number(args.time)
      if (edge !== 'start' && edge !== 'end') throw new Error('trim: edge must be start|end')
      if (edge === 'start') {
        if (time <= c.start + 0.001) throw new Error('trim: no head room left')
        const delta = Math.min(time, c.start + c.duration - 0.05) - c.start
        c.start = Math.round((c.start + delta) * 1000) / 1000
        if ('in' in c) c.in = Math.round((Number(c.in || 0) + delta * Number(c.speed || 1)) * 1000) / 1000
        c.duration = Math.round((c.duration - delta) * 1000) / 1000
      } else {
        const newDur = Math.round((time - c.start) * 1000) / 1000
        if (newDur < 0.05) throw new Error('trim: no tail room left')
        c.duration = newDur
      }
      break
    }
    case 'delete': {
      const found = findClip(edl, args.clip_id)
      if (!found) throw new Error('delete: clip not found')
      const ripple = args.ripple == null ? true : Boolean(args.ripple)
      const { start, duration } = found.clip
      found.t.clips = found.t.clips.filter((x) => String(x.id) !== String(found.clip.id))
      if (ripple) {
        for (const c of found.t.clips) {
          if (Number(c.start) >= Number(start)) c.start = Math.round((c.start - duration) * 1000) / 1000
        }
      }
      break
    }
    case 'move': {
      const found = findClip(edl, args.clip_id)
      if (!found) throw new Error('move: clip not found')
      found.clip.start = Math.max(0, Math.round(Number(args.to) * 1000) / 1000)
      found.t.clips.sort((a, b) => a.start - b.start || String(a.id).localeCompare(String(b.id)))
      break
    }
    case 'set_effect': {
      const found = findClip(edl, args.clip_id)
      if (!found) throw new Error('set_effect: clip not found')
      const { effect, value } = args
      const others = (found.clip.effects || []).filter((e) => e.type !== effect)
      found.clip.effects = [...others, { type: effect, value: String(value) }]
      break
    }
    case 'set_grade_all': {
      const v1 = trackOf(edl, 'v1')
      for (const c of (v1?.clips || [])) {
        c.effects = [...(c.effects || []).filter((e) => e.type !== 'grade'), { type: 'grade', value: String(args.value) }]
      }
      break
    }
    case 'set_transition_all': {
      const v1 = trackOf(edl, 'v1')
      for (const c of (v1?.clips || [])) c.transition_out = String(args.value)
      break
    }
    case 'set_motion_all': {
      const v1 = trackOf(edl, 'v1')
      for (const c of (v1?.clips || [])) {
        c.effects = [...(c.effects || []).filter((e) => e.type !== 'motion'), { type: 'motion', value: String(args.value) }]
      }
      break
    }
    case 'set_speed': {
      const found = findClip(edl, args.clip_id)
      if (!found) throw new Error('set_speed: clip not found')
      const v = Math.min(4, Math.max(0.25, Number(args.value) || 1))
      found.clip.speed = v
      break
    }
    case 'add_caption': {
      const c1 = trackOf(edl, 'c1')
      if (!c1) throw new Error('add_caption: no caption track')
      c1.clips = c1.clips || []
      c1.clips.push({
        id: newClipId('c1', edl.tracks.flatMap((t) => t.clips || [])),
        start: Math.round(Number(args.start) * 1000) / 1000,
        duration: Math.max(0.2, Math.round(Number(args.duration) * 1000) / 1000),
        text: String(args.text || '').slice(0, 240),
        style: { position: 'bottom', size: 42, color: '#ffffff', fade: true },
      })
      break
    }
    case 'update_caption': {
      const found = findClip(edl, args.clip_id)
      if (!found) throw new Error('update_caption: clip not found')
      found.clip.text = String(args.text || '').slice(0, 240)
      break
    }
    case 'replace_music': {
      for (const t of edl.tracks || []) {
        if (t.id !== 'm1') continue
        t.clips = (t.clips || []).filter(() => false)
        if (args.source_id) {
          t.clips.push({
            id: newClipId('m1', edl.tracks.flatMap((tt) => tt.clips || [])),
            start: 0,
            duration: edl.project?.duration || 10,
            source_id: String(args.source_id),
            gain: 0.22,
            duck_under: true,
          })
        }
      }
      break
    }
    case 'ensure_captions':
    case 'remove_silence':
    case 'set_profile':
      // Server-side macro ops that need backend data (ASR turns / waveform /
      // profile rendering). The optimistic draft queues them untouched; the
      // next server sync replaces the draft with truth.
      break
    default:
      throw new Error(`applyOp: unknown op '${opname}'`)
  }
  recomputeDuration(edl)
  return edl
}

/** Apply a batch of ops; returns the new EDL. Throws on the first bad op. */
export function applyBatch(edl, ops) {
  let out = edl
  for (const o of ops || []) out = applyOp(out, o)
  return out
}
