// API client for ChronoCut backend. All calls are relative so the same
// bundle works whether served by FastAPI or proxied in dev.

const API = '/api/v1'

function buildForm({ file, mode, prompt, referenceUrl, targetLanguage, outputProfiles, tone, lengthSeconds, targetAudience }) {
  const fd = new FormData()
  if (mode) fd.append('mode', mode)
  if (prompt != null) fd.append('prompt', prompt)
  if (referenceUrl != null) fd.append('reference_url', referenceUrl)
  if (targetLanguage) fd.append('target_language', targetLanguage)
  if (outputProfiles) fd.append('output_profiles', outputProfiles)
  if (tone) fd.append('tone', tone)
  if (lengthSeconds != null) fd.append('length_seconds', String(lengthSeconds))
  if (targetAudience) fd.append('target_audience', targetAudience)
  if (file) fd.append('file', file, 'media.zip')
  return fd
}

export async function createJob(payload) {
  const res = await fetch(`${API}/jobs`, { method: 'POST', body: buildForm(payload) })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error(err.detail || 'Failed to create job')
  }
  return res.json()
}

export async function getJob(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}`)
  if (!res.ok) throw new Error('Job not found')
  return res.json()
}

export async function getLedger(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/ledger`)
  if (!res.ok) return { calls: [], total_cost_cents: 0 }
  return res.json()
}

export async function getReview(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/review`)
  if (!res.ok) return {}
  return res.json()
}

export async function getChangelog(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/changelog`)
  if (!res.ok) return {}
  return res.json()
}

export async function getCapabilities() {
  const res = await fetch(`${API}/capabilities`)
  if (!res.ok) return { support_envelope: {}, provider_menu: [] }
  return res.json()
}

export function videoUrl(jobId, profile) {
  return `${API}/jobs/${jobId}/video${profile ? `?profile=${encodeURIComponent(profile)}` : ''}`
}

export function eventsUrl(jobId) {
  return `${API}/jobs/${jobId}/events`
}
