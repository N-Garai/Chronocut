import { useEffect, useRef, useState, useCallback } from 'react'
import { eventsUrl } from '../lib/api'

// Subscribes to the backend SSE stream for a job and accumulates state_delta
// events into an array. Falls back gracefully if EventSource is unavailable.
export function useJobEvents(jobId) {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const esRef = useRef(null)

  const reset = useCallback(() => {
    setEvents([])
    setConnected(false)
  }, [])

  useEffect(() => {
    if (!jobId) return
    reset()
    let es
    try {
      es = new EventSource(eventsUrl(jobId))
    } catch (e) {
      return
    }
    esRef.current = es
    es.onopen = () => setConnected(true)
    // Named events (the backend marks these, so onmessage never sees them):
    // agent_activity rows land in the same array the pipeline stages use,
    // keeping the Studio console continuous across both formats.
    es.addEventListener('agent_activity', (ev) => {
      try {
        const data = JSON.parse(ev.data)
        setEvents((prev) => [...prev.slice(-200), { ...data, stage: 'agent_activity' }])
      } catch { /* ignore */ }
    })
    es.addEventListener('edl_revision', (ev) => {
      try {
        const data = JSON.parse(ev.data)
        setEvents((prev) => [...prev.slice(-200), { ...data, stage: data.stage || 'edl_updated' }])
      } catch { /* ignore */ }
    })
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        setEvents((prev) => [...prev.slice(-200), data])
      } catch {
        // ignore
      }
    }
    es.addEventListener('done', (ev) => {
      try {
        const data = JSON.parse(ev.data)
        setEvents((prev) => [...prev, { stage: 'done', message: `Status: ${data.status}`, status: data.status }])
      } catch {
        // ignore
      }
      setConnected(false)
      es.close()
    })
    es.onerror = () => {
      setConnected(false)
      // EventSource auto-reconnects; close on terminal handled above.
    }
    return () => {
      es.close()
    }
  }, [jobId, reset])

  return { events, connected }
}
