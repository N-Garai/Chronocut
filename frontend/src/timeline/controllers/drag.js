/**
 * timeline/controllers/drag.js — pointer drag for clip moves.
 * Preview yields { clipId, deltaMs }; commit gives the final delta for the
 * caller to convert into a move op (after snapping).
 */
export function attachDrag({ clipEl, clipId, pps = 50, onBegin, setPreview, commit }) {
  const start = (ev) => {
    if (ev.button !== 0) return
    ev.preventDefault()
    ev.stopPropagation()
    const startX = ev.clientX
    onBegin?.(clipId)
    let active = true
    let lastDx = null

    const move = (e) => {
      if (!active) return
      lastDx = e.clientX - startX
      setPreview({ clipId, deltaMs: xMsFromPx(lastDx, pps) })
    }
    const up = () => {
      if (!active) return
      active = false
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      try { clipEl.releasePointerCapture?.(ev.pointerId) } catch { /* noop */ }
      commit({ clipId, deltaMs: lastDx != null ? xMsFromPx(lastDx, pps) : null })
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
