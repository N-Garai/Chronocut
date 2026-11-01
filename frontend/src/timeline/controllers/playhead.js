/**
 * timeline/controllers/playhead.js — pointer session controller for the
 * decision 5). Preview patches the playhead via callback; commit fires on
 * pointerup. Captures the pointer so drags stay smooth without per-frame
 * React state thrash.
 *
 * attachPlayhead({ container, getMs, setMs, onCommit, pps })
 *   container: the scrollable timeline body (ruler or track area);
 *   returns a cleanup fn for the listeners.
 */
export function attachPlayhead({ container, getXMs, setPreview, commit, pps = 50 }) {
  const handler = async (ev) => {
    if (ev.button !== 0) return
    ev.preventDefault()
    container.setPointerCapture?.(ev.pointerId)
    let active = true

    const move = (e) => {
      if (!active) return
      const rect = container.getBoundingClientRect()
      const x = e.clientX - rect.left + (container.scrollLeft || 0)
      setPreview(xMsFromPx(x, pps))
    }
    const up = (e) => {
      if (!active) return
      active = false
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      try { container.releasePointerCapture?.(ev.pointerId) } catch { /* noop */ }
      const rect = container.getBoundingClientRect()
      const x = e.clientX - rect.left + (container.scrollLeft || 0)
      commit(xMsFromPx(x, pps))
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    // initial preview immediately for a click-seek
    const rect = container.getBoundingClientRect()
    const x = ev.clientX - rect.left + (container.scrollLeft || 0)
    setPreview(xMsFromPx(x, pps))
  }
  container.addEventListener('pointerdown', handler)
  return () => container.removeEventListener('pointerdown', handler)
}

export function xMsFromPx(px, pps) {
  return Math.round((Number(px) / pps) * 1000)
}
