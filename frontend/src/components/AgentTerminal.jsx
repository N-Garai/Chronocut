import { useEffect, useRef, useState, useCallback } from 'react'
import { Terminal, Cpu, ChevronDown, ChevronRight, Play, Square } from 'lucide-react'
import RevealText from './RevealText'

const agentColors = {
  INGEST: 'text-cyanglow',
  ARCHIVIST: 'text-cyanglow',
  REFERENCE: 'text-violet-400',
  RAG: 'text-amberglow',
  SCREENWRITER: 'text-amberglow',
  I18N: 'text-cyanglow',
  DIRECTOR: 'text-violet-400',
  EDITOR: 'text-emerald-400',
  REVIEW: 'text-emerald-400',
  ORCHESTRATOR: 'text-bone',
  DONE: 'text-bone',
}

function eventTone(ev) {
  const msg = (ev.message || '').toLowerCase()
  if (ev.status === 'FAILED' || msg.includes('fail')) return 'error'
  if (ev.status === 'COMPLETE' || ev.status === 'NEEDS_REVIEW' || msg.includes('complete')) return 'done'
  if (msg.includes('analyz') || msg.includes('writing') || msg.includes('composing') || msg.includes('synthes') || msg.includes('render')) return 'tool'
  return 'ok'
}

function buildEventLines(events, jobStatus) {
  return events.map((ev, i) => {
    const stage = (ev.stage || 'ORCHESTRATOR').toUpperCase()
    const sub = ev.sub_agent ? String(ev.sub_agent) : null
    const parentSub = ev.parent_sub ? String(ev.parent_sub) : null
    return {
      id: `ev-${i}`,
      agent: sub || stage,
      parentStage: stage,
      parentSub,
      isSub: !!sub,
      depth: sub ? (parentSub ? 2 : 1) : 0,
      tone: eventTone(ev),
      text: ev.message || `${stage} @ ${ev.progress_percent ?? 0}%`,
      timestamp: ev.ts || new Date().toISOString(),
      progress: ev.progress_percent,
      expandable: false,
    }
  })
}

export default function AgentTerminal({ play = false, jobStatus, uploading, uploadError, events = [], onOpenTimeline = null }) {
  const boxRef = useRef(null)
  const feedRef = useRef(null)
  const [expandedLines, setExpandedLines] = useState({})
  const [cursorPhase, setCursorPhase] = useState(0)

  const isLive = !!jobStatus && (jobStatus.status === 'PROCESSING' || jobStatus.status === 'QUEUED')
  const isDone = !!jobStatus && jobStatus.status === 'COMPLETE'
  const isFailed = !!jobStatus && jobStatus.status === 'FAILED'
  const isReview = !!jobStatus && jobStatus.status === 'NEEDS_REVIEW'

  const lines = events.length > 0 ? buildEventLines(events, jobStatus) : (jobStatus ? [] : [])

  const toggleExpand = useCallback((id) => {
    setExpandedLines((prev) => ({ ...prev, [id]: !prev[id] }))
  }, [])

  useEffect(() => {
    if (!isLive) return
    const interval = setInterval(() => setCursorPhase((p) => (p + 1) % 4), 400)
    return () => clearInterval(interval)
  }, [isLive])

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
  }, [lines.length])

  const getCursorStyle = () => {
    if (!isLive) return {}
    const offsets = ['0%', '2%', '-1%', '1%']
    return { transform: `translateX(${offsets[cursorPhase]})` }
  }

  return (
    <section id="swarm" className="relative overflow-hidden px-6 py-28 sm:px-10">
      <div className="absolute inset-0 z-0">
        <video
          className="absolute inset-0 h-full w-full object-cover"
          src="/agent-telemetry.mp4"
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
        />
        <div className="absolute inset-0 bg-void/65" />
        <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-void to-transparent" />
        <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-void to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-b from-void/30 via-transparent to-void/30" />
      </div>

      <div className="relative z-10 mx-auto max-w-6xl">
        <div className="mb-12">
          <span className="font-mono text-[11px] uppercase tracking-widest3 text-cyanglow">
            [ 02 · AGENT TELEMETRY ]
          </span>
          <RevealText className="mt-4 font-display text-[clamp(2.5rem,7vw,5.5rem)] leading-[0.9] text-bone">
            THE SWARM IN THE WILD
          </RevealText>
          <RevealText
            as="p"
            className="mt-6 max-w-xl font-light leading-relaxed text-ash/70"
            stagger={0.008}
          >
            Specialised agents coordinate through a secure graph workflow.
            Watch them think, call tools, and cut the final film — streamed live.
          </RevealText>
        </div>

        <div ref={boxRef} className="overflow-hidden rounded-2xl border border-white/10 bg-[#070708] shadow-[0_40px_120px_-30px_rgba(0,0,0,0.9)]">
          <div className="flex items-center justify-between border-b border-white/10 bg-white/[0.03] px-5 py-3">
            <div className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-full bg-red-500/80" />
              <span className="h-3 w-3 rounded-full bg-amber-400/80" />
              <span className="h-3 w-3 rounded-full bg-emerald-400/80" />
            </div>
            <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest2 text-ash/50">
              <Terminal size={12} className="text-cyanglow" />
              {jobStatus?.job_id ? `job ${jobStatus.job_id.slice(0, 8)} — ${jobStatus.status || 'PROCESSING'}` : 'chronocut-agent-swarm — tty0'}
            </div>
            <div className="flex items-center gap-3">
              {isDone && onOpenTimeline && (
                <button
                  onClick={onOpenTimeline}
                  className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest2 text-amberglow transition-colors hover:text-amberglow/80"
                  data-testid="open-timeline"
                >
                  <Play size={10} /> Open Timeline
                </button>
              )}
              {isDone && !onOpenTimeline && (
                <button
                  onClick={() => document.querySelector('#output')?.scrollIntoView({ behavior: 'smooth' })}
                  className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest2 text-cyanglow transition-colors hover:text-cyanglow/80"
                >
                  <Play size={10} /> View Output
                </button>
              )}
            </div>
          </div>

          <div
            ref={feedRef}
            className="terminal-scroll h-[420px] overflow-y-auto p-5 font-mono text-[11px] leading-relaxed sm:h-[460px] sm:text-xs"
            data-lenis-prevent="true"
          >
            {lines.length === 0 && !uploadError && (
              <div className="mb-4 flex items-center gap-2 text-ash/40">
                <Cpu size={13} className="text-amberglow" />
                <span className="uppercase tracking-widest2">session boot — drop a folder or paste a prompt to begin</span>
              </div>
            )}

            {lines.map((line, i) => {
              const tone = line.tone
              const colorCls = agentColors[line.parentStage || line.agent] || 'text-bone'
              const chip = {
                error: 'border-red-400/40 bg-red-400/10 text-red-400',
                done: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-400',
                tool: 'border-cyanglow/40 bg-cyanglow/10 text-cyanglow',
                ok: 'border-emerald-400/30 bg-emerald-400/5 text-emerald-400',
              }[tone] || 'border-amberglow/30 bg-amberglow/5 text-amberglow'
              const icon = { error: '❌', done: '🎬', tool: '🔧', ok: '✅' }[tone] || '•'
              const indentCls = line.depth === 2
                ? 'ml-9 border-l border-white/10 pl-3'
                : line.depth === 1
                  ? 'ml-4 border-l border-white/10 pl-3'
                  : ''
              const connector = line.depth === 2 ? '↳↳ ' : line.depth === 1 ? '↳ ' : ''
              return (
                <div key={line.id || i} className={`group flex gap-2 py-1.5 hover:bg-white/[0.02] ${indentCls}`}>
                  <span className="shrink-0 text-ash/30">[{String(i + 1).padStart(3, '0')}]</span>
                  <span className={`shrink-0 font-bold ${colorCls} ${line.isSub ? 'opacity-80' : ''}`}>{line.agent}</span>
                  <span className={`status-chip shrink-0 border ${chip}`}>{icon} {tone.toUpperCase()}</span>
                  <span className="flex-1 text-ash/85">{connector}{line.text}</span>
                </div>
              )
            })}

            {(isLive || play) && lines.length > 0 && (
              <div className="mt-2 flex items-center gap-1 text-amberglow">
                <span className="inline-block" style={getCursorStyle()}>›</span>
                <span className="h-4 w-2 animate-blink bg-amberglow" />
              </div>
            )}

            {isDone && (
              <div className="mt-4 rounded-lg border border-emerald-400/30 bg-emerald-400/10 p-4">
                <div className="flex items-center gap-2 text-emerald-400">
                  <span className="text-lg">🎬</span>
                  <span className="font-mono text-[11px] uppercase tracking-widest2">Pipeline Complete</span>
                </div>
                <p className="mt-2 font-mono text-[11px] text-bone/80">
                  Your documentary is ready. Scroll down to view and download the final output.
                </p>
                <button
                  onClick={() => document.querySelector('#output')?.scrollIntoView({ behavior: 'smooth' })}
                  className="mt-3 flex items-center gap-2 rounded-full bg-amberglow px-5 py-2.5 font-mono text-[10px] font-bold uppercase tracking-widest2 text-void transition-colors hover:bg-amberglow/80"
                >
                  <Play size={12} /> View Final Output
                </button>
              </div>
            )}

            {isReview && (
              <div className="mt-4 rounded-lg border border-amber-400/30 bg-amber-400/10 p-4">
                <div className="flex items-center gap-2 text-amber-400">
                  <span className="text-lg">⚠️</span>
                  <span className="font-mono text-[11px] uppercase tracking-widest2">Needs Review</span>
                </div>
                <p className="mt-2 font-mono text-[11px] text-bone/80">
                  {jobStatus?.error_log?.message || 'Self-review flagged this render.'}
                </p>
              </div>
            )}

            {isFailed && (
              <div className="mt-4 rounded-lg border border-red-400/30 bg-red-400/10 p-4">
                <div className="flex items-center gap-2 text-red-400">
                  <span className="text-lg">❌</span>
                  <span className="font-mono text-[11px] uppercase tracking-widest2">Pipeline Failed</span>
                </div>
                <p className="mt-2 font-mono text-[11px] text-bone/80">
                  {jobStatus?.error_log?.message || uploadError || 'Unknown error occurred'}
                </p>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-white/10 px-5 py-3">
            {isLive ? (
              <>
                <span className="status-chip border border-cyanglow/40 bg-cyanglow/10 text-cyanglow">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyanglow" /> {jobStatus?.stage || 'processing'}
                </span>
                <span className="status-chip border border-amberglow/30 bg-amberglow/5 text-amberglow">
                  {jobStatus?.progress_percent ?? 0}%
                </span>
              </>
            ) : isDone ? (
              <>
                <span className="status-chip border border-emerald-400/40 bg-emerald-400/10 text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> complete
                </span>
                <span className="status-chip border border-amberglow/30 bg-amberglow/5 text-amberglow">100%</span>
              </>
            ) : isFailed ? (
              <span className="status-chip border border-red-400/40 bg-red-400/10 text-red-400">
                <span className="h-1.5 w-1.5 rounded-full bg-red-400" /> failed
              </span>
            ) : isReview ? (
              <span className="status-chip border border-amber-400/40 bg-amber-400/10 text-amber-400">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" /> needs review
              </span>
            ) : (
              <>
                <span className="status-chip border border-emerald-400/30 bg-emerald-400/5 text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> runtime stable
                </span>
                <span className="status-chip border border-amberglow/30 bg-amberglow/5 text-amberglow">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amberglow" /> agents active
                </span>
              </>
            )}
            <span className="ml-auto hidden font-mono text-[10px] uppercase tracking-widest2 text-ash/40 sm:block">
              {isLive ? 'live SSE pipeline · deterministic graph' : 'sandboxed · deterministic edges · state-synced'}
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}
