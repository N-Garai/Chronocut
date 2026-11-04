import { useEffect, useMemo, useRef, useState } from 'react'
import { Radio, Crosshair, ChevronDown, ChevronUp, Send, Copy, Loader2 } from 'lucide-react'
import { statusTone } from '../../timeline/agentTelemetry'
import { summarizeChips } from '../../timeline/snapshot'

const TONE_CLASS = {
  ok: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-400',
  error: 'border-red-400/40 bg-red-400/10 text-red-400',
  busy: 'border-cyanglow/40 bg-cyanglow/10 text-cyanglow',
  warn: 'border-amber-400/40 bg-amber-400/10 text-amber-400',
  idle: 'border-white/15 bg-white/5 text-white/50',
}

/**
 * AgentTelemetryPanel — right-most workspace column:
 * state chips, live agent_activity feed (replay then SSE), agent console
 * with quick-action chips and a natural-language command input.
 */
export default function AgentTelemetryPanel({
  jobId, edl, rows, connected,
  collapsed, onToggleCollapse,
  onQuickAction, onCommand, agentBusy, selection, playheadMs,
  revision, dirty, stale, renderState,
  jobStage, jobProgress, jobStatus,
}) {
  const [message, setMessage] = useState('')
  const [filterAgent, setFilterAgent] = useState('all')
  const [expanded, setExpanded] = useState(() => new Set())
  const feedRef = useRef(null)

  const visible = useMemo(() => {
    const filtered = filterAgent === 'all' ? rows : rows.filter((r) => r.agent === filterAgent)
    return filtered.slice(-20)
  }, [rows, filterAgent])

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
  }, [visible.length])

  const pipeNames = useMemo(() => [...new Set(rows.map((r) => r.agent))].slice(0, 8), [rows])

  if (collapsed) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center gap-2 border-l border-white/10 bg-carbon/60 py-3">
        <button onClick={onToggleCollapse} title="Open telemetry" className="rounded p-1 text-cyanglow hover:bg-white/10">
          <Radio size={14} />
        </button>
        <span className="[writing-mode:vertical-lr] font-mono text-[9px] uppercase tracking-widest text-white/35">telemetry</span>
      </aside>
    )
  }

  const chips = summarizeChips(edl, { revision, playheadMs, selection, dirty, stale, renderState })

  return (
    <aside className="flex w-[320px] shrink-0 flex-col border-l border-white/10 bg-carbon/60" data-testid="agent-telemetry">
      {/* header */}
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-white/70">
          <Radio size={13} className="text-cyanglow" /> agent telemetry
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'animate-pulse bg-cyanglow' : 'bg-red-400'}`} title={connected ? 'SSE live' : 'reconnecting…'} />
        </span>
        <button onClick={onToggleCollapse} className="rounded p-1 text-white/50 hover:bg-white/10" title="Collapse">
          <ChevronUp size={13} />
        </button>
      </div>

      {/* live pipeline progress (the same bar the studio page shows) */}
      {jobStage && jobStatus && !['COMPLETE', 'FAILED', 'NEEDS_REVIEW', 'CANCELLED', 'DELETED'].includes(jobStatus) && (
        <div className="border-b border-white/10 px-3 py-2" data-testid="pipeline-progress">
          <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-widest text-white/45">
            <span className="truncate">{jobStage}</span>
            <span className="text-cyanglow">{Number.isFinite(jobProgress) ? `${jobProgress}%` : ''}</span>
          </div>
          <div className="mt-1 h-1 overflow-hidden rounded bg-white/10">
            <div
              className="h-full bg-cyanglow transition-all duration-500"
              style={{ width: `${Math.max(2, Math.min(100, Number(jobProgress) || 0))}%` }}
            />
          </div>
        </div>
      )}

      {/* state chips */}
      <div className="grid grid-cols-2 gap-1.5 border-b border-white/10 px-3 py-2">
        {[
          ['revision', revision ?? '–', 'text-cyanglow'],
          ['duration', `${Math.round(Number(edl?.project?.duration || 0) * 10) / 10}s`, 'text-white/70'],
          ['clips', (edl?.tracks || []).find((t) => t.id === 'v1')?.clips?.length ?? 0, 'text-amberglow'],
          ['sel', selection.length, 'text-white/70'],
        ].map(([label, val, cls]) => (
          <div key={label} className="rounded border border-white/10 bg-white/[0.03] px-2 py-1">
            <span className="block font-mono text-[8px] uppercase tracking-widest text-white/35">{label}</span>
            <span className={`font-mono text-[11px] ${cls}`}>{String(val)}</span>
          </div>
        ))}
        {stale && (
          <div className="col-span-2 rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 font-mono text-[9px] uppercase tracking-widest text-amber-400">
            preview stale · render to update
          </div>
        )}
        {dirty && (
          <div className="col-span-2 rounded border border-cyanglow/30 bg-cyanglow/10 px-2 py-1 font-mono text-[9px] uppercase tracking-widest text-cyanglow">
            unsaved draft…
          </div>
        )}
      </div>

      {/* live feed */}
      <div ref={feedRef} className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-2 font-mono text-[10px]" data-lenis-prevent="true">
        <div className="mb-2 flex flex-wrap gap-1">
          <button
            onClick={() => setFilterAgent('all')}
            className={`rounded border px-1.5 py-0.5 text-[8px] uppercase tracking-widest ${filterAgent === 'all' ? 'border-cyanglow/50 text-cyanglow' : 'border-white/10 text-white/40'}`}
          >
            all
          </button>
          {pipeNames.map((a) => (
            <button
              key={a}
              onClick={() => setFilterAgent(a)}
              className={`rounded border px-1.5 py-0.5 text-[8px] uppercase tracking-widest ${filterAgent === a ? 'border-amberglow/60 text-amberglow' : 'border-white/10 text-white/40'}`}
            >
              {a}
            </button>
          ))}
        </div>
        {visible.length === 0 && (
          <p className="py-4 text-[9px] uppercase tracking-widest text-white/25">
            waiting for agent activity…
          </p>
        )}
        {visible.map((row) => {
          const tone = statusTone(row.status)
          const revDelta = row.revisionBefore != null && row.revisionAfter != null ? `r${row.revisionBefore}→r${row.revisionAfter}` : ''
          const key = String(row.seq) + row.action_id
          const hasOps = (row.operations?.length || 0) > 0
          const isOpen = expanded.has(key)
          const toggle = () => setExpanded((prev) => {
            const next = new Set(prev)
            if (next.has(key)) next.delete(key)
            else next.add(key)
            return next
          })
          return (
            <div key={key} className="rounded border border-white/[0.07] bg-white/[0.02] px-2 py-1">
              <div className="flex items-center gap-1.5">
                <span className={`status-chip shrink-0 border ${TONE_CLASS[tone] || TONE_CLASS.idle}`}>{row.status}</span>
                <span className="font-bold text-amberglow/90">{row.agent}</span>
                <span className="truncate text-white/55">{row.action}</span>
                {row.parentAgent && <span className="text-white/25">↳ under {row.parentAgent}</span>}
                {hasOps && (
                  <button
                    onClick={toggle}
                    className="ml-auto flex shrink-0 items-center gap-0.5 text-[9px] text-white/40 hover:text-cyanglow"
                    title={isOpen ? 'Hide the plan\'s operations' : 'Show the plan\'s operations'}
                    data-testid="feed-row-expand"
                  >
                    {isOpen ? <ChevronUp size={9} /> : <ChevronDown size={9} />}
                    {row.operations.length}
                  </button>
                )}
              </div>
              <div className="flex items-center justify-between text-[9px] text-white/35">
                <span className="truncate">{row.detail}</span>
                <span className="ml-2 shrink-0 text-white/30">
                  {row.modelBadge && (
                    <span
                      className="mr-1 rounded border border-white/10 px-1 py-px font-mono text-[8px] uppercase tracking-widest text-white/35"
                      title={`Model used: ${row.modelBadge}`}
                    >
                      {row.modelBadge}
                    </span>
                  )}
                  {revDelta}{row.durationMs ? ` · ${row.durationMs}ms` : ''}
                </span>
              </div>
              {(row.clipIds?.length || 0) > 0 && (
                <button
                  onClick={() => onQuickAction?.('locate', { clip_ids: row.clipIds })}
                  className="mt-0.5 flex items-center gap-1 text-[9px] text-cyanglow hover:text-cyanglow/70"
                  title="Locate affected clips on the timeline"
                >
                  <Crosshair size={9} /> locate {row.clipIds.length}
                </button>
              )}
              {hasOps && isOpen && (
                <ul className="mt-1 space-y-0.5 border-l border-cyanglow/30 pl-1.5" data-testid="feed-row-ops">
                  {row.operations.map((o, i) => (
                    <li key={`${o.op}-${i}`} className="flex items-center gap-1 text-[9px] text-white/50">
                      <span className="text-cyanglow/80">{o.op}</span>
                      {o.target && <span className="truncate text-white/35">{o.target}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </div>

      {/* console */}
      <div className="border-t border-white/10 p-2">
        <div className="mb-1.5 flex flex-wrap gap-1">
          {[
            ['Cut here', 'cut_here'],
            ['Split left', 'split_left'],
            ['Split right', 'split_right'],
            ['Cut every 3s', 'cut_every_3s'],
            ['Delete selected', 'delete_selected'],
            ['Remove silence', 'remove_silence'],
          ].map(([label, action]) => (
            <button
              key={action}
              onClick={() => onQuickAction?.(action)}
              className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-widest text-white/60 hover:border-cyanglow/60 hover:text-cyanglow"
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && message.trim()) {
                onCommand?.(message.trim())
                setMessage('')
              }
            }}
            placeholder="Tell the agent what to change…"
            data-testid="agent-command-input"
            className="min-w-0 flex-1 rounded border border-white/10 bg-white/[0.04] px-2 py-1.5 font-mono text-[10px] text-bone placeholder-white/25 outline-none focus:border-cyanglow/60"
          />
          <button
            onClick={() => { if (message.trim()) { onCommand?.(message.trim()); setMessage('') } }}
            disabled={agentBusy || !message.trim()}
            className="rounded bg-amberglow p-1.5 text-void disabled:opacity-30"
            title="Send to agent planner"
          >
            {agentBusy ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
          </button>
          <button
            onClick={() => navigator.clipboard?.writeText(chips).catch(() => {})}
            className="rounded border border-white/15 p-1.5 text-white/50 hover:text-white"
            title="Copy timeline summary (what the agent sees)"
          >
            <Copy size={12} />
          </button>
        </div>
      </div>
    </aside>
  )
}
