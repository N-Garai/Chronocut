// API client for ChronoCut backend. Base URL is relative in dev / Vite
// previews; a public static deployment sets VITE_API_BASE_URL to the API
// origin (the API no longer serves the frontend itself).

export const API = `${import.meta.env?.VITE_API_BASE_URL || ''}/api/v1`

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

async function request(path, init = undefined) {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    let detail
    try { detail = (await res.json()).detail } catch { detail = null }
    const err = new Error(typeof detail === 'string' ? detail : detail?.message || `Request failed (${res.status})`)
    err.status = res.status
    err.detail = detail
    throw err
  }
  return res.json()
}

export async function createJob(payload) {
  // raw media files ride as media[]; a single zip legacy path keeps working
  const form = buildForm(payload)
  if (payload.mediaFiles?.length) {
    form.delete('file')
    for (const f of payload.mediaFiles) form.append('media', f, f.name)
  }
  return request('/jobs', { method: 'POST', body: form })
}

export const getJob = (jobId) => request(`/jobs/${jobId}`)

export const getLedger = (jobId) =>
  request(`/jobs/${jobId}/ledger`).catch(() => ({ calls: [], total_cost_cents: 0 }))

export const getReview = (jobId) =>
  request(`/jobs/${jobId}/review`).catch(() => ({}))

export const getCapabilities = () =>
  request('/capabilities').catch(() => ({ support_envelope: {}, provider_menu: [] }))

export const getEdl = (jobId) =>
  request(`/jobs/${jobId}/edl`)

export const putEdl = (jobId, edl, baseRevision) =>
  request(`/jobs/${jobId}/edl`, { method: 'PUT', body: JSON.stringify({ edl, base_revision: baseRevision }) })

export const postEdlOperations = (jobId, operations, baseRevision, { dryRun = false } = {}) =>
  request(`/jobs/${jobId}/edl/operations`, {
    method: 'POST',
    body: JSON.stringify({ operations, base_revision: baseRevision, dry_run: dryRun }),
  })

export const postAgent = (jobId, payload) =>
  request(`/jobs/${jobId}/agent`, { method: 'POST', body: JSON.stringify(payload) })

export const getAgentActivity = (jobId, limit = 50) =>
  request(`/jobs/${jobId}/agent/activity?limit=${limit}`).catch(() => ({ job_id: jobId, activity: [] }))

export const getAssets = (jobId) =>
  request(`/jobs/${jobId}/assets`).catch(() => ({ job_id: jobId, assets: [] }))

export const assetThumbUrl = (thumbUrl) =>
  (thumbUrl ? `${API}${String(thumbUrl).replace(/^\/api\/v1/, '')}` : null)

/** Cached waveform PNG for one audio asset (empty string = none rendered). */
export const waveformUrl = (jobId, assetId) =>
  (jobId && assetId
    ? `${API}/jobs/${jobId}/waveform?asset_id=${encodeURIComponent(assetId)}`
    : '')

export const getRenders = (jobId) =>
  request(`/jobs/${jobId}/renders`).catch(() => ({ renders: [] }))

export function queueRender(jobId, body) {
  return request(`/jobs/${jobId}/render`, { method: 'POST', body: JSON.stringify(body) })
}

export function videoUrl(jobId, profile) {
  return `${API}/jobs/${jobId}/video${profile ? `?profile=${encodeURIComponent(profile)}` : ''}`
}

export function renderedUrl(jobId, renderId) {
  return `${API}/jobs/${jobId}/renders/${renderId}/video`
}

export function edlOtioUrl(jobId, revision) {
  return `${API}/jobs/${jobId}/edl.otio${revision ? `?revision=${revision}` : ''}`
}

export function eventsUrl(jobId) {
  return `${API}/jobs/${jobId}/events`
}
