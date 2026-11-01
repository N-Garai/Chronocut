/**
 * timeline/controllers/resize.js — edge-drag trim with preview/commit.
 *
 * Preview yields { clip_id, edge, ms } so the UI can render the live trim
 * shadow; commit returns the proposed trimmed ms for the caller to turn into
 * a trim op (snapping applied by the caller via timeline/snapping.js).
 */
export function attachResize({ clipEl, edge, clipId, pps = 50, setPreview, commit }) {
  const start = (ev) => {
    ev.stopPropagation()
    ev.preventDefault()
    if (ev.button !== 0) return
    const startX = ev.clientX
    let active = true

    const move = (e) => {
      if (!active) return
      const dx = e.clientX - startX
      const ms = xMsFromPx(dx, pps)
      setPreview({ clipId, edge, deltaMs: ms })
    }
    const up = (e) => {
      if (!active) return
      active = false
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      try { clipEl.releasePointerCapture?.(ev.pointerId) } catch { /* noop */ }
      const dx = e.clientX - startX
      commit({ clipId, edge, deltaMs: xMsFromPx(dx, pps) })
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  clipEl.addEventListener('pointerdown', start)
  return () => clipEl.removeEventListener('pointerdown', start)
}

export function xMsFromPx(px, pps) {
  return Math.round((Number(px) / pps) * 1000)
}
