const RIBBON = 'AUTONOMOUS DOCUMENTARY ORCHESTRATION — MULTI-AGENT SWARM — CLOUD-NATIVE PIPELINE'

/**
 * Marquee — infinite cinematic ribbon. Duplicated track for seamless loop.
 */
export default function Marquee({ reverse = false }) {
  const items = Array.from({ length: 8 }, (_, i) => `${RIBBON} —`).join(' ')
  const repeat = 2

  return (
    <div className="relative overflow-hidden border-y border-white/10 bg-coal py-5">
      <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-24 bg-gradient-to-r from-coal to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-24 bg-gradient-to-l from-coal to-transparent" />

      <div
        className={`flex w-max whitespace-nowrap ${
          reverse ? 'animate-marquee-reverse' : 'animate-marquee'
        }`}
      >
        {Array.from({ length: repeat }).map((_, i) => (
          <span
            key={i}
            className="flex items-center gap-6 pr-6 font-display text-[clamp(1.6rem,4vw,3rem)] uppercase text-bone"
          >
            {items.split('—').filter(Boolean).map((seg, j) => (
              <span key={j} className="flex items-center gap-6">
                <span className="text-bone/90">{seg.trim()}</span>
                <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-amberglow" fill="currentColor">
                  <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
                  <circle cx="12" cy="12" r="3" fill="currentColor" />
                </svg>
              </span>
            ))}
          </span>
        ))}
      </div>
    </div>
  )
}
