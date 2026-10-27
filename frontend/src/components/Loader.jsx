import { useLayoutEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { loaderEvents } from '../data/agentLogs'

const CLAPPER_SVG = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><rect x="10" y="10" width="180" height="180" rx="12" fill="none" stroke="%23FFC300" stroke-width="6"/><rect x="10" y="10" width="180" height="60" rx="12" fill="%23050505"/><rect x="10" y="40" width="180" height="30" fill="%23FFC300"/><line x1="20" y1="25" x2="180" y2="25" stroke="%23050505" stroke-width="3"/><line x1="20" y1="35" x2="180" y2="35" stroke="%23050505" stroke-width="3"/><line x1="20" y1="45" x2="180" y2="45" stroke="%23050505" stroke-width="3"/><text x="100" y="85" text-anchor="middle" fill="%23FFC300" font-family="monospace" font-size="14" font-weight="bold">ACTION</text><text x="100" y="105" text-anchor="middle" fill="%23CFCFCF" font-family="monospace" font-size="10">CHRONOCUT</text><circle cx="100" cy="140" r="30" fill="none" stroke="%23FFC300" stroke-width="4"/><polygon points="92,130 92,150 112,140" fill="%23FFC300"/></svg>`)}`

export default function Loader({ onComplete }) {
  const overlayRef = useRef(null)
  const panelTopRef = useRef(null)
  const panelBottomRef = useRef(null)
  const clapperRef = useRef(null)
  const flashRef = useRef(null)
  const counterRef = useRef(null)
  const eventsRef = useRef(null)
  const [done, setDone] = useState(false)

  useLayoutEffect(() => {
    const counterEl = document.getElementById('loader-count')
    if (!counterEl) return

    const counter = { v: 0 }
    const updateCounter = () => {
      counterEl.textContent = String(Math.round(counter.v)).padStart(3, '0')
    }

    gsap.to(counter, {
      v: 100,
      duration: 2.4,
      ease: 'power2.inOut',
      onUpdate: updateCounter,
    })

    return () => updateCounter()
  }, [done])

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({
        onComplete: () => {
          setDone(true)
          onComplete && onComplete()
          document.documentElement.classList.remove('lenis-stopped')
        },
      })

      // Panels start OPEN so the loader content (incl. LIGHTS/CAMERA/ACTION)
      // is actually visible; they slam shut as a transition at the end.
      gsap.set(panelTopRef.current, { yPercent: -100 })
      gsap.set(panelBottomRef.current, { yPercent: 100 })

      // Phase 1: Circular spinner + counter (0-100)
      tl.fromTo('.loader-spinner', 
        { rotation: 0, opacity: 0 },
        { rotation: 360, opacity: 1, duration: 2.4, ease: 'none', repeat: 1 },
        0
      )
      tl.fromTo(counterRef.current, 
        { opacity: 0, scale: 0.8 },
        { opacity: 1, scale: 1, duration: 0.6, ease: 'back.out(2)' },
        0.2
      )
      tl.to('.loader-event', {
        opacity: 1,
        y: 0,
        stagger: 0.12,
        duration: 0.4,
        ease: 'power2.out',
      }, 0.4)

      // Phase 2: Fade out counter/events, show clapperboard
      tl.to(counterRef.current, { opacity: 0, y: -30, duration: 0.5, ease: 'power3.in' }, 2.6)
      tl.to(eventsRef.current, { opacity: 0, y: 20, duration: 0.4, ease: 'power3.in' }, 2.7)
      tl.to('.loader-spinner', { opacity: 0, scale: 0.5, duration: 0.4, ease: 'power3.in' }, 2.6)

      tl.fromTo(clapperRef.current,
        { opacity: 0, scale: 0.3, rotation: -20 },
        { opacity: 1, scale: 1, rotation: 0, duration: 0.7, ease: 'back.out(1.8)' },
        3.0
      )

      // Clapper slam
      tl.to(clapperRef.current, {
        scaleY: 0.25,
        duration: 0.12,
        ease: 'power4.in',
        yoyo: true,
        repeat: 1,
      }, 3.7)

      // Flash
      tl.to(flashRef.current, { opacity: 1, duration: 0.08, ease: 'power4.in' }, 3.9)
      tl.to(flashRef.current, { opacity: 0, duration: 0.5, ease: 'power2.out' }, 4.0)

      // Fade out clapper
      tl.to(clapperRef.current, { opacity: 0, scale: 1.4, duration: 0.6, ease: 'power3.in' }, 4.3)

      // Phase 3: "LIGHTS! CAMERA! ACTION!" text animation
      const words = gsap.utils.toArray('.cinematic-word')
      tl.fromTo(words,
        { opacity: 0, y: 60, scale: 0.8, rotateX: 20 },
        {
          opacity: 1,
          y: 0,
          scale: 1,
          rotateX: 0,
          stagger: 0.35,
          duration: 1.3,
          ease: 'power3.out',
        },
        4.6
      )
      tl.to(words, {
        opacity: 0,
        y: -50,
        scale: 0.85,
        rotateX: -15,
        stagger: 0.3,
        duration: 1.0,
        ease: 'power3.in',
        delay: 1.5,
      })

      // Phase 4: Shutter slam shut (panels started open via gsap.set above)
      tl.to(panelTopRef.current, { yPercent: 0, duration: 1.5 }, 7.0)
      tl.to(panelBottomRef.current, { yPercent: 0, duration: 1.5 }, 7.0)
      tl.to(overlayRef.current, { autoAlpha: 0, duration: 0.3 }, 7.8)

      // Safety fallback
      const failsafe = setTimeout(() => {
        setDone(true)
        onComplete && onComplete()
        document.documentElement.classList.remove('lenis-stopped')
      }, 9000)

      return () => {
        clearTimeout(failsafe)
      }
    }, overlayRef)

    return () => ctx.revert()
  }, [onComplete])

  if (done) return null

  return (
    <div ref={overlayRef} className="fixed inset-0 z-[200]">
      <div className="absolute inset-0 bg-carbon" />

      <div className="absolute inset-0 flex flex-col items-center justify-center px-6">
        {/* Phase 1: Spinner + Counter */}
        <div className="flex flex-col items-center gap-8">
          <div className="loader-spinner relative h-20 w-20 opacity-0">
            <svg className="h-full w-full animate-spin-slow text-amberglow" viewBox="0 0 80 80" fill="none">
              <circle cx="40" cy="40" r="32" stroke="currentColor" strokeWidth="2" opacity="0.2" />
              <circle cx="40" cy="40" r="32" stroke="currentColor" strokeWidth="3" strokeDasharray="180" strokeDashoffset="60" strokeLinecap="round" />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <svg viewBox="0 0 24 24" className="h-6 w-6 fill-amberglow">
                <path d="M8 5v14l11-7z" />
              </svg>
            </div>
          </div>

          <div ref={counterRef} className="loader-counter font-mono text-[clamp(3.5rem,14vw,9rem)] leading-none tracking-widest text-bone opacity-0">
            <span id="loader-count">000</span>
            <span className="text-amberglow">%</span>
          </div>

          <div className="font-mono text-[10px] uppercase tracking-widest2 text-ash/60">
            Initializing agent swarm
          </div>

          <div ref={eventsRef} className="loader-events mt-6 flex h-28 max-w-sm flex-col justify-center overflow-hidden font-mono text-[10px] leading-5 text-ash/80 sm:max-w-md">
            {loaderEvents.slice(0, 7).map((ev) => (
              <div key={ev} className="loader-event translate-y-3 opacity-0">
                <span className="text-cyanglow">› </span>
                {ev}
              </div>
            ))}
          </div>
        </div>

        {/* Phase 2: Clapperboard */}
        <div className="absolute flex flex-col items-center gap-6">
          <div className="relative">
            <img
              ref={clapperRef}
              src={CLAPPER_SVG}
              alt="Action"
              className="h-36 w-36 sm:h-44 sm:w-44"
              style={{ opacity: 0 }}
            />
          </div>
          <div className="font-mono text-sm uppercase tracking-[0.4em] text-amberglow">
            ACTION
          </div>
        </div>

        {/* Phase 3: Cinematic Text */}
        <div className="absolute flex flex-col items-center justify-center gap-2 sm:gap-3">
          {['LIGHTS!', 'CAMERA!', 'ACTION'].map((word) => (
            <span
              key={word}
              className="cinematic-word font-blackberry text-[clamp(2.8rem,10vw,7.5rem)] leading-[0.85] tracking-[0.12em] text-bone opacity-0"
              style={{ textShadow: '0 0 80px rgba(255,195,0,0.3), 0 4px 20px rgba(0,0,0,0.8)' }}
            >
              {word}
            </span>
          ))}
        </div>

        <div
          ref={flashRef}
          className="pointer-events-none absolute inset-0 bg-amberglow opacity-0"
        />
      </div>

      <div
        ref={panelTopRef}
        className="absolute inset-x-0 top-0 z-10 h-1/2 bg-[#0a0a0a]"
      />
      <div
        ref={panelBottomRef}
        className="absolute inset-x-0 bottom-0 z-10 h-1/2 bg-[#0a0a0a]"
      />
      <div className="pointer-events-none absolute inset-x-0 top-1/2 z-20 h-px -translate-y-1/2 bg-amberglow/40" />
    </div>
  )
}
