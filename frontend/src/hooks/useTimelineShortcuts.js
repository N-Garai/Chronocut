import { useEffect } from 'react'
import { resolve } from '../timeline/keybindings'

/** Keyboard routing for the timeline page. Handlers map by shortcut name. */
export function useTimelineShortcuts(handlers, { enabled = true } = {}) {
  useEffect(() => {
    if (!enabled) return
    const onKey = (e) => {
      const target = e.target
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
      const name = resolve(e)
      if (!name) return
      const handler = handlers[name]
      if (typeof handler !== 'function') return
      e.preventDefault()
      handler()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [handlers, enabled])
}

export default useTimelineShortcuts
