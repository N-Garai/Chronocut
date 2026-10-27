import { useRef, useState } from 'react'
import gsap from 'gsap'
import { UploadCloud, FileAudio, FileImage, X, Check, FolderArchive, ArrowRight, Film } from 'lucide-react'
import RevealText from './RevealText'
import Magnetic from './Magnetic'

const INGESTION_VIDEO = '/ingestion.mp4'

/**
 * DropZone — frosted-glass ingestion card with video background.
 * Drag & drop raw audio + photos.
 * Fires `onLaunch(files)` to trigger the agent pipeline demo.
 */
export default function DropZone({ onLaunch }) {
  const inputRef = useRef(null)
  const glowRef = useRef(null)
  const promptRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [files, setFiles] = useState([])
  const [prompt, setPrompt] = useState('')
  const [launching, setLaunching] = useState(false)

  const ACCEPTED = {
    audio: ['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac', 'wma', 'opus', 'aiff', 'au'],
    image: ['jpg', 'jpeg', 'png', 'webp', 'heic', 'gif', 'bmp', 'tiff', 'tif', 'svg', 'avif'],
    video: ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v', 'mpg', 'mpeg'],
  }

  const classify = (name) => {
    const ext = name.split('.').pop().toLowerCase()
    if (ACCEPTED.audio.includes(ext)) return 'audio'
    if (ACCEPTED.image.includes(ext)) return 'image'
    if (ACCEPTED.video.includes(ext)) return 'video'
    return 'other'
  }

  const addFiles = (list) => {
    const next = Array.from(list)
      .map((f) => ({
        id: `${f.name}-${f.size}-${Date.now()}`,
        name: f.name,
        size: f.size,
        type: classify(f.name),
        file: f,
      }))
      .filter((f) => f.type !== 'other')
    if (!next.length) return
    setFiles((prev) => [...prev, ...next].slice(0, 40))

    const el = glowRef.current
    gsap.fromTo(
      el,
      { opacity: 0.9, boxShadow: '0 0 60px 8px rgba(0,229,255,0.35)' },
      {
        opacity: 0,
        boxShadow: '0 0 0px 0px rgba(0,229,255,0)',
        duration: 1.4,
        ease: 'power2.out',
      }
    )
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    addFiles(e.dataTransfer.files)
  }

  const launch = () => {
    if (launching) return
    if (!files.length) return
    setLaunching(true)
    onLaunch && onLaunch({ files: files.map((f) => f.file), prompt })
  }

  const reset = () => {
    setFiles([])
    setLaunching(false)
  }

  const totalMB = (files.reduce((a, f) => a + f.size, 0) / 1048576).toFixed(1)

  return (
    <section id="ingest" className="relative overflow-hidden px-6 py-28 sm:px-10">
      {/* Video background */}
      <div className="absolute inset-0 z-0">
        <video
          className="absolute inset-0 h-full w-full object-cover"
          src={INGESTION_VIDEO}
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
        <div className="mb-12">
          <span className="font-mono text-[11px] uppercase tracking-widest3 text-cyanglow">
            [ 01 · INGESTION ]
          </span>
          <RevealText className="mt-4 font-display text-[clamp(2.5rem,7vw,5.5rem)] leading-[0.9] text-bone">
            FEED THE ORCHESTRATOR
          </RevealText>
          <RevealText
            as="p"
            className="mt-6 max-w-xl font-light leading-relaxed text-bone/90"
            stagger={0.008}
          >
            Raw interviews, field recordings, family albums, archival scans —
            ChronoCut assembles the story while you step away.
          </RevealText>
        </div>

        <div className="relative">
          <div ref={glowRef} className="pointer-events-none absolute inset-0 z-10 rounded-3xl" />

          <div
            className={`relative overflow-hidden rounded-3xl border p-2 transition-all duration-500 ${
              dragging
                ? 'border-cyanglow bg-cyanglow/10'
                : 'border-white/15 bg-white/[0.08]'
            }`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <div className="grid gap-2 md:grid-cols-[1.2fr_1fr]">
              <button
                onClick={() => inputRef.current && inputRef.current.click()}
                className={`group relative flex min-h-[360px] flex-col items-center justify-center gap-6 rounded-2xl border-2 border-dashed p-10 text-center transition-colors duration-300 ${
                  dragging
                    ? 'border-cyanglow bg-cyanglow/10'
                    : 'border-white/20 hover:border-amberglow/70'
                }`}
              >
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  accept="audio/*,image/*"
                  className="hidden"
                  onChange={(e) => {
                    addFiles(e.target.files)
                    e.target.value = ''
                  }}
                />

                <div className="relative">
                  <span className="absolute inset-0 animate-spin-slow rounded-full bg-amberglow/20 blur-2xl" />
                  <div className="relative flex h-24 w-24 items-center justify-center rounded-full border border-amberglow/40 bg-carbon/80 text-amberglow">
                    <UploadCloud size={40} className="transition-transform duration-500 group-hover:-translate-y-1" />
                  </div>
                </div>

                <div>
                  <p className="font-heading text-xl tracking-wide text-bone sm:text-2xl">
                    {dragging ? 'RELEASE TO INGEST' : 'DROP RAW FOLDER HERE'}
                  </p>
                  <p className="mt-3 font-mono text-[11px] uppercase tracking-widest2 text-bone/60">
                    .mp3 · .wav · .m4a — .jpg · .png · .heic
                  </p>
                </div>

                <span className="rounded-full border border-white/15 px-6 py-2.5 font-mono text-[11px] uppercase tracking-widest2 text-bone/80 transition-colors group-hover:border-amberglow group-hover:text-amberglow">
                  or browse files
                </span>
              </button>

              <div className="flex min-h-[360px] flex-col rounded-2xl border border-white/10 bg-carbon/90 p-6">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] uppercase tracking-widest2 text-bone/70">
                    Manifest
                  </span>
                  {files.length > 0 && (
                    <button
                      onClick={reset}
                      className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest2 text-bone/50 transition-colors hover:text-red-400"
                    >
                      <X size={12} /> clear
                    </button>
                  )}
                </div>

                <div className="mt-4 flex-1 space-y-2 overflow-y-auto pr-1" style={{ maxHeight: '240px' }}>
                  {files.length === 0 && (
                    <div className="flex h-40 flex-col items-center justify-center gap-3 text-center font-mono text-[10px] uppercase tracking-widest2 text-bone/40">
                      <FolderArchive size={28} className="text-bone/30" />
                      <span>manifest empty</span>
                      <span>awaiting raw media</span>
                    </div>
                  )}

                  {files.map((f) => (
                    <div
                      key={f.id}
                      className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.03] px-3 py-2"
                    >
                      <span
                        className={`flex h-8 w-8 items-center justify-center rounded-md ${
                          f.type === 'audio'
                            ? 'bg-cyanglow/10 text-cyanglow'
                            : f.type === 'video'
                              ? 'bg-violet-500/10 text-violet-400'
                              : 'bg-amberglow/10 text-amberglow'
                        }`}
                      >
                        {f.type === 'audio' ? <FileAudio size={16} /> : f.type === 'video' ? <Film size={16} /> : <FileImage size={16} />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-mono text-[11px] text-bone">{f.name}</p>
                        <p className="font-mono text-[9px] uppercase tracking-widest text-bone/40">
                          {f.type === 'audio' ? 'audio track' : f.type === 'video' ? 'video clip' : 'still frame'}
                        </p>
                      </div>
                      <Check size={14} className="shrink-0 text-emerald-400" />
                    </div>
                  ))}
                </div>

                <div className="mt-4 border-t border-white/10 pt-4">
                  <label className="block font-mono text-[10px] uppercase tracking-widest2 text-bone/60">
                    Director Prompt
                  </label>
                  <textarea
                    ref={promptRef}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Describe your documentary vision... (e.g., 'Focus on the emotional journey, emphasize family bonds, include archival B-roll from the 1970s')"
                    className="mt-2 h-24 w-full rounded-lg border border-white/10 bg-white/[0.04] p-3 font-mono text-[11px] leading-relaxed text-bone placeholder-bone/30 outline-none transition-colors focus:border-cyanglow/60"
                  />
                </div>

                <div className="mt-4 border-t border-white/10 pt-4">
                  <div className="flex items-center justify-between font-mono text-[11px] text-bone/60">
                    <span>{files.length} assets</span>
                    <span>{totalMB} MB</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex flex-col items-center gap-3 p-6 sm:flex-row sm:justify-between">
              <p className="font-mono text-[10px] uppercase tracking-widest2 text-bone/40">
                 zero cost · background processing
              </p>
              <Magnetic strength={0.3}>
                <button
                  onClick={launch}
                  disabled={launching || files.length === 0}
                  data-cursor="play"
                  className={`group flex items-center gap-3 rounded-full px-8 py-4 font-mono text-[11px] font-bold uppercase tracking-widest2 transition-all duration-300 ${
                    launching
                      ? 'cursor-not-allowed bg-white/10 text-bone/50'
                      : 'bg-cyanglow text-void hover:shadow-[0_0_40px_rgba(0,229,255,0.4)]'
                  }`}
                >
                  {launching ? (
                    <>
                      <span className="h-2 w-2 animate-ping rounded-full bg-cyanglow" />
                      SWARM LAUNCHED
                    </>
                  ) : (
                    <>
                      <ArrowRight size={15} className="transition-transform duration-300 group-hover:translate-x-1" />
                      {files.length ? 'LAUNCH AGENT SWARM' : 'ADD MEDIA FIRST'}
                    </>
                  )}
                </button>
              </Magnetic>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
