import { useLayoutEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import RevealText from './RevealText'

gsap.registerPlugin(ScrollTrigger)

const isMobile = () =>
  typeof window !== 'undefined' && window.innerWidth < 768

const storyboardSteps = [
  {
    id: '01',
    tag: 'ARCHIVIST',
    title: 'FRAME EXTRACTION',
    desc: '47 messy stills de-warped, denoised and re-timed into a usable timeline.',
    before: 'https://images.unsplash.com/photo-1485846234645-a62644f84728?w=600&h=450&fit=crop',
    after: 'https://images.unsplash.com/photo-1492691527719-9d1e07e534b4?w=600&h=450&fit=crop',
  },
  {
    id: '02',
    tag: 'DIRECTOR',
    title: 'B-ROLL SOURCING',
    desc: 'Empty scenes filled with sourced archival B-roll via live API tool calls.',
    before: 'https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?w=600&h=450&fit=crop',
    after: 'https://images.unsplash.com/photo-1518676590629-3dcbd9c5a5c9?w=600&h=450&fit=crop',
  },
  {
    id: '03',
    tag: 'EDITOR',
    title: 'KEN BURNS CHOREOGRAPHY',
    desc: 'Dead photos get a director\'s camera — GPU pan & zoom tied to the narration.',
    before: 'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=600&h=450&fit=crop',
    after: 'https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=600&h=450&fit=crop',
  },
  {
    id: '04',
    tag: 'SCREENWRITER',
    title: 'AUDIO SYNC',
    desc: 'Filler words cut, cadence mapped, music ducked 6dB under the voiceover.',
    before: 'https://images.unsplash.com/photo-1478737270239-2f02b77fc618?w=600&h=450&fit=crop',
    after: 'https://images.unsplash.com/photo-1518929458119-e5bf444c30f4?w=600&h=450&fit=crop',
  },
  {
    id: '05',
    tag: 'ORCHESTRATOR',
    title: 'FINAL CUT',
    desc: 'All tracks composited and graded. One MP4, sealed and timestamped.',
    before: 'https://images.unsplash.com/photo-1504701954957-2010ec3bcec1?w=600&h=450&fit=crop',
    after: 'https://images.unsplash.com/photo-1478720568477-152d9b164e26?w=600&h=450&fit=crop',
  },
]

/**
 * Storyboard — GSAP pinned horizontal "storyboard timeline".
 * Each step shows a before/after pair of real images.
 * Degrades to a vertical stack on mobile.
 */
export default function Storyboard() {
  const sectionRef = useRef(null)
  const trackRef = useRef(null)
  const [mounted, setMounted] = useState(false)

  useLayoutEffect(() => {
    setMounted(true)
  }, [])

  useLayoutEffect(() => {
    if (isMobile()) return

    const ctx = gsap.context(() => {
      const track = trackRef.current
      const section = sectionRef.current
      if (!track || !section) return

      const getAmount = () => track.scrollWidth - window.innerWidth
      const tween = gsap.to(track, {
        x: () => -getAmount(),
        ease: 'none',
        scrollTrigger: {
          trigger: section,
          start: 'top top',
          end: () => `+=${getAmount()}`,
          pin: true,
          scrub: 1,
          anticipatePin: 1,
          invalidateOnRefresh: true,
        },
      })

      gsap.from('.story-card', {
        x: 120,
        opacity: 0,
        rotateY: 18,
        transformOrigin: 'center center',
        stagger: 0.08,
        ease: 'power3.out',
        scrollTrigger: {
          trigger: track,
          start: 'top 80%',
          toggleActions: 'play none none reverse',
        },
      })

      return () => tween.kill()
    }, sectionRef)

    const onResize = () => ScrollTrigger.refresh()
    window.addEventListener('resize', onResize)

    return () => {
      window.removeEventListener('resize', onResize)
      ctx.revert()
    }
  }, [mounted])

  return (
    <section
      id="storyboard"
      ref={sectionRef}
      className="relative overflow-hidden"
    >
      <div className="absolute inset-0 z-0">
        <video
          className="absolute inset-0 h-full w-full object-cover"
          src="/storyboard-timeline.mp4"
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

      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-px bg-white/10" />

      <div className="relative z-10 flex flex-col md:h-screen md:overflow-hidden">
        <div className="flex items-end justify-between px-6 pb-4 pt-14 md:pt-16">
          <div className="px-2">
            <span className="font-mono text-[11px] uppercase tracking-widest3 text-cyanglow">
              [ II · STORYBOARD TIMELINE ]
            </span>
            <RevealText className="mt-3 font-display text-[clamp(2.2rem,6vw,4.5rem)] leading-none text-bone">
              RAW TO REEL
            </RevealText>
          </div>
          <div className="hidden pb-2 font-mono text-[10px] uppercase tracking-widest2 text-ash/40 md:block">
            scroll → timeline drifts
          </div>
        </div>

        <div className="relative md:flex-1">
          <div
            ref={trackRef}
            className="flex flex-col gap-8 px-6 pb-20 pt-6 md:flex-row md:items-center md:gap-14 md:px-[10vw] md:pb-0 md:pt-0 md:will-change-transform"
          >
            {storyboardSteps.map((step, i) => (
              <div key={step.id} className="story-card flex flex-col gap-4 md:min-w-[640px]">
                <div className="flex items-center gap-3">
                  <span className="font-display text-5xl text-outline-amber md:text-6xl">
                    {step.id}
                  </span>
                  <div>
                    <span className="font-mono text-[10px] uppercase tracking-widest3 text-amberglow">
                      {step.tag}
                    </span>
                    <h3 className="font-heading text-2xl uppercase tracking-wide text-bone md:text-3xl">
                      {step.title}
                    </h3>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="relative overflow-hidden rounded-sm border border-white/10 bg-[#0a0a0a]">
                    <img
                      src={step.before}
                      alt={`${step.title} before`}
                      className="aspect-[4/3] w-full object-cover"
                      loading="lazy"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                    <span className="absolute left-2 top-2 font-mono text-[8px] uppercase tracking-widest2 text-white/80">
                      BEFORE
                    </span>
                  </div>
                  <div className="relative overflow-hidden rounded-sm border border-amberglow/30 bg-[#0a0a0a]">
                    <img
                      src={step.after}
                      alt={`${step.title} after`}
                      className="aspect-[4/3] w-full object-cover"
                      loading="lazy"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-amberglow/10 to-transparent" />
                    <span className="absolute left-2 top-2 font-mono text-[8px] uppercase tracking-widest2 text-amberglow">
                      AFTER
                    </span>
                  </div>
                </div>

                <p className="max-w-[360px] font-light text-[13px] leading-relaxed text-ash/60">
                  {step.desc}
                </p>

                {i < storyboardSteps.length - 1 && (
                  <div className="h-px w-full bg-white/10 md:hidden" />
                )}
              </div>
            ))}

            <div className="hidden shrink-0 flex-col items-center justify-center gap-4 px-10 md:flex">
              <span className="font-mono text-[10px] uppercase tracking-widest3 text-ash/40">
                end of timeline
              </span>
              <svg viewBox="0 0 32 32" className="h-10 w-10 animate-spin-slow text-amberglow" fill="none" stroke="currentColor" strokeWidth="1.2">
                <circle cx="16" cy="16" r="13" />
                <circle cx="16" cy="16" r="5" fill="currentColor" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
