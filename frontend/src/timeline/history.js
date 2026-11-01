/**
 * timeline/history.js — full-snapshot undo stack.
 *
 * One *transaction* = one pushed snapshot. Batches from an agent plan and a
 * manual pointer-commit each push exactly one entry (max 30, matching
 * backend/app/edl/store.py revision cap behavior).
 *
 * Semantics: `present` = index into entries; entries[0] = original EDL.
 * `push` replaces the REDO tail and appends.
 */
export const MAX_HISTORY = 30

export function createHistory(initialEdl) {
  return {
    entries: [initialEdl],
    present: 0,
  }
}

/**
 * Start a transaction: normalized ops apply to the current draft; pushes one
 * snapshot. Returns { ok, edl, error } — never mutates the original on failure.
 */
export function applyTransaction(history, edl, applyFn) {
  let next = null
  try {
    next = applyFn(edl)
  } catch (e) {
    return { ok: false, edl, error: String(e?.message || e) }
  }
  if (!next || next === edl) return { ok: true, edl }
  const entries = history.entries.slice(0, history.present + 1)
  entries.push(next)
  const overflow = Math.max(0, entries.length - MAX_HISTORY)
  return {
    ok: true,
    edl: next,
    history: { entries: entries.slice(overflow), present: entries.length - overflow - 1 },
  }
}

export function undo(h) {
  return h.present > 0 ? { ...h, present: h.present - 1 } : h
}

export function redo(h) {
  return h.present < h.entries.length - 1 ? { ...h, present: h.present + 1 } : h
}

export function presentEdl(h) {
  return h.entries[h.present] || h.entries[0]
}

export function canUndo(h) { return h.present > 0 }
export function canRedo(h) { return h.present < h.entries.length - 1 }
