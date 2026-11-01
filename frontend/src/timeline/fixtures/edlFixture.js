/**
 * Shared fixture EDL for the timeline unit tests. 15 s project, three 5 s
 * video shots, one caption row, one narration row — the same shape the
 * backend serializer emits (seconds, 3 decimals).
 */
export function makeEdl() {
  return {
    version: '1.0',
    revision: 1,
    project: { job_id: 'j-test', profile: 'youtube_landscape', duration: 15.0 },
    sources: [
      { id: 'img-a', type: 'image', path: '/media/a.png' },
      { id: 'img-b', type: 'image', path: '/media/b.png' },
      { id: 'img-c', type: 'image', path: '/media/c.png' },
    ],
    tracks: [
      {
        id: 'v1',
        type: 'video',
        clips: [
          { id: 'v1-01', source_id: 'img-a', start: 0.0, duration: 5.0, in: 0.0 },
          { id: 'v1-02', source_id: 'img-b', start: 5.0, duration: 5.0, in: 0.0 },
          { id: 'v1-03', source_id: 'img-c', start: 10.0, duration: 5.0, in: 0.0 },
        ],
      },
      {
        id: 'c1',
        type: 'caption',
        clips: [
          { id: 'c1-01', start: 0.0, duration: 3.0, text: 'first line' },
        ],
      },
      { id: 'a1', type: 'narration', clips: [] },
      { id: 'm1', type: 'music', clips: [] },
      { id: 's1', type: 'sfx', clips: [] },
    ],
  }
}

export function clipsOf(edl, trackId = 'v1') {
  return (edl.tracks || []).find((t) => t.id === trackId)?.clips || []
}

export function idsOf(edl, trackId = 'v1') {
  return clipsOf(edl, trackId).map((c) => String(c.id))
}
