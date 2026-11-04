import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { eventsUrl, getAgentActivity, getEdl, getRenders, postEdlOperations, putEdl, renderedUrl, videoUrl } from '../lib/api'
import { applyBatch } from '../timeline/commands'
import { diffRevisions, allClipIds } from '../lib/edl'
import { mergeRows } from '../timeline/agentTelemetry'

const SAVE_DEBOUNCE_MS = 250
const MAX_HISTORY = 30

const IS_TERMINAL = (s) => ['COMPLETE', 'FAILED', 'NEEDS_REVIEW', 'CANCELLED', 'DELETED'].includes(s)

/**
 * useTimeline — the timeline page's single data owner
 * (draft EDL, optimistic ops, history, SSE revisions):
 *
 *  - draftEdl with baseRevision; ops execute optimistically and the debounced
 *    server save (250 ms) POSTs operations; server truth replaces the draft.
 *  - undo = full EDL snapshots (max 30). One batch = one undo entry; agent
 *    plans and manual edits share execute().
 *  - live SSE: edl_updated refetches when not dirty; missed revisions
 *    self-heal (seq-skip + periodic reconcile); dirty drafts queue behind
 *    the conflict/remote-update banner instead of being overwritten.
 *  - tracked revisions: renderedRevision + previewUrl for the stale badge.
 */
export function useTimeline(jobId) {
  const [edl, setEdl] = useState(null)
  const [revision, setRevision] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saveStatus, setSaveStatus] = useState('idle')
  const [lastSavedAt, setLastSavedAt] = useState(null)
  const [conflict, setConflict] = useState(null) // server revision on 409
  const [remoteUpdate, setRemoteUpdate] = useState(false) // queued behind dirty
  const [diff, setDiff] = useState({ added: [], changed: [], removed: [], at: 0 })
  const [sseConnected, setSseConnected] = useState(false)
  const [activity, setActivity] = useState([])
  const [lastError, setLastError] = useState(null)
  const [render, setRender] = useState(null) // {render_id, status, url, revision}

  const historyRef = useRef([]) // [{edl, revision}]
  const historyPos = useRef(-1)
  const saveTimer = useRef(null)
  const inflight = useRef(false)
  const pendingOps = useRef([])
  const dirtyRef = useRef(false)
  // synchronous mirrors of edl/revision — execute() must apply ops against the
  // latest state even when React defers queued setState updaters (batched
  // ticks right after an SSE refetch would otherwise silently drop the op)
  const edlRef = useRef(null)
  const revisionRef = useRef(null)
  // optimistic revision while in flight is not tracked; server echo wins
  const dirty = saveStatus === 'pending' || saveStatus === 'saving'
  dirtyRef.current = dirty

  // ---------------- history helpers ----------------
  const pushHistory = useCallback((snapshot) => {
    const entries = historyRef.current.slice(0, historyPos.current + 1)
    entries.push(snapshot)
    const overflow = Math.max(0, entries.length - MAX_HISTORY)
    historyRef.current = entries.slice(overflow)
    historyPos.current = entries.length - overflow - 1
  }, [])

  const setBase = useCallback((nextEdl, nextRevision, { resetHistory = false, record = false } = {}) => {
    edlRef.current = nextEdl
    revisionRef.current = nextRevision
    setEdl(nextEdl)
    setRevision(nextRevision)
    if (record) pushHistory({ edl: nextEdl, revision: nextRevision })
    if (resetHistory) {
      historyRef.current = [{ edl: nextEdl, revision: nextRevision }]
      historyPos.current = 0
    }
  }, [pushHistory])

  const fetchEdl = useCallback(async ({ keepHistory = true } = {}) => {
    if (!jobId) return null
    try {
      const data = await getEdl(jobId)
      edlRef.current = data.edl
      revisionRef.current = data.revision
      setEdl((prev) => {
        if (prev) setDiff({ ...diffRevisions(prev, data.edl), at: Date.now() })
        return data.edl
      })
      setRevision(data.revision)
      if (!keepHistory || historyPos.current < 0) {
        historyRef.current = [{ edl: data.edl, revision: data.revision }]
        historyPos.current = 0
      }
      return data.edl
    } catch (e) {
      if (e.status === 404) return null
      throw e
    } finally {
      setLoading(false)
    }
  }, [jobId])

  useEffect(() => {
    let alive = true
    fetchEdl({ keepHistory: false })
    return () => { alive = false }
  }, [jobId, fetchEdl])

  const refresh = useCallback(() => fetchEdl(), [fetchEdl])

  // ---------------- server save path ----------------
  const flushSave = useCallback(async () => {
    if (inflight.current || !pendingOps.current.length) return
    const ops = pendingOps.current
    pendingOps.current = []
    inflight.current = true
    setSaveStatus('saving')
    try {
      const data = await postEdlOperations(jobId, ops)
      setConflict(null)
      setBase(data.edl, data.revision)
      setSaveStatus('saved')
      setLastSavedAt(Date.now())
    } catch (e) {
      if (e.status === 409) {
        setConflict(e.detail?.stale_revision ?? 'conflict')
        setSaveStatus('conflict')
      } else {
        setLastError(String(e?.message || e))
        setSaveStatus('error')
      }
    } finally {
      inflight.current = false
      if (pendingOps.current.length) flushSave()
    }
  }, [jobId, setBase])

  const scheduleSave = useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => { flushSave() }, SAVE_DEBOUNCE_MS)
  }, [flushSave])

  // ---------------- command execution ----------------
  const execute = useCallback((ops, { note = 'edit' } = {}) => {
    if (!Array.isArray(ops) || ops.length === 0) return false
    if (!edlRef.current) return false
    let next
    try {
      next = applyBatch(edlRef.current, ops)
    } catch (e) {
      setLastError(String(e?.message || e))
      return false
    }
    if (!next || next === edlRef.current) return false
    edlRef.current = next
    revisionRef.current = (revisionRef.current ?? 1) + 1
    setEdl(next)
    setRevision(revisionRef.current)
    pushHistory({ edl: next, revision: revisionRef.current })
    pendingOps.current.push(...ops)
    setSaveStatus('pending')
    scheduleSave()
    return true
  }, [pushHistory, scheduleSave])

  // ---------------- undo / redo ----------------
  const applyHistory = useCallback(async (dir) => {
    const pos = historyPos.current + dir
    const target = historyRef.current[pos]
    if (!target) return false
    historyPos.current = pos
    edlRef.current = target.edl
    revisionRef.current = target.revision
    setEdl(target.edl)
    setRevision(target.revision)
    setSaveStatus('saved')
    try {
      // full-EDL replace keeps the server consistent with the snapshot
      const data = await putEdl(jobId, target.edl)
      setBase(data.edl, data.revision)
    } catch (e) {
      if (e.status === 409) { setConflict(e.detail?.stale_revision ?? 'conflict'); setSaveStatus('conflict') }
      else setSaveStatus('error')
    }
    return true
  }, [jobId, setBase])

  const undo = useCallback(() => applyHistory(-1), [applyHistory])
  const redo = useCallback(() => applyHistory(1), [applyHistory])

  // ---------------- telemetry cold-load replay ----------------
  useEffect(() => {
    if (!jobId) return undefined
    let alive = true
    setActivity([])
    getAgentActivity(jobId, 50).then((res) => {
      if (!alive) return
      const rows = Array.isArray(res?.activity) ? res.activity : []
      if (rows.length) setActivity((prev) => mergeRows(prev, rows, 'replay'))
    })
    return () => { alive = false }
  }, [jobId])

  // ---------------- SSE sync ----------------
  useEffect(() => {
    if (!jobId) return
    let es
    try { es = new EventSource(eventsUrl(jobId)) } catch { return }
    es.onopen = () => setSseConnected(true)
    es.onerror = () => setSseConnected(false)
    const handleData = (ev) => {
      let data
      try { data = JSON.parse(ev.data) } catch { return }
      if (data?.stage === 'agent_activity') {
        setActivity((rows) => mergeRows(rows, [data], 'live'))
        return
      }
      if (data?.stage === 'edl_updated') {
        const incomingRev = Number(data.edl_revision || 0)
        if (incomingRev && revision != null && incomingRev <= revision) return
        if (dirtyRef.current) { setRemoteUpdate(true); return }
        setConflict(null)
        fetchEdl()
        if (incomingRev && revision != null && incomingRev - revision > 1) fetchEdl()
        return
      }
      if (data?.stage === 'render_completed') {
        const doc = data.render_doc || null
        if (doc) setRender({ ...doc, url: renderedUrl(jobId, doc.render_id) })
        else fetchEdl()
      }
    }
    // The backend emits named events for the feed + revision bus (so they
    // never reach onmessage); listen to both shapes on one shared handler.
    es.addEventListener('agent_activity', handleData)
    es.addEventListener('edl_revision', handleData)
    es.onmessage = handleData
    const close = () => { es.close() }
    es.addEventListener('done', close)
    return () => es.close()
  }, [jobId, revision, fetchEdl])

  // ---------------- renders ----------------
  const refreshRenders = useCallback(async () => {
    if (!jobId) return
    try {
      const r = await getRenders(jobId)
      const list = r?.renders || []
      if (list.length) {
        const doc = list[list.length - 1]
        setRender({ ...doc, url: renderedUrl(jobId, doc.render_id) })
        return
      }
      // No registered render doc — the in-process compile path serves the
      // finished video straight from /video. A ranged GET probes existence
      // cheaply (404 keeps the empty state; HEAD is 405 on FastAPI routes).
      const res = await fetch(videoUrl(jobId), { headers: { Range: 'bytes=0-1' } })
      if (res.ok || res.status === 206) setRender({ status: 'READY', revision: null, url: videoUrl(jobId) })
    } catch { /* none yet */ }
  }, [jobId])

  useEffect(() => {
    if (jobId && revision != null) refreshRenders()
  }, [jobId, revision, refreshRenders])

  /**
   * Stale badge: preview render belongs to an older revision, or a post-exec
   * edit happened since the last render completion.
   */
  const renderedRevision = render?.status === 'READY' ? Number(render.revision) : null
  const previewStale = revision != null && revision > (renderedRevision ?? -1)

  /** Clear the up-front presentational diff pulse (1.5 s). */
  const clearDiff = useCallback(() => setDiff({ added: [], changed: [], removed: [], at: 0 }), [])

  const reloadServer = useCallback(async () => {
    setConflict(null)
    setRemoteUpdate(false)
    pendingOps.current = []
    setSaveStatus('idle')
    await fetchEdl({ keepHistory: false })
  }, [fetchEdl])

  return useMemo(() => ({
    edl, revision, loading, saveStatus, lastSavedAt, conflict, remoteUpdate,
    dirty,
    canUndo: historyPos.current > 0,
    canRedo: historyPos.current < historyRef.current.length - 1,
    undo, redo, execute, refresh, reloadServer,
    diff, clearDiff,
    sseConnected, activity,
    render, renderedRevision, previewStale,
    lastError,
  }), [edl, revision, loading, saveStatus, lastSavedAt, conflict, remoteUpdate, dirty, undo, redo, execute, refresh, reloadServer, diff, clearDiff, sseConnected, activity, render, renderedRevision, previewStale, lastError])
}

export default useTimeline
