/**
 * timeline/agentBridge.js — maps a validated agent plan to timeline commands
 * One plan = one batch of ops = one undo entry.
 *
 * Pure functions only: the executing hook decides when to commit.
 */
import { cmdBatch } from './commands'

/**
 * Normalize a plan response into a server op batch:
 * { message, operations: [{op,args,...}], base_revision }.
 * Throws when the response is not a valid plan or exceeds 200 ops.
 */
export function normalizePlan(planResponse) {
  const ops = planResponse?.operations
  if (!Array.isArray(ops) || ops.length === 0) {
    throw new Error('agent plan has no operations')
  }
  if (ops.length > 200) {
    throw new Error(`agent plan too large (${ops.length} > 200)`)
  }
  for (const o of ops) {
    if (!o || typeof o !== 'object' || typeof o.op !== 'string') {
      throw new Error('agent plan contains a malformed operation')
    }
  }
  return { ops: cmdBatch(ops), message: planResponse.message || '', base_revision: planResponse.base_revision }
}

/** Whole-plan BatchCommand descriptor (one transaction). */
export function batchCommand(planResponse) {
  const { ops, message } = normalizePlan(planResponse)
  return { kind: 'batch', ops, message }
}

/** Requires-confirmation check (destructive = >3 clips or >25% duration delta). */
export function requiresConfirmation(planResponse, edl) {
  if (planResponse?.requires_confirmation) return true
  const ops = planResponse?.operations || []
  if (ops.length === 0) return false
  const destructive = ops.filter((o) => ['delete', 'remove_silence'].includes(o.op))
  if (destructive.length >= 3) return true
  if (destructive.length > 0 && parseFloat(edl?.project?.duration || 0) > 0) {
    // >25% of total duration removed by a single delete is destructive
    const removed = destructive
      .filter((o) => o.op === 'delete')
      .reduce((sum, o) => {
        const clip = (edl?.tracks || []).flatMap((t) => t.clips || []).find((c) => String(c.id) === String(o.args?.clip_id))
        return sum + Number(clip?.duration || 0)
      }, 0)
    if (removed / parseFloat(edl.project.duration) > 0.25) return true
  }
  return false
}

/** Client context sent with the agent request (playhead + selection). */
export function clientContext({ playheadMs, selectedClipIds }) {
  return {
    playhead_ms: Math.round(Number(playheadMs) || 0),
    selection: (selectedClipIds || []).slice(0, 20),
  }
}
