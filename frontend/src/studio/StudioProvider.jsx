import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { getCapabilities, getLedger, getReview } from '../lib/api'
import { useJob } from '../hooks/useJob'

const StudioContext = createContext(null)

const TERMINAL = ['COMPLETE', 'FAILED', 'NEEDS_REVIEW', 'CANCELLED']

/**
 * StudioProvider — shared job state and capability context.
 * The Studio page creates jobs; the Timeline page reads the live status,
 * capabilities, ledger, review, and the raw SSE event stream is owned by
 * each consumer hook (useTimeline, useJobEvents) so panels stay decoupled.
 */
export function StudioProvider({ children }) {
  const [activeJobId, setActiveJobId] = useState(() => {
    // deep-link: /studio/:jobId/timeline passes the id via URL, landing state
    // keeps it in sessionStorage so a refresh lands on the right job.
    try { return sessionStorage.getItem('cc.jobId') || null } catch { return null }
  })
  const [caps, setCaps] = useState({ support_envelope: {}, provider_menu: [] })
  const [ledger, setLedger] = useState(null)
  const [review, setReview] = useState(null)

  const setActiveJob = useCallback((jobId) => {
    setActiveJobId(jobId)
    setLedger(null)
    setReview(null)
    try { sessionStorage.setItem('cc.jobId', jobId || '') } catch { /* noop */ }
  }, [])

  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => {})
  }, [])

  const { job, jobMissing, loaded, jobRef } = useJob(activeJobId)

  useEffect(() => {
    if (!activeJobId) return
    let alive = true
    getLedger(activeJobId).then((d) => alive && setLedger(d)).catch(() => {})
    getReview(activeJobId).then((d) => alive && setReview(d)).catch(() => {})
    return () => { alive = false }
  }, [activeJobId, job?.status])

  const value = useMemo(() => ({
    activeJobId, setActiveJob,
    job, jobMissing, loaded, jobRef,
    caps, ledger, review,
  }), [activeJobId, setActiveJob, job, jobMissing, loaded, jobRef, caps, ledger, review])

  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>
}

export function useStudio() {
  const ctx = useContext(StudioContext)
  if (!ctx) throw new Error('useStudio must be used inside StudioProvider')
  return ctx
}

export default StudioProvider
