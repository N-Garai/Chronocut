import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Loader2, Play, Pause, SkipBack, SkipForward, Maximize, Minimize } from 'lucide-react'
import TimelineShell from '../components/timeline/TimelineShell'
import TimelineToolbar from '../components/timeline/TimelineToolbar'
import TransportBar from '../components/timeline/TransportBar'
import Inspector from '../components/timeline/Inspector'
import AssetBin from '../components/timeline/AssetBin'
import VideoPreview from '../components/timeline/VideoPreview'
import TextEditor from '../components/timeline/TextEditor'
import AgentTelemetryPanel from '../components/studio/AgentTelemetryPanel'
import { useJob } from '../hooks/useJob'
import useTimeline from '../hooks/useTimeline'
import { useAgent } from '../hooks/useAgent'
import { useTimelineShortcuts } from '../hooks/useTimelineShortcuts'
import uiStore from '../timeline/uiStore'
import { requiresConfirmation } from '../timeline/agentBridge'
import { cmdBatch, cmdSplit, cmdDelete, cmdSplitEvery, cmdRemoveSilence } from '../timeline/commands'
import { trackOf, edlDurationMs } from '../lib/edl'
import { assetThumbUrl, edlOtioUrl, getAssets, queueRender, waveformUrl } from '../lib/api'

const TERMINAL_OK = ['COMPLETE', 'NEEDS_REVIEW']

/**
 * TimelineStudio — the `/studio/:jobId/timeline` workspace.
 *
 * Professional video editing layout:
 *
 *   Left:   Asset bin (media upload + existing assets)
 *   Center: Video preview (top) + Timeline with tracks (bottom)
 *   Right:  Inspector (clip properties) + Agent Telemetry (live agent feed)
 *
 * The timeline opens IMMEDIATELY when a job exists, even while the pipeline
 * is still running. Clips appear on the track as the editor agent creates them
 * (EDL revisions stream over SSE). Users can scrub, select, trim, split and
 * issue agent commands while the pipeline is still working.
 */
export default function TimelineStudio() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()

  const agentEnabled = (import.meta.env?.VITE_AGENT_ENABLED ?? 'true') !== 'false'

  const { job, jobMissing, loaded } = useJob(jobId)
  const tl = useTimeline(jobId)
  const { edl, revision, loading, saveStatus, conflict } = tl

  const { playheadMs, setPlayheadMs, previewPlayhead, setPreviewPlayhead } = usePlayhead()
  const [selectedClipIds, setSelectedClipIds] = useState([])
  const [staleLocal, setStaleLocal] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [panelCollapsed, setPanelCollapsed] = useState(() => window.innerWidth < 1280)
  const [compact, setCompact] = useState(() => window.innerWidth < 1024)
  const [textEditorOpen, setTextEditorOpen] = useState(false)
  const [editingClipId, setEditingClipId] = useState(null)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1023px)')
    const onChange = () => setCompact(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => { uiStore.bind(jobId) }, [jobId])
  const [ui, setUi] = useState(uiStore.state)
  useEffect(() => uiStore.subscribe(setUi), [])

  useEffect(() => {
    if (!edl) return
    const t = Number(params.get('t'))
    if (Number.isFinite(t) && t > 0) setPlayheadMs(Math.min(Math.round(t * 1000), edlDurationMs(edl)))
  }, [edl?.revision])

  useEffect(() => {
    const guard = (e) => {
      if (saveStatus === 'pending' || saveStatus === 'saving') { e.preventDefault(); e.returnValue = '' }
    }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [saveStatus])

  useEffect(() => { setSelectedClipIds([]); setStaleLocal(false) }, [jobId])

  const [assetRows, setAssetRows] = useState([])
  useEffect(() => {
    let alive = true
    if (!jobId) return undefined
    getAssets(jobId).then((res) => {
      if (alive) setAssetRows((res?.assets || []).map((a) => ({ ...a, thumb: assetThumbUrl(a.thumb_url) })))
    })
    return () => { alive = false }
  }, [jobId, revision])

  const { waveforms, thumbs } = useMemo(() => {
    const w = {}
    const t = {}
    for (const a of assetRows) {
      const id = String(a.asset_id || a.id || '')
      if (!id) continue
      if (['narration', 'music', 'sfx', 'audio'].includes(a.kind)) {
        w[id] = waveformUrl(jobId, id)
      } else if (a.thumb) {
        t[id] = a.thumb
      }
    }
    return { waveforms: w, thumbs: t }
  }, [assetRows, jobId])

  const dirty = saveStatus === 'pending' || saveStatus === 'saving'
  const staleRemote = tl.remoteUpdate || (revision != null && tl.renderedRevision != null && tl.renderedRevision < revision)

  const runBatch = useCallback((ops) => {
    const ok = tl.execute(cmdBatch(ops))
    if (ok) setStaleLocal(true)
    return ok
  }, [tl])

  const v1Clips = edl ? (trackOf(edl, 'v1')?.clips || []) : []
  const findClip = useCallback((id) => v1Clips.find((c) => String(c.id) === String(id)), [v1Clips])

  const splitSelection = useCallback(() => {
    const clipId = selectedClipIds[0]
    const clip = clipId ? findClip(clipId) : null
    if (!clip) return
    if (playheadMs / 1000 <= Number(clip.start) + 0.05) return
    runBatch([cmdSplit(clip.id, playheadMs)])
  }, [selectedClipIds, findClip, playheadMs, runBatch])

  const deleteSelection = useCallback(() => {
    if (!selectedClipIds.length) return
    runBatch(selectedClipIds.slice(0, 20).map((id) => cmdDelete(id)))
  }, [selectedClipIds, runBatch])

  const onTrimCommit = useCallback(({ clipId, edge, deltaMs }) => {
    const clip = findClip(clipId)
    if (!clip || Math.abs(deltaMs) < 50) return
    const baseMs = edge === 'start' ? Number(clip.start) * 1000 : (Number(clip.start) + Number(clip.duration)) * 1000
    runBatch([{ op: 'trim', args: { clip_id: clipId, edge, time: Math.round(baseMs + deltaMs) / 1000 } }])
  }, [findClip, runBatch])

  const onDragCommit = useCallback(({ clipId, deltaMs }) => {
    if (deltaMs == null || Math.abs(deltaMs) < 50) return
    const clip = findClip(clipId)
    if (!clip) return
    runBatch([{ op: 'move', args: { clip_id: clipId, to: Math.max(0, Number(clip.start) + deltaMs / 1000) } }])
  }, [findClip, runBatch])

  // Agent planner
  const agent = useAgent(jobId, { playheadMs, selectedClipIds })
  const [pendingAgentPlan, setPendingAgentPlan] = useState(null)
  const sendAgentCommand = useCallback(async (message) => {
    setPendingAgentPlan(null)
    const plan = await agent.request(message, {
      onApply: (ops) => runBatch(ops),
      needsConfirmation: (p) => requiresConfirmation(p, edl),
    })
    const ops = plan?.operations || []
    if (ops.length > 0 && (plan.requires_confirmation || requiresConfirmation(plan, edl))) {
      setPendingAgentPlan(plan)
    }
  }, [agent, runBatch, edl])

  const confirmAgentPlan = useCallback(() => {
    if (!pendingAgentPlan) return
    agent.resolve(pendingAgentPlan, { applied: true, onApply: (ops) => runBatch(ops) })
    setPendingAgentPlan(null)
  }, [agent, pendingAgentPlan, runBatch])

  const cancelAgentPlan = useCallback(() => {
    if (!pendingAgentPlan) return
    agent.resolve(pendingAgentPlan, { applied: false })
    setPendingAgentPlan(null)
  }, [agent, pendingAgentPlan])

  const quickAction = useCallback((action, payload = {}) => {
    if (action === 'locate' && payload.clip_ids?.length) {
      const clip = payload.clip_ids.map((id) => findClip(id)).find(Boolean)
      if (clip) setPlayheadMs(Math.round(Number(clip.start) * 1000))
      setSelectedClipIds(payload.clip_ids.filter((id) => findClip(id)))
      return
    }
    const clipId = selectedClipIds[0]
    switch (action) {
      case 'cut_here': case 'split_left': case 'split_right':
        if (clipId) runBatch([cmdSplit(clipId, playheadMs)]); break
      case 'cut_every_3s': runBatch([cmdSplitEvery(3)]); break
      case 'delete_selected': deleteSelection(); break
      case 'remove_silence': runBatch([cmdRemoveSilence({})]); break
      default: break
    }
  }, [selectedClipIds, playheadMs, runBatch, deleteSelection, findClip])

  const selectedClip = selectedClipIds.map(findClip).find(Boolean) || null

  const inspectorChange = useCallback((clipId, op, args) => {
    if (op === 'set_effect') runBatch([{ op: 'set_effect', args: { clip_id: clipId, ...args } }])
    if (op === 'set_speed') runBatch([{ op: 'set_speed', args: { clip_id: clipId, value: args.value } }])
    if (op === 'set_caption') runBatch([{ op: 'update_caption', args: { clip_id: clipId, text: args.text } }])
  }, [runBatch])

  const captionChange = useCallback((clipId, text) => {
    runBatch([{ op: 'update_caption', args: { clip_id: clipId, text } }])
  }, [runBatch])

  const renderPreview = useCallback(async () => {
    setStaleLocal(false)
    try { await queueRender(jobId, { revision, profile: 'preview_480', kind: 'preview' }) } catch { /* surfaced via telemetry */ }
  }, [jobId, revision])

  const exportOtio = useCallback(() => {
    window.open(edlOtioUrl(jobId), '_blank')
  }, [jobId])

  // Video playback
  const videoRef = useRef(null)
  useEffect(() => {
    if (!playing || !tl.render?.url) return
    const v = videoRef.current
    if (!v) return
    v.currentTime = playheadMs / 1000
    v.play().catch(() => {})
    const onTime = () => setPlayheadMs(Math.round(v.currentTime * 1000))
    v.addEventListener('timeupdate', onTime)
    return () => v.removeEventListener('timeupdate', onTime)
  }, [playing, tl.render?.url, playheadMs])

  useEffect(() => {
    if (!playing) videoRef.current?.pause()
  }, [playing])

  const onSeek = useCallback((ms, { preview } = {}) => {
    if (preview) { setPreviewPlayhead(ms); return }
    setPreviewPlayhead(null)
    setPlayheadMs(Math.max(0, Math.round(ms)))
    if (playing && videoRef.current) videoRef.current.currentTime = ms / 1000
  }, [playing, setPlayheadMs, setPreviewPlayhead])

  const onZoom = useCallback((pps) => uiStore.set({ pps: Math.min(200, Math.max(10, pps)) }), [])

  useTimelineShortcuts(useMemo(() => ({
    undo: () => tl.undo(),
    redo: () => tl.redo(),
    play_pause: () => setPlaying((p) => !p),
    zoom_in: () => onZoom(ui.pps * 1.25),
    zoom_out: () => onZoom(ui.pps / 1.25),
    toggle_snapping: () => uiStore.toggle('snapping'),
    toggle_ripple: () => uiStore.toggle('ripple'),
    toggle_agent: () => setPanelCollapsed((c) => !c),
    split: splitSelection,
    delete: deleteSelection,
  }), [tl.undo, tl.redo, ui.pps, onZoom, splitSelection, deleteSelection]), { enabled: true })

  // Render
  if (jobMissing) return <StateBlock kind="not_found" onBack={() => navigate('/studio')} />
  if (!loaded || loading) return <StateBlock kind="loading" />
  if (job?.status === 'FAILED') return <StateBlock kind="render_failed" job={job} onBack={() => navigate('/studio')} />
  if (!edl) return <StateBlock kind="waiting_for_edl" job={job} onBack={() => navigate('/studio')} />

  return (
    <div className="flex h-screen flex-col bg-void text-bone">
      {/* Header */}
      <header className="flex items-center gap-3 border-b border-white/10 px-4 py-2">
        <button onClick={() => navigate('/studio')} className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest2 text-white/60 hover:text-amberglow">
          <ArrowLeft size={12} /> studio
        </button>
        <span className="font-mono text-[10px] uppercase tracking-widest2 text-amberglow">timeline</span>
        <span className="rounded border border-white/15 px-2 font-mono text-[10px] text-cyanglow">#{jobId.slice(0, 8)}</span>
        <span className="font-mono text-[10px] text-white/40" data-testid="revision-status">
          {saveStatus === 'saving' ? 'saving…' : saveStatus === 'conflict' ? `conflict: server r${conflict}` : saveStatus === 'error' ? 'save failed (retry on next edit)' : `r${revision ?? '–'}`}
        </span>
        {edl?.project?.profile && (
          <span className="rounded border border-white/15 px-2 font-mono text-[9px] uppercase tracking-widest text-white/50" data-testid="profile-label">{edl.project.profile}</span>
        )}
        {(saveStatus === 'conflict' || tl.remoteUpdate) && (
          <button onClick={() => tl.reloadServer()} data-testid="conflict-reload" className="rounded-full bg-amberglow px-3 py-1 font-mono text-[9px] font-bold uppercase tracking-widest text-void">
            {tl.remoteUpdate ? 'AI updated the cut — load it' : 'reload server cut'}
          </button>
        )}
        {tl.previewStale && <span className="status-chip border border-amber-400/40 bg-amber-400/10 text-amber-400" data-testid="stale-badge">preview stale</span>}
        {!tl.sseConnected && <span className="status-chip border border-red-400/30 bg-red-400/10 text-red-400">reconnecting…</span>}
        {pendingAgentPlan && (
          <span className="ml-auto flex items-center gap-2 rounded border border-amber-400/40 bg-amber-400/10 px-2 py-1" data-testid="agent-confirm">
            <span className="font-mono text-[9px] uppercase tracking-widest text-amber-300">{pendingAgentPlan.operations?.length || 0} ops · confirm destructive edit</span>
            <button onClick={confirmAgentPlan} className="rounded bg-amberglow px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-widest text-void" data-testid="agent-confirm-apply">apply</button>
            <button onClick={cancelAgentPlan} className="rounded border border-white/20 px-2 py-0.5 font-mono text-[9px] uppercase tracking-widest text-white/60 hover:text-white" data-testid="agent-confirm-cancel">cancel</button>
          </span>
        )}
      </header>

      {/* Timeline toolbar */}
      <TimelineToolbar
        selection={selectedClipIds}
        playheadMs={playheadMs}
        onSplit={splitSelection}
        onDelete={deleteSelection}
        onSplitEvery={() => runBatch([cmdSplitEvery(3)])}
        onRemoveSilence={() => runBatch([cmdRemoveSilence({})])}
        onRenderPreview={renderPreview}
        onExportOtio={exportOtio}
        canUndo={tl.canUndo}
        canRedo={tl.canRedo}
        onUndo={() => tl.undo()}
        onRedo={() => tl.redo()}
        saving={saveStatus === 'saving'}
        stale={staleRemote || staleLocal}
      />

      {/* Read-only banner */}
      {compact && (
        <div className="border-y border-amberglow/25 bg-amberglow/[0.07] px-4 py-1.5 text-center font-mono text-[9px] uppercase tracking-widest text-amberglow/80" data-testid="readonly-banner">
          read-only review on this screen — open on a wider screen to edit
        </div>
      )}

      {/* Main workspace */}
      <div className="flex min-h-0 flex-1">
        {/* Left: Asset bin */}
        {!compact && <AssetBin sources={edl?.sources || []} assets={assetRows} jobId={jobId} onSelect={(id) => setSelectedClipIds([id])} />}

        {/* Center: Preview + Timeline */}
        <div className="flex min-w-0 flex-1">
          <div className="relative aspect-video w-full max-w-xl overflow-hidden bg-black" data-testid="preview-pane">
            <VideoPreview
              src={tl.render?.url || null}
              playheadMs={playheadMs}
              durationMs={edlDurationMs(edl)}
              playing={playing}
              setPlayheadMs={setPlayheadMs}
              setPlaying={setPlaying}
            />
          </div>

          <TimelineShell
            edl={edl}
            playheadMs={playheadMs}
            previewPlayheadMs={previewPlayhead}
            pps={ui.pps}
            selectedClipIds={selectedClipIds}
            diff={tl.diff}
            snapping={ui.snapping}
            ripple={ui.ripple}
            readOnly={compact}
            waveforms={waveforms}
            thumbs={thumbs}
            onSeek={onSeek}
            onZoom={onZoom}
            onSelectMany={(ids, { additive } = {}) => setSelectedClipIds((prev) => additive ? [...new Set([...prev, ...ids])] : ids)}
            onClipSelect={(id, { additive } = {}) => setSelectedClipIds((prev) => additive ? (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]) : [id])}
            onTrimCommit={compact ? undefined : onTrimCommit}
            onDragCommit={compact ? undefined : onDragCommit}
          />
          <TransportBar
            playheadMs={playheadMs}
            durationMs={edlDurationMs(edl)}
            playing={playing}
            pps={ui.pps}
            onPlayPause={() => setPlaying((p) => !p)}
            onSeek={onSeek}
            snapping={ui.snapping}
            ripple={ui.ripple}
            onToggleSnapping={() => uiStore.toggle('snapping')}
            onToggleRipple={() => uiStore.toggle('ripple')}
            onZoom={onZoom}
          />
        </div>

        {/* Right sidebar: Inspector + Agent Telemetry */}
        {!compact && (
          <div className="flex flex-col min-w-[300px] max-w-[420px] border-l border-white/10">
            <Inspector
              selectedClip={selectedClip}
              onChange={inspectorChange}
              onCaptionChange={captionChange}
            />
            {agentEnabled && (
              <AgentTelemetryPanel
                jobId={jobId}
                edl={edl}
                rows={tl.activity}
                connected={tl.sseConnected}
                collapsed={panelCollapsed}
                onToggleCollapse={() => setPanelCollapsed((c) => !c)}
                onQuickAction={quickAction}
                onCommand={sendAgentCommand}
                agentBusy={agent.busy}
                selection={selectedClipIds}
                playheadMs={playheadMs}
                revision={revision}
                dirty={dirty}
                stale={staleRemote || staleLocal}
                renderState={tl.render?.status ? tl.render.status.toLowerCase() : 'unrendered'}
              />
            )}
          </div>
        )}
      </div>

      {/* Text editor overlay */}
      {textEditorOpen && selectedClip && (
        <TextEditor
          clip={selectedClip}
          onChange={inspectorChange}
          onClose={() => setTextEditorOpen(false)}
        />
      )}
    </div>
  )
}

function usePlayhead() {
  const [playheadMs, setPlayheadMs] = useState(0)
  const [previewPlayhead, setPreviewPlayhead] = useState(null)
  return { playheadMs, setPlayheadMs, previewPlayhead, setPreviewPlayhead }
}

function StateBlock({ kind, job, onBack }) {
  const copy = {
    loading: (<><Loader2 size={22} className="mx-auto animate-spin text-amberglow" /><p className="mt-3 font-mono text-[10px] uppercase tracking-widest2 text-white/40">loading timeline…</p></>),
    not_found: (<><p className="font-mono text-sm text-red-400">job not found</p><p className="mt-2 font-mono text-[10px] text-white/40">This job doesn't exist or was deleted.</p></>),
    pipeline_running: (<><Loader2 size={22} className="mx-auto animate-spin text-cyanglow" /><p className="mt-3 font-mono text-[10px] uppercase tracking-widest2 text-white/60">pipeline running — the timeline fills as agents work (v1 track live)</p><p className="mt-1 font-mono text-[9px] text-white/30">{job?.stage || 'processing'} · {Number.isFinite(job?.progress_percent) ? job.progress_percent : 0}%</p></>),
    waiting_for_edl: (<><Loader2 size={22} className="mx-auto animate-spin text-amberglow" /><p className="mt-3 font-mono text-[10px] uppercase tracking-widest2 text-white/60">waiting for the first EDL revision…</p></>),
    render_failed: (<><p className="font-mono text-sm text-red-400">pipeline failed</p><p className="mt-2 max-w-md font-mono text-[10px] text-white/40">{job?.error_log?.message || 'unknown error'}</p></>),
  }[kind]
  return (
    <div className="grid min-h-screen place-items-center bg-void text-bone">
      <div className="text-center">
        {copy}
        <br />
        <button onClick={onBack} className="mt-6 rounded-full border border-white/20 px-5 py-2 font-mono text-[10px] uppercase tracking-widest2 text-white/70 hover:border-amberglow hover:text-amberglow">
          ← back to studio
        </button>
      </div>
    </div>
  )
}