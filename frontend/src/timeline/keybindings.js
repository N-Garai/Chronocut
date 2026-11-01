/**
 * timeline/keybindings.js — single shortcut registry with sequential
 * multi-key combos ("g g" groups), Space transport, and Alt-disabled snaps.
 */
export function matchesKeys(event, { ctrl, meta, shift, alt, keys }) {
  const c = ctrl ? (event.ctrlKey) : null
  const mt = meta ? (event.metaKey) : null
  if (ctrl && !c) return false
  if (meta && !mt) return false
  if (shift && !event.shiftKey) return false
  if (alt && !event.altKey) return false
  if (!ctrl && (event.ctrlKey || event.metaKey)) return false
  const k = event.key.toLowerCase()
  return keys.includes(k)
}

export const DEFAULT_SHORTCUTS = [
  { name: 'undo', combo: [{ ctrl: true, keys: ['z'] }] },
  { name: 'redo', combo: [{ ctrl: true, shift: true, keys: ['z'] }] },
  { name: 'split', combo: [{ keys: ['s'] }] },
  { name: 'delete', combo: [{ keys: ['backspace'] }, { keys: ['delete'] }] },
  { name: 'play_pause', combo: [{ keys: [' '] }] },
  { name: 'zoom_in', combo: [{ keys: ['='] }, { keys: ['+'] }] },
  { name: 'zoom_out', combo: [{ keys: ['-'] }] },
  { name: 'toggle_snapping', combo: [{ keys: ['n'] }] },
  { name: 'toggle_ripple', combo: [{ keys: ['r'] }] },
  { name: 'toggle_agent', combo: [{ keys: ['a'], alt: true }] },
  { name: 'select_all', combo: [{ ctrl: true, keys: ['a'] }] },
]

/** Resolve a key event to a shortcut name using a pending prefix combo. */
export function resolve(event, prefix = null, shortcuts = DEFAULT_SHORTCUTS) {
  if (prefix) return null // g-prefixed combos: extend later (P1)
  for (const s of shortcuts) {
    if (s.combo.some((c) => matchesKeys(event, c))) return s.name
  }
  return null
}
