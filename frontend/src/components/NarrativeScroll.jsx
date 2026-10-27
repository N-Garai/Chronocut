import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import RevealText from './RevealText'

gsap.registerPlugin(ScrollTrigger)

const narrativeSteps = [
  {
    id: '01',
    label: 'ORCHESTRATOR',
    title: 'Routes the workflow',
    body: 'The Lead Orchestrator receives the ZIP upload, creates a job record, and routes the workflow through the agent graph. It monitors every agent and updates progress in real time.',
    subAgents: [
      { name: 'Job Manager' },
      { name: 'Pipeline Router' },
      { name: 'State Watcher' },
      { name: 'Capability Discovery' },
      { name: 'Budget Governor' },
    ],
  },
  {
    id: '02',
    label: 'ARCHIVIST',
    title: 'Agents read the material',
    body: 'The Archivist swarm fans out — audio is transcribed with millisecond timestamps and every photo is tagged with semantic metadata: era, objects, mood, color.',
    subAgents: [
      { name: 'Audio Transcriber' },
      { name: 'Image Tagger' },
      { name: 'Filler Analyzer' },
    ],
  },
  {
    id: '03',
    label: 'SCREENWRITER',
    title: 'Narrative arc is built',
    body: 'Filler words are surgically removed. A 3-act structure is detected — hook, setup, payoff. The script maps every line back to the original speaker cadence.',
    subAgents: [
      { name: 'Filler Remover' },
      { name: 'Narrative Arc' },
      { name: 'Script Builder' },
      { name: 'Narrative Arc Specialist' },
    ],
  },
  {
    id: '04',
    label: 'DIRECTOR',
    title: 'Visuals are slotted',
    body: 'User photos are matched to script beats. Gaps are filled with B-roll from Pexels and Wikimedia. The Director locks a shot list with transitions and motion directives.',
    subAgents: [
      { name: 'Visual Matcher' },
      { name: 'B-Roll Sourcing' },
      { name: 'Storyboard Assembler' },
      { name: 'Visual Matcher Specialist' },
      { name: 'B-Roll Sourcing Specialist' },
      { name: 'Storyboard Composer' },
    ],
  },
  {
    id: '05',
    label: 'EDITOR',
    title: 'Rendered, no hand-holding',
    body: 'Ken Burns pans, crossfades, audio sync — all applied by the deterministic Editor node. Final MP4 delivered in minutes. Zero human intervention.',
    subAgents: [
      { name: 'Ken Burns FX' },
      { name: 'Audio Sync' },
      { name: 'Render Pipeline' },
      { name: 'Self-Review' },
    ],
  },
]

/**
 * NarrativeScroll — pinned left-column typography + right-column image stack.
 * Text lines reveal with staggered SplitType animation as user scrolls.
 */
export default function NarrativeScroll() {
  const sectionRef = useRef(null)
  const leftRef = useRef(null)

  useLayoutEffect(() => {
    try {
      const ctx = gsap.context(() => {
        const section = sectionRef.current
        if (!section) return

        const lines = leftRef.current?.querySelectorAll('.narrative-line')
        if (!lines?.length) return

        gsap.fromTo(
          lines,
          { yPercent: 120, opacity: 0 },
          {
            yPercent: 0,
            opacity: 1,
            stagger: 0.12,
            ease: 'power3.out',
            scrollTrigger: {
              trigger: section,
              start: 'top 60%',
              end: 'bottom 40%',
              scrub: 1,
            },
          }
        )

        ScrollTrigger.refresh()
      }, sectionRef)

      return () => ctx.revert()
    } catch (err) {
      // Fail-safe: if the scroll animation errors, make the text visible.
      console.error('NarrativeScroll animation failed; showing static text', err)
      const lines = leftRef.current?.querySelectorAll('.narrative-line')
      lines?.forEach((l) => {
        l.style.opacity = '1'
        l.style.transform = 'none'
      })
    }
  }, [])

  return (
    <section
      ref={sectionRef}
      id="narrative"
      className="relative overflow-hidden py-28 sm:py-36"
    >
      <div className="absolute inset-0 z-0">
        <video
          className="absolute inset-0 h-full w-full object-cover"
          src="/pipeline.mp4"
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

      <div className="relative z-10 mx-auto max-w-7xl px-6 sm:px-10">
        <div className="mb-16">
          <span className="font-mono text-[11px] uppercase tracking-widest3 text-cyanglow">
            [ 04 · THE PIPELINE ]
          </span>
          <RevealText className="mt-4 font-display text-[clamp(2.5rem,7vw,5.5rem)] leading-[0.9] text-bone">
            HOW THE SWARM WORKS
          </RevealText>
        </div>

        <div className="grid grid-cols-1 gap-12 lg:grid-cols-12">
          {/* Left: sticky narrative text */}
          <div className="lg:col-span-5">
            <div
              ref={leftRef}
              className="lg:sticky lg:top-32 flex flex-col gap-10"
            >
              {narrativeSteps.map((step) => (
                <div key={step.id} className="narrative-line">
                  <span className="font-mono text-[10px] uppercase tracking-widest3 text-amberglow">
                    {step.label}
                  </span>
                  <h3 className="mt-2 font-display text-[clamp(1.6rem,3.5vw,2.8rem)] leading-[0.95] text-bone">
                    {step.title}
                  </h3>
                  <p className="mt-3 font-light leading-relaxed text-ash/70">
                    {step.body}
                  </p>

                  {step.subAgents.length > 0 && (
                    <div className="mt-4 ml-4 flex flex-col gap-3 border-l border-white/10 pl-4">
                      {step.subAgents.map((sub) => (
                        <div key={sub.name} className="sub-agent-block">
                          <span className="font-mono text-[9px] uppercase tracking-widest3 text-cyanglow/80">
                            {sub.name}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Right: visual stack */}
          <div className="lg:col-span-7">
            <div className="flex flex-col gap-6">
              {narrativeSteps.map((step, i) => (
                <div
                  key={step.id}
                  className="narrative-card overflow-hidden rounded-sm border border-white/10 bg-carbon"
                >
                  <div className="relative aspect-video overflow-hidden bg-[#0a0a0a]">
                    <img
                      src={`https://picsum.photos/seed/chronocut${step.id}/1280/720`}
                      alt={step.title}
                      className="h-full w-full object-cover transition-transform duration-[2000ms] ease-out hover:scale-105"
                      loading="lazy"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-carbon/80 via-transparent to-transparent" />
                    <div className="absolute bottom-4 left-4 flex items-center gap-3">
                      <span className="font-mono text-[10px] uppercase tracking-widest3 text-amberglow">
                        SEQ.{step.id}
                      </span>
                      <span className="h-px w-6 bg-amberglow/60" />
                      <span className="font-mono text-[10px] uppercase tracking-widest2 text-ash/60">
                        {step.label}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
