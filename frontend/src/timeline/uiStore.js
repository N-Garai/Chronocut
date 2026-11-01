/**
 * timeline/uiStore.js — view state store.
 *
 * Owns playheadMs, zoom (pps), scrollLeft, panel sizes, snapping/ripple
 * toggles and selection. Persisted per job in localStorage minus transient
 * selection/history (selection and history are cleared on reload).
 *
 * Tiny observable store — no external state library needed.
 */
const KEY = 'chronocut.ui'

function defaults() {
  return {
    pps: 50,
    scrollLeft: 0,
    playheadMs: 0,
    snapping: true,
    ripple: true,
    panelSizes: { telemetry: 320, inspector: 300 },
    panelsOpen: { telemetry: true, inspector: true },
  }
}

function load(jobId) {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || '{}')
    return { ...defaults(), ...(stored[jobId] || {}) }
  } catch {
    return defaults()
  }
}

function persist(jobId, state) {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || '{}')
    const { selectedClipIds, ...rest } = state
    stored[jobId] = rest
    localStorage.setItem(KEY, JSON.stringify(stored))
  } catch { /* private-mode browsing */ }
}

const listeners = new Set()

class UiStore {
  constructor() {
    this.state = defaults()
  }

  load(jobId) {
    this.state = load(jobId)
    this.emit()
  }

  set(patch, { persist: doPersist = true } = {}) {
    this.state = { ...this.state, ...patch }
    if (doPersist && this.jobId) persist(this.jobId, this.state)
    this.emit()
  }

  bind(jobId) {
    this.jobId = jobId
    this.load(jobId)
  }

  toggle(key) {
    this.set({ [key]: !this.state[key] })
  }

  subscribe(fn) {
    listeners.add(fn)
    return () => listeners.delete(fn)
  }

  emit() {
    for (const fn of listeners) fn(this.state)
  }
}

export const uiStore = new UiStore()
export default uiStore
