import { useEffect, useRef, useState } from 'react'
import { getJob } from '../lib/api'

const TERMINAL = ['COMPLETE', 'FAILED', 'NEEDS_REVIEW', 'CANCELLED', 'DELETED']

/**
 * useJob — live job status polled every ~1.2s while processing. `jobMissing`
 * distinguishes a true 404 (not_found page state) from net noise.
 */
export function useJob(jobId) {
  const [job, setJob] = useState(null)
  const [jobMissing, setJobMissing] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const jobRef = useRef(null)

  useEffect(() => {
    if (!jobId) return
    let alive = true
    let timer
    async function tick() {
      let stop = false
      try {
        const data = await getJob(jobId)
        if (!alive) return
        setJobMissing(false)
        setLoaded(true)
        setJob(data)
        jobRef.current = data
        if (TERMINAL.includes(data.status)) stop = true
      } catch (e) {
        if (!alive) return
        if (e.status === 404) { setJobMissing(true); setLoaded(true); return }
      }
      if (!stop) timer = setTimeout(tick, 3000)
    }
    tick()
    return () => { alive = false; clearTimeout(timer) }
  }, [jobId])

  return { job, jobMissing, loaded, jobRef }
}

export default useJob
