import { ArrowUp, SquareTerminal } from 'lucide-react'
import Magnetic from './Magnetic'

export default function Footer() {
  const scrollTop = () => {
    const lenis = window.__lenis
    if (lenis) lenis.scrollTo(0, { duration: 1.6 })
    else window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <footer className="relative border-t border-white/10 bg-coal">
      <div className="mx-auto flex max-w-6xl flex-col gap-10 px-6 py-16 sm:px-10">
        <div className="flex flex-col items-start justify-between gap-8 sm:flex-row sm:items-end">
          <div>
            <p className="font-display text-[clamp(3rem,9vw,7rem)] leading-none text-bone">
              CHRONO
              <span className="text-outline-amber">CUT</span>
            </p>
            <p className="mt-4 max-w-sm font-light text-sm leading-relaxed text-ash/60">
              An autonomous documentary & oral history orchestrator. Drop the
              mess, keep the story.
            </p>
          </div>

          <div className="flex flex-col items-start gap-4 sm:items-end">
            <Magnetic strength={0.3}>
              <button
                onClick={scrollTop}
                data-cursor="view"
                className="flex items-center gap-2 rounded-full border border-white/15 px-6 py-3 font-mono text-[11px] uppercase tracking-widest2 text-bone transition-colors hover:border-amberglow hover:text-amberglow"
              >
                <ArrowUp size={14} /> Back to top
              </button>
            </Magnetic>
          </div>
        </div>

        <div className="flex flex-col gap-3 border-t border-white/10 pt-6 font-mono text-[10px] uppercase tracking-widest2 text-ash/40 sm:flex-row sm:items-center sm:justify-between">
          <span>© 2026 ChronoCut — Autonomous Documentary Orchestrator</span>
          <span className="flex items-center gap-2">
            <SquareTerminal size={12} className="text-amberglow" />
            Multi-Agent Pipeline · Cloud-Native · Deterministic Rendering
          </span>
        </div>
      </div>
    </footer>
  )
}
