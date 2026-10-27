import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Play, ArrowDown, Radio } from 'lucide-react'
import CanvasField from './CanvasField'
import RevealText from './RevealText'
import Magnetic from './Magnetic'

gsap.registerPlugin(ScrollTrigger)

const HERO_VIDEO = '/hero-section.mp4'

/**
 * HeroCinematic — full-bleed kinetic type hero with video background
 * and magnetic CTA. Parallax scales the backdrop on scroll.
 */
export default function Hero({ videoSrc = HERO_VIDEO, showVideo = true }) {
  const sectionRef = useRef(null)
  const bgRef = useRef(null)
  const titleRef = useRef(null)
  const taglineRef = useRef(null)
  const videoRef = useRef(null)

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const section = sectionRef.current
      if (!section) return

      ScrollTrigger.create({
        trigger: section,
        start: 'top top',
        end: 'bottom top',
        scrub: true,
        onUpdate: (self) => {
          const p = self.progress
          if (bgRef.current) {
            gsap.set(bgRef.current, { scale: 1.1 - p * 0.12 })
          }
          if (titleRef.current) {
            gsap.set(titleRef.current, {
              yPercent: p * -40,
              opacity: 1 - p * 1.2,
            })
          }
          if (taglineRef.current) {
            gsap.set(taglineRef.current, {
              opacity: 1 - p * 3,
              yPercent: p * 20,
            })
          }
        },
      })

      const tagline = taglineRef.current
      if (tagline) {
        gsap.fromTo(
          tagline,
          { opacity: 0, y: 40, rotateX: 8 },
          {
            opacity: 1,
            y: 0,
            rotateX: 0,
            duration: 1.6,
            ease: 'power3.out',
            delay: 2,
          }
        )
      }
    }, sectionRef)

    return () => ctx.revert()
  }, [])

  const scrollToIngest = () => {
    const el = document.querySelector('#ingest')
    const lenis = window.__lenis
    if (lenis) lenis.scrollTo(el, { offset: -30 })
    else el && el.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <section
      id="top"
      ref={sectionRef}
      className="relative flex h-[100svh] min-h-[640px] flex-col justify-end overflow-hidden"
    >
      <div ref={bgRef} className="absolute inset-0 will-change-transform">
        {showVideo && (
          <video
            ref={videoRef}
            className="absolute inset-0 h-full w-full object-cover"
            src={videoSrc}
            autoPlay
            loop
            muted
            playsInline
            preload="auto"
          />
        )}
        {!showVideo && <CanvasField className="h-full w-full" />}
        <div className="absolute inset-0 bg-gradient-to-b from-void/60 via-void/30 to-void" />
        <div className="absolute inset-0 bg-void/20" />
      </div>

      <div className="pointer-events-none absolute inset-0 z-[2]">
        <div className="absolute left-6 top-24 sm:left-10">
          <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest3 text-cyanglow">
            <Radio size={12} className="animate-pulse-soft" />
            SWARM ONLINE — 4 AGENTS ACTIVE
          </div>
          <div className="mt-2 font-mono text-[10px] uppercase tracking-widest2 text-ash/50">
            Autonomous Swarm · Background Processing · Deterministic Graph
          </div>
        </div>

        <div className="absolute bottom-24 right-6 hidden sm:right-10 lg:block">
          <div className="flex flex-col items-end gap-1 font-mono text-[10px] uppercase tracking-widest2 text-ash/50">
            <span>SEQ.01 — INGEST</span>
            <span className="text-amberglow">SEQ.02 — SCRIPT</span>
            <span>SEQ.03 — SOURCE</span>
            <span>SEQ.04 — RENDER</span>
          </div>
        </div>
      </div>

      <div className="relative z-[3] px-6 pb-16 sm:px-10 sm:pb-20">
        <h1
          ref={titleRef}
          className="font-display text-[clamp(4rem,17vw,17rem)] leading-[0.95] tracking-[-0.01em] text-bone"
          style={{ lineHeight: '0.95' }}
        >
          <RevealText as="span" animateOnMount delay={0.35} stagger={0.05} className="block mb-2">
            CHRONOCUT
          </RevealText>
          <span className="block text-outline">
            <RevealText as="span" animateOnMount delay={0.6} stagger={0.03} className="block">
              AUTONOMOUS
            </RevealText>
          </span>
        </h1>

        <div
          ref={taglineRef}
          className="mt-6 max-w-xl"
          style={{ opacity: 0 }}
        >
          <p className="font-blackberry text-[clamp(1.4rem,3vw,2.2rem)] leading-snug text-bone/90">
            Theme is art
          </p>
        </div>

        <div className="mt-8 flex flex-col gap-8 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex items-center gap-6">
            <Magnetic strength={0.35}>
              <button
                onClick={scrollToIngest}
                data-cursor="play"
                className="group relative flex items-center gap-3 overflow-hidden rounded-full bg-amberglow px-7 py-4 font-mono text-[11px] font-bold uppercase tracking-widest2 text-void transition-transform duration-300 hover:scale-[1.03]"
              >
                <span className="absolute inset-0 -translate-x-full bg-bone transition-transform duration-500 group-hover:translate-x-0" />
                <Play size={14} className="relative z-10 fill-void" />
                <span className="relative z-10">Initialize Agent Swarm</span>
              </button>
            </Magnetic>

            <a
              href="#storyboard"
              onClick={(e) => {
                e.preventDefault()
                const el = document.querySelector('#storyboard')
                const lenis = window.__lenis
                if (lenis) lenis.scrollTo(el, { offset: -10 })
                else el && el.scrollIntoView({ behavior: 'smooth' })
              }}
              className="group flex flex-col items-center gap-2 font-mono text-[10px] uppercase tracking-widest2 text-ash/60 transition-colors hover:text-bone"
            >
              Scroll
              <ArrowDown size={16} className="animate-bounce text-amberglow" />
            </a>
          </div>
        </div>
      </div>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[3] h-24 bg-gradient-to-t from-void to-transparent" />
    </section>
  )
}
