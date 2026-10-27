import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { Play, Pause, Download, FileText, Film, Volume2, Check, MonitorPlay } from 'lucide-react'
import RevealText from './RevealText'
import Magnetic from './Magnetic'
import { videoUrl } from '../lib/api'
import { polaroidSVG } from '../lib/polaroids'
import JSZip from 'jszip'

const DURATION = 227

function MockVideo({ playing, progress, onToggle, onProgress }) {
  const canvasRef = useRef(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const img = new Image()
    img.src = polaroidSVG({ mode: 'cut', seed: 12, hue: 10 })
    let raf
    let start = performance.now()
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
    const resize = () => {
      const rect = canvas.parentElement.getBoundingClientRect()
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
    }
    resize()
    window.addEventListener('resize', resize)
    const draw = (t) => {
      const elapsed = (t - start) / 1000
      const scale = 1.15 + Math.sin(elapsed * 0.12) * 0.06
      const ox = Math.sin(elapsed * 0.07) * 40
      const oy = Math.cos(elapsed * 0.09) * 30
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.fillStyle = '#000'
      ctx.fillRect(0, 0, canvas.width / dpr, canvas.height / dpr)
      const w = canvas.width / dpr
      const h = canvas.height / dpr
      const iw = w * scale
      const ih = (w * scale * 3) / 4
      ctx.drawImage(img, (w - iw) / 2 + ox, (h - ih) / 2 + oy, iw, ih)
      ctx.fillStyle = 'rgba(0,0,0,0.55)'
      ctx.fillRect(0, 0, w, h)
      ctx.globalCompositeOperation = 'overlay'
      const grad = ctx.createLinearGradient(0, 0, w, h)
      grad.addColorStop(0, 'rgba(255,195,0,0.25)')
      grad.addColorStop(0.5, 'rgba(0,0,0,0)')
      grad.addColorStop(1, 'rgba(0,229,255,0.18)')
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, w, h)
      ctx.globalCompositeOperation = 'source-over'
      if (playing) raf = requestAnimationFrame(draw)
    }
    if (playing) raf = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [playing])
  return (
    <div className="relative aspect-video w-full overflow-hidden bg-black">
      <canvas ref={canvasRef} className="h-full w-full" />
      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/40" />
      <div className="absolute left-5 top-4 flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest2 text-white/80">
        <Film size={13} className="text-amberglow" /> CHRONOCUT_0001.mp4 — 03:47
      </div>
      <div className="absolute right-5 top-4 flex items-center gap-3">
        <span className="status-chip border border-emerald-400/40 bg-black/40 text-emerald-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> 1080p
        </span>
        <Volume2 size={14} className="text-white/70" />
      </div>
      <button data-cursor="play" onClick={onToggle} className="group absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" aria-label={playing ? 'Pause' : 'Play'}>
        <span className="absolute inset-0 animate-ping rounded-full bg-amberglow/30" style={{ animationIterationCount: playing ? 0 : 'infinite' }} />
        <span className="relative flex h-24 w-24 items-center justify-center rounded-full border border-white/30 bg-black/50 backdrop-blur-md transition-all duration-300 group-hover:scale-110 group-hover:border-amberglow group-hover:bg-amberglow group-hover:text-void">
          {playing ? <Pause size={30} /> : <Play size={30} className="ml-1" />}
        </span>
      </button>
      <div className="absolute inset-x-0 bottom-0 px-5 pb-4">
        <div className="mb-2 flex items-center justify-between font-mono text-[10px] uppercase tracking-widest2 text-white/70">
          <span>{Math.floor(progress)}:{String(Math.floor((progress % 1) * 60)).padStart(2, '0')}</span>
          <span>03:47</span>
        </div>
        <div className="group relative h-1 w-full cursor-pointer bg-white/20" onClick={onProgress}>
          <div className="absolute inset-y-0 left-0 bg-amberglow" style={{ width: `${(progress / DURATION) * 100}%` }} />
        </div>
      </div>
    </div>
  )
}

export default function OutputPlayer({ jobOutput }) {
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [downloaded, setDownloaded] = useState(false)
  const [profile, setProfile] = useState(null)
  const visualizerRef = useRef(null)
  const [playingReal, setPlayingReal] = useState(false)
  const videoRef = useRef(null)

  const isReal = !!jobOutput && (jobOutput.status === 'COMPLETE' || jobOutput.status === 'NEEDS_REVIEW')
  const paths = jobOutput?.editor_output?.video_paths || {}
  const profileKeys = Object.keys(paths)
  const activeProfile = profile || jobOutput?.editor_output?.primary_profile || profileKeys[0] || null
  const videoSrc = isReal && jobOutput?.job_id ? videoUrl(jobOutput.job_id, activeProfile) : null

  useEffect(() => {
    if (!playing) return
    const iv = setInterval(() => {
      setProgress((p) => {
        const next = p + 0.35
        if (next >= DURATION) { setPlaying(false); return DURATION }
        return next
      })
    }, 100)
    return () => clearInterval(iv)
  }, [playing])

  const buildReportContent = () => {
    const userPrompt = jobOutput?.input_files?.user_prompt || ''
    return isReal
      ? [
          'CHRONOCUT — PIPELINE REPORT',
          `JOB: ${jobOutput.job_id}`,
          `STATUS: ${jobOutput.status}`,
          userPrompt ? `USER PROMPT: ${userPrompt}` : '',
          '',
          'PROFILES RENDERED',
          '---',
          ...profileKeys.map((k) => `${k}: ${paths[k]}`),
          '',
          'CHANGELOG',
          '---',
          JSON.stringify(jobOutput.editor_output?.changelog || {}, null, 2),
        ].join('\n')
      : 'CHRONOCUT — WHITE-BOX RESEARCH REPORT\nA complete autonomous documentary, rendered with zero human intervention.'
  }

  const downloadAll = async () => {
    try {
      const zip = new JSZip()
      const add = (name, data) =>
        zip.file(name, typeof data === 'string' ? data : JSON.stringify(data, null, 2))
      add('CHRONOCUT_REPORT.txt', buildReportContent())
      add('script.json', jobOutput?.screenwriter_output || {})
      add('storyboard.json', jobOutput?.director_output?.storyboard || [])
      add('changelog.json', jobOutput?.editor_output?.changelog || {})
      add('review.json', jobOutput?.review_report || {})
      add('input_files.json', jobOutput?.input_files || {})
      if (videoSrc) {
        try {
          const res = await fetch(videoSrc)
          if (res.ok) {
            const buf = await res.arrayBuffer()
            zip.file(`video_${activeProfile || 'main'}.mp4`, buf)
          }
        } catch (e) {
          console.warn('artifact zip: video fetch failed', e)
        }
      }
      const blob = await zip.generateAsync({ type: 'blob' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = isReal
        ? `chronocut_artifacts_${jobOutput.job_id?.slice(0, 8) || '0001'}.zip`
        : 'chronocut_research_artifacts.zip'
      a.click()
      URL.revokeObjectURL(url)
      setDownloaded(true)
      setTimeout(() => setDownloaded(false), 2500)
    } catch (e) {
      console.warn('artifact zip failed, falling back to text report', e)
      const blob = new Blob([buildReportContent()], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'chronocut_report.txt'
      a.click()
      URL.revokeObjectURL(url)
    }
  }

  return (
    <section id="output" className="relative overflow-hidden px-6 py-28 sm:px-10">
      <div className="absolute inset-0 z-0">
        <video className="absolute inset-0 h-full w-full object-cover" src="/output.mp4" autoPlay loop muted playsInline preload="auto" />
        <div className="absolute inset-0 bg-void/65" />
        <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-void to-transparent" />
        <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-void to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-t from-void/30 via-transparent to-void/30" />
      </div>

      <div className="relative z-10 mx-auto max-w-6xl">
        <div className="mb-12">
          <span className="font-mono text-[11px] uppercase tracking-widest3 text-cyanglow">[ 03 · FINAL OUTPUT ]</span>
          <RevealText className="mt-4 font-display text-[clamp(2.5rem,7vw,5.5rem)] leading-[0.9] text-bone">
            {isReal ? 'RENDER COMPLETE' : 'THE CUT IS READY'}
          </RevealText>
          <RevealText as="p" className="mt-6 max-w-xl font-light leading-relaxed text-ash/70" stagger={0.008}>
            {isReal
              ? 'Your documentary is ready. Switch format profiles and download the artifacts below.'
              : 'A complete documentary, rendered with zero human intervention. Press play — or take the artifacts.'}
          </RevealText>
          {isReal && jobOutput?.input_files?.user_prompt && (
            <div className="mt-4 rounded-lg border border-cyanglow/20 bg-cyanglow/5 p-4">
              <span className="font-mono text-[10px] uppercase tracking-widest2 text-cyanglow">Director Prompt</span>
              <p className="mt-1 font-mono text-[11px] text-bone/80">{jobOutput.input_files.user_prompt}</p>
            </div>
          )}
        </div>

        <div className="overflow-hidden rounded-2xl border border-white/10 bg-carbon shadow-[0_40px_120px_-30px_rgba(0,0,0,0.9)]">
          {videoSrc ? (
            <div className="relative aspect-video w-full bg-black">
              <video
                key={videoSrc}
                ref={videoRef}
                className="h-full w-full"
                src={videoSrc}
                controls
                preload="metadata"
                onPlay={() => setPlayingReal(true)}
                onPause={() => setPlayingReal(false)}
                onEnded={() => setPlayingReal(false)}
              />
              {!playingReal && (
                <button
                  data-cursor="play"
                  onClick={() => videoRef.current && videoRef.current.play()}
                  className="group absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
                  aria-label="Play"
                >
                  <span className="absolute inset-0 animate-ping rounded-full bg-amberglow/30" />
                  <span className="relative flex h-24 w-24 items-center justify-center rounded-full border border-white/30 bg-black/50 backdrop-blur-md transition-all duration-300 group-hover:scale-110 group-hover:border-amberglow group-hover:bg-amberglow group-hover:text-void">
                    <Play size={30} className="ml-1" />
                  </span>
                </button>
              )}
            </div>
          ) : (
            <MockVideo
              playing={playing}
              progress={progress}
              onToggle={() => setPlaying((p) => !p)}
              onProgress={(e) => {
                const rect = e.currentTarget.getBoundingClientRect()
                const ratio = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1)
                setProgress(ratio * DURATION)
              }}
            />
          )}

          <div className="flex flex-col gap-5 p-6 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-4">
              <div ref={visualizerRef} className="flex h-8 items-end gap-1" aria-hidden="true">
                {Array.from({ length: 24 }).map((_, i) => (
                  <span key={i} className="w-1 origin-bottom rounded-sm bg-amberglow" style={{ height: `${20 + ((i * 37) % 80)}%`, transform: 'scaleY(0.15)' }} />
                ))}
              </div>
              <div>
                <p className="font-mono text-[11px] uppercase tracking-widest2 text-bone">
                  {videoSrc ? `now playing · ${activeProfile}` : (playing ? 'now rendering acoustics' : 'documentary · 03:47')}
                </p>
                <p className="font-mono text-[9px] uppercase tracking-widest text-ash/40">voiceover · b-roll · archival grade</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {profileKeys.length > 1 && (
                <div className="flex flex-wrap items-center gap-2">
                  {profileKeys.map((k) => (
                    <button
                      key={k}
                      onClick={() => setProfile(k)}
                      className={`rounded-full border px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest2 transition-colors ${
                        k === activeProfile ? 'border-amberglow bg-amberglow/10 text-amberglow' : 'border-white/15 text-bone/70 hover:border-white/40'
                      }`}
                    >
                      <MonitorPlay size={11} className="mr-1 inline" /> {k}
                    </button>
                  ))}
                </div>
              )}
              <Magnetic strength={0.3}>
                <button onClick={downloadAll} data-cursor="view" className="group flex items-center gap-2 rounded-full border border-white/15 px-6 py-3.5 font-mono text-[11px] uppercase tracking-widest2 text-bone transition-colors hover:border-white/40">
                  <FileText size={15} className="text-cyanglow" /> Download Artifacts
                </button>
              </Magnetic>
              {videoSrc && (
                <Magnetic strength={0.35}>
                  <a
                    href={videoSrc}
                    download
                    data-cursor="play"
                    className={`group flex items-center gap-3 rounded-full px-7 py-3.5 font-mono text-[11px] font-bold uppercase tracking-widest2 transition-all duration-300 ${
                      downloaded ? 'bg-emerald-400 text-void' : 'bg-amberglow text-void hover:shadow-[0_0_40px_rgba(255,195,0,0.4)]'
                    }`}
                  >
                    <Download size={15} /> Download MP4
                  </a>
                </Magnetic>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
