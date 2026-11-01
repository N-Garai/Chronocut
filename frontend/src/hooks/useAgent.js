import { useCallback, useRef, useState } from 'react'
import { postAgent } from '../lib/api'
import { normalizePlan, requiresConfirmation, clientContext } from '../timeline/agentBridge'

/**
 * useAgent — sends a natural-language command, validates the plan response
 * and hands it to the caller as a one-undo batch.
 *
 * The actual EDL write goes through the timeline's execute() so manual and
 * agent edits share the same command path. `409` keeps the draft and flips
 * `staleConflict`; the caller shows the banner and requires an explicit
 * reload before re-planning.
 *
 * Destructive plans (server flag, or the client-side >3 clips / >25% duration
 * rule) are returned without applying: the caller shows a confirmation and
 * calls `resolve(plan, { applied, onApply })` once the user decides.
 */
export function useAgent(jobId, { playheadMs, selectedClipIds }) {
  const [busy, setBusy] = useState(false)
  const [lastPlan, setLastPlan] = useState(null)
  const [actions, setActions] = useState([]) // in-memory action log
  const [staleConflict, setStaleConflict] = useState(null)
  const actionSeq = useRef(0)

  const request = useCallback(async (message, { onApply, needsConfirmation } = {}) => {
    if (!message?.trim() || busy) return null
    setBusy(true)
    const entry = {
      id: `act-${++actionSeq.current}`,
      ts: new Date().toISOString(),
      actor: 'user',
      message: String(message).trim(),
      status: 'running',
    }
    setActions((a) => [...a, entry])
    try {
      const body = {
        message: String(message).trim(),
        base_revision: null, // plan-only; server validates on apply
        context: clientContext({ playheadMs, selectedClipIds }),
      }
      const plan = await postAgent(jobId, body)
      entry.plan = plan
      entry.latencyMs = plan.duration_ms
      entry.revisionBefore = plan.base_revision
      setLastPlan(plan)

      let ops = []
      try { ops = normalizePlan(plan).ops } catch { ops = [] }
      entry.operationCount = ops.length

      const destructive = Boolean(plan.requires_confirmation)
        || (typeof needsConfirmation === 'function' && ops.length > 0 && needsConfirmation(plan))

      if (destructive && ops.length > 0) {
        // One interaction: keep the plan, let the user confirm or cancel.
        entry.status = 'planned'
        entry.needsConfirmation = true
      } else if (onApply && ops.length > 0) {
        const ok = onApply(ops)
        entry.status = ok ? 'applied' : 'failed'
        entry.appliedOps = ops.length
      } else {
        entry.status = 'planned'
      }
      setActions((a) => [...a])
      return plan
    } catch (e) {
      entry.status = e.status === 409 ? 'stale' : 'failed'
      entry.error = String(e?.message || e)
      if (e.status === 409) setStaleConflict(e?.detail?.stale_revision ?? 'conflict')
      setActions((a) => [...a])
      return null
    } finally {
      setBusy(false)
    }
  }, [busy, jobId, playheadMs, selectedClipIds])

  /** Commit or discard a plan that was held for confirmation. */
  const resolve = useCallback((plan, { applied = false, onApply } = {}) => {
    let ops = []
    try { ops = normalizePlan(plan).ops } catch { ops = [] }
    const ok = Boolean(applied && onApply && ops.length) && onApply(ops)
    const status = !applied ? 'rejected' : ok ? 'applied' : 'failed'
    setActions((a) => a.map((e) => (e.plan === plan ? { ...e, status, appliedOps: ok ? ops.length : 0 } : e)))
    return ok
  }, [])

  return {
    busy, request, resolve, lastPlan, actions, staleConflict,
    clearConflict: () => setStaleConflict(null),
    requiresConfirmation, canPlan: !staleConflict,
  }
}

export default useAgent
