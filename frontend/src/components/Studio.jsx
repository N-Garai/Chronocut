import { useEffect, useRef, useState, useCallback } from 'react'
import { Cpu, UploadCloud, Link2, PenLine, ArrowRight, Check, Loader2, Coins, ShieldCheck, AlertTriangle } from 'lucide-react'
import RevealText from './RevealText'
import Magnetic from './Magnetic'
import { createJob, getLedger, getReview } from '../lib/api'

const PROFILES = [
  ['youtube_landscape', 'YouTube 16:9'],
  ['youtube_portrait', 'YouTube 9:16'],
  ['instagram_portrait', 'Reels 9:16'],
  ['instagram_square', 'IG Square 1:1'],
  ['twitter_landscape', 'X 16:9'],
  ['square_1080', 'Square 1080'],
]

export default function Studio({ activeJob, jobStatus, caps, createJob, uploading, uploadError }) {
  const [mode, setMode] = useState('from_media')
  const [files, setFiles] = useState([])
  const [prompt, setPrompt] = useState('')
  const [referenceUrl, setReferenceUrl] = useState('')
  const [tone, setTone] = useState('')
  const [lengthSeconds, setLengthSeconds] = useState(180)
  const [targetAudience, setTargetAudience] = useState('')
  const [profiles, setProfiles] = useState(['youtube_landscape'])
  const [localErr, setLocalErr] = useState(null)
  const [ledger, setLedger] = useState(null)
  const [review, setReview] = useState(null)
  const fileRef = useRef(null)

  const envelope = caps?.support_envelope || {}
  const providers = caps?.provider_menu || []

  useEffect(() => {
    if (!activeJob) return
    let alive = true
    getLedger(activeJob).then((d) => alive && setLedger(d)).catch(() => {})
    getReview(activeJob).then((d) => alive && setReview(d)).catch(() => {})
    return () => { alive = false }
  }, [activeJob])

  const toggleProfile = (p) =>
    setProfiles((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]))

  const onPickFiles = (list) => setFiles(Array.from(list))

  const launch = useCallback(async () => {
    setLocalErr(null)
    try {
      let payload = {
        mode,
        prompt: prompt.trim() || undefined,
        outputProfiles: profiles.join(','),
        tone: tone.trim() || undefined,
        lengthSeconds: Number(lengthSeconds) || undefined,
        targetAudience: targetAudience.trim() || undefined,
      }
      if (mode === 'from_media') {
        if (!files.length) throw new Error('Add at least one media file')
        const { default: JSZip } = await import('jszip')
        const zip = new JSZip()
        const folder = zip.folder('media')
        for (const f of files) folder.file(f.name, f)
        payload.file = await zip.generateAsync({ type: 'blob' })
      } else if (mode === 'from_reference') {
        if (!referenceUrl.trim()) throw new Error('Paste a reference video URL')
        payload.referenceUrl = referenceUrl.trim()
      } else if (mode === 'from_prompt') {
        if (!prompt.trim()) throw new Error('Write a director prompt')
      }
      await createJob(payload)
    } catch (e) {
      setLocalErr(e.message)
    }
  }, [mode, files, prompt, referenceUrl, tone, lengthSeconds, targetAudience, profiles, createJob])

  const status = jobStatus?.status
  const progress = jobStatus?.progress_percent ?? 0

  return (
    <section id="studio" className="relative overflow-hidden px-6 py-28 sm:px-10">
      {/* Video background (ingestion) */}
      <div className="absolute inset-0 z-0">
        <video
          className="absolute inset-0 h-full w-full object-cover"
          src="/ingestion.mp4"
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-void/80 via-void/70 to-void/80" />
        <div className="absolute inset-0 bg-cyan/10" />
      </div>

      <div className="relative z-10 mx-auto max-w-6xl">
        <div className="mb-10">
          <span className="font-mono text-[11px] uppercase tracking-widest3 text-amberglow">[ 01 · INGESTION ]</span>
          <RevealText className="mt-4 font-display text-[clamp(2.2rem,6vw,4.5rem)] leading-[0.95] text-bone">
            CHOOSE YOUR SOURCE
          </RevealText>
          <RevealText as="p" className="mt-5 max-w-2xl font-light leading-relaxed text-ash/70" stagger={0.008}>
            Three orchestration modes, one deterministic pipeline. Drop media, paste a reference film, or describe the story from scratch.
          </RevealText>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          {/* Left: mode + form */}
          <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-6 sm:p-8">
            <div className="grid grid-cols-3 gap-2 rounded-2xl border border-white/10 bg-carbon/60 p-1.5">
              {[
                ['from_media', 'Media', UploadCloud],
                ['from_reference', 'Reference', Link2],
                ['from_prompt', 'Prompt', PenLine],
              ].map(([m, label, Icon]) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`flex flex-col items-center gap-1 rounded-xl px-2 py-3 font-mono text-[10px] uppercase tracking-widest2 transition-colors ${
                    mode === m ? 'bg-amberglow/15 text-amberglow' : 'text-bone/55 hover:text-bone'
                  }`}
                >
                  <Icon size={18} />
                  {label}
                </button>
              ))}
            </div>

            <div className="mt-6 space-y-4">
              {mode === 'from_media' && (
                <>
                  <input
                    ref={fileRef}
                    type="file"
                    multiple
                    accept="audio/*,image/*,video/*"
                    className="hidden"
                    onChange={(e) => onPickFiles(e.target.files)}
                  />
                  <button
                    onClick={() => fileRef.current?.click()}
                    className="flex w-full flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-white/15 p-8 text-center transition-colors hover:border-cyanglow/70"
                  >
                    <UploadCloud size={30} className="text-cyanglow" />
                    <span className="font-mono text-[11px] uppercase tracking-widest2 text-bone/70">
                      {files.length ? `${files.length} file(s) selected` : 'select audio, photos, video'}
                    </span>
                  </button>
                </>
              )}

              {mode === 'from_reference' && (
                <div>
                  <label className="font-mono text-[10px] uppercase tracking-widest2 text-bone/60">Reference Video URL (YouTube / archive / direct)</label>
                  <input
                    value={referenceUrl}
                    onChange={(e) => setReferenceUrl(e.target.value)}
                    placeholder="https://www.youtube.com/watch?v=..."
                    className="mt-2 w-full rounded-lg border border-white/10 bg-white/[0.04] p-3 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60"
                  />
                </div>
              )}

              <div>
                <label className="font-mono text-[10px] uppercase tracking-widest2 text-bone/60">
                  {mode === 'from_prompt' ? 'Director Prompt *' : 'Director Prompt (optional)'}
                </label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="e.g. A 3-minute documentary about my grandmother's migration story, warm tone, archival 1970s feel."
                  className="mt-2 h-28 w-full rounded-lg border border-white/10 bg-white/[0.04] p-3 font-mono text-[11px] leading-relaxed text-bone placeholder-bone/30 outline-none focus:border-cyanglow/60"
                />
              </div>

              {mode === 'from_prompt' && (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="font-mono text-[10px] uppercase tracking-widest2 text-bone/60">Tone</label>
                    <input value={tone} onChange={(e) => setTone(e.target.value)} placeholder="poetic" className="mt-2 w-full rounded-lg border border-white/10 bg-white/[0.04] p-2.5 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60" />
                  </div>
                  <div>
                    <label className="font-mono text-[10px] uppercase tracking-widest2 text-bone/60">Length (sec)</label>
                    <input type="number" value={lengthSeconds} onChange={(e) => setLengthSeconds(e.target.value)} className="mt-2 w-full rounded-lg border border-white/10 bg-white/[0.04] p-2.5 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60" />
                  </div>
                  <div className="col-span-2">
                    <label className="font-mono text-[10px] uppercase tracking-widest2 text-bone/60">Target Audience</label>
                    <input value={targetAudience} onChange={(e) => setTargetAudience(e.target.value)} placeholder="general public" className="mt-2 w-full rounded-lg border border-white/10 bg-white/[0.04] p-2.5 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60" />
                  </div>
                </div>
              )}

              <div>
                <label className="font-mono text-[10px] uppercase tracking-widest2 text-bone/60">Output Profiles (M8)</label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {PROFILES.map(([k, label]) => (
                    <button
                      key={k}
                      onClick={() => toggleProfile(k)}
                      className={`rounded-full border px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest2 transition-colors ${
                        profiles.includes(k) ? 'border-amberglow bg-amberglow/10 text-amberglow' : 'border-white/15 text-bone/60 hover:border-white/40'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {(localErr || uploadError) && (
                <p className="rounded-lg border border-red-400/30 bg-red-400/10 p-3 font-mono text-[11px] text-red-400">
                  {localErr || uploadError}
                </p>
              )}

              <Magnetic strength={0.3}>
                <button
                  onClick={launch}
                  disabled={uploading}
                  data-cursor="play"
                  className={`flex w-full items-center justify-center gap-3 rounded-full px-8 py-4 font-mono text-[11px] font-bold uppercase tracking-widest2 transition-all duration-300 ${
                    uploading ? 'cursor-not-allowed bg-white/10 text-bone/50' : 'bg-amberglow text-void hover:shadow-[0_0_40px_rgba(255,195,0,0.4)]'
                  }`}
                >
                  {uploading ? (
                    <>
                      <Loader2 size={15} className="animate-spin" /> Orchestrating...
                    </>
                  ) : (
                    <>
                      <ArrowRight size={15} /> Launch Pipeline
                    </>
                  )}
                </button>
              </Magnetic>
            </div>
          </div>

          {/* Right: capabilities + live status */}
          <div className="space-y-6">
            <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-6">
              <div className="flex items-center gap-2">
                <Cpu size={16} className="text-cyanglow" />
                <span className="font-mono text-[10px] uppercase tracking-widest2 text-bone/70">Capabilities (M2)</span>
              </div>
              {Object.keys(envelope).length === 0 ? (
                <p className="mt-3 font-mono text-[10px] uppercase tracking-widest2 text-bone/40">loading...</p>
              ) : (
                <ul className="mt-3 space-y-1.5">
                  {Object.entries(envelope).map(([k, v]) => (
                    <li key={k} className="flex items-center justify-between font-mono text-[10px]">
                      <span className="text-bone/70">{k}</span>
                      <span className={v ? 'text-emerald-400' : 'text-ash/40'}>{v ? '✓ on' : '— off'}</span>
                    </li>
                  ))}
                </ul>
              )}
              {providers.length > 0 && (
                <div className="mt-4 border-t border-white/10 pt-3">
                  <p className="font-mono text-[10px] uppercase tracking-widest2 text-bone/50">Provider menu</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {providers.map((p) => (
                      <span key={p.provider} className="rounded-full border border-white/10 px-2.5 py-1 font-mono text-[9px] uppercase tracking-widest text-bone/60">{p.provider}{p.model ? ` · ${p.model}` : ''}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {activeJob && (
              <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-6">
                <span className="font-mono text-[10px] uppercase tracking-widest2 text-bone/70">Live Job</span>
                <p className="mt-2 font-mono text-[11px] text-cyanglow">#{activeJob.slice(0, 8)}</p>
                <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                  <div className="h-full bg-amberglow transition-all duration-500" style={{ width: `${status === 'COMPLETE' ? 100 : status === 'FAILED' ? 100 : progress}%` }} />
                </div>
                <p className="mt-2 font-mono text-[10px] uppercase tracking-widest2 text-bone/60">
                  {status || 'queued'} · {progress}%
                </p>

                {ledger && (
                  <div className="mt-4 flex items-center gap-2 rounded-lg border border-white/10 bg-carbon/60 p-3">
                    <Coins size={14} className="text-amberglow" />
                    <span className="font-mono text-[10px] uppercase tracking-widest2 text-bone/70">
                      Cost: ${((ledger.total_cost_cents || 0) / 100).toFixed(4)} · {ledger.calls?.length || 0} calls
                    </span>
                  </div>
                )}

                {review && review.status && (
                  <div className={`mt-3 flex items-center gap-2 rounded-lg border p-3 ${
                    review.status === 'PASS' ? 'border-emerald-400/30 bg-emerald-400/10' : review.status === 'FAIL' ? 'border-red-400/30 bg-red-400/10' : 'border-amber-400/30 bg-amber-400/10'
                  }`}>
                    {review.status === 'PASS' ? <ShieldCheck size={14} className="text-emerald-400" /> : review.status === 'FAIL' ? <AlertTriangle size={14} className="text-red-400" /> : <AlertTriangle size={14} className="text-amber-400" />}
                    <span className="font-mono text-[10px] uppercase tracking-widest2 text-bone/80">Self-review: {review.status}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
