import { useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { splitText } from '../lib/splitText'

gsap.registerPlugin(ScrollTrigger)

/**
 * RevealText — kinetic typography reveal.
 * Splits text into chars inside an overflow-hidden mask, then reveals by
 * animating the masked content wrapper from yPercent 110 -> 0 while each
 * character cascades up with a stagger.
 *
 * Props:
 *  - as: tag element (default 'h2')
 *  - className: classes for the visible element (must include font sizing)
 *  - charClassName: optional per-char class (e.g. color)
 *  - animateOnMount: trigger reveal once on mount (hero entrance)
 *  - stagger, duration, delay: GSAP timing
 *  - start, once: ScrollTrigger config for on-scroll reveals
 */
export default function RevealText({
  as: Tag = 'h2',
  children,
  className = '',
  charClassName = '',
  animateOnMount = false,
  stagger = 0.035,
  duration = 1.15,
  delay = 0,
  start = 'top 85%',
  once = true,
  ...rest
}) {
  const ref = useRef(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return

    let cleanup = () => {}
    try {
      const split = splitText(el)
      const content = split?.content
      if (!content) return

      const chars = el.querySelectorAll('.split-char')
      if (charClassName) {
        chars.forEach((c) => c.classList.add(charClassName))
      }

      const reduced =
        typeof window !== 'undefined' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches

      const ctx = gsap.context(() => {
        if (reduced) {
          gsap.set(content, { yPercent: 0 })
          return
        }

        const common = { duration, ease: 'power4.out' }
        const reveal = () =>
          gsap
            .timeline({ delay })
            .fromTo(content, { yPercent: 110 }, { yPercent: 0, ...common })
            .fromTo(
              chars,
              { yPercent: 45 },
              { yPercent: 0, stagger, duration: duration * 0.75, ease: 'power3.out' },
              0.06
            )

        if (animateOnMount) {
          reveal()
          return
        }

        const animation = reveal()
        ScrollTrigger.create({
          trigger: el,
          start,
          toggleActions: once ? 'play none none none' : 'play none none reverse',
          animation,
        })
      }, el)

      cleanup = () => ctx.revert()
    } catch (err) {
      // Fail-safe: never leave text hidden if the animation engine errors.
      console.error('RevealText animation failed; showing static text', err)
      el.style.visibility = 'visible'
      const content = el.querySelector('.split-content')
      if (content) {
        content.style.transform = 'none'
        content.style.opacity = '1'
      }
    }
    return cleanup
  }, [animateOnMount, charClassName, duration, stagger, delay, start, once])

  return (
    <Tag ref={ref} className={className} {...rest}>
      {children}
    </Tag>
  )
}
