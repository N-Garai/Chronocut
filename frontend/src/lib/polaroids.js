function svgEncode(svg) {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

const grain = (opacity = 0.18) =>
  `<filter id="g"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="${opacity}"/></feComponentTransfer></filter>`

const vignette = (strength = 0.35) =>
  `<radialGradient id="v" cx="50%" cy="50%" r="70%">
     <stop offset="60%" stop-color="#000" stop-opacity="0"/>
     <stop offset="100%" stop-color="#000" stop-opacity="${strength}"/>
   </radialGradient>`

function mountains(w, h, base, peak) {
  let path = ''
  let x = 0
  while (x < w) {
    const seg = 60 + Math.random() * 90
    path += `L${x},${base} L${x + seg / 2},${peak} `
    x += seg
  }
  return `<path d="M0,${base} ${path}L${w},${base} L${w},${h} L0,${h} Z" fill="#1a1a1a"/>`
}

/**
 * Builds an abstract SVG "photograph". mode 'raw' = messy documentary still;
 * mode 'cut' = color-graded cinematic frame. Returns a data URI.
 */
export function polaroidSVG({ mode, seed = 0, hue = 45 }) {
  const w = 640
  const h = 480
  const rand = (n) => Math.abs(Math.sin(seed * 12.9898 + n * 78.233)) % 1

  if (mode === 'raw') {
    const clips = Array.from({ length: 8 }, (_, i) => {
      const x = rand(i * 3) * w
      const y = rand(i * 3 + 1) * h
      const rw = 60 + rand(i * 3 + 2) * 200
      const rh = 40 + rand(i * 3 + 3) * 160
      return `<rect x="${x}" y="${y}" width="${rw}" height="${rh}" fill="#0a0a0a" opacity="${0.25 + rand(i) * 0.5}"/>`
    }).join('')

    const specks = Array.from({ length: 26 }, (_, i) => {
      const x = rand(i * 7) * w
      const y = rand(i * 7 + 1) * h
      const r = 0.5 + rand(i) * 2
      return `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" opacity="${0.1 + rand(i + 4) * 0.5}"/>`
    }).join('')

    return svgEncode(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        <defs>${grain(0.4)}${vignette(0.5)}</defs>
        <rect width="${w}" height="${h}" fill="#141414"/>
        <rect width="${w}" height="${h}" fill="#1b1b1f"/>
        ${mountains(w, h, 360, 250)}
        ${clips}
        <rect x="${20}" y="${30}" width="${w * 0.5}" height="${34}" fill="#0d0d0d" opacity="0.7"/>
        <rect x="${20}" y="${74}" width="${w * 0.32}" height="${20}" fill="#0d0d0d" opacity="0.6"/>
        ${specks}
        <rect width="${w}" height="${h}" fill="url(#v)"/>
        <g filter="url(#g)"><rect width="${w}" height="${h}" fill="#aaa" opacity="0.35"/></g>
      </svg>`
    )
  }

  const skyTop = `hsl(${hue}, 45%, 12%)`
  const skyBottom = `hsl(${hue + 20}, 60%, 30%)`
  const sunX = 300 + (rand(5) - 0.5) * 120
  const sunY = 170 + (rand(6) - 0.5) * 60

  return svgEncode(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      <defs>${grain(0.14)}${vignette(0.45)}
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="${skyTop}"/><stop offset="1" stop-color="${skyBottom}"/>
        </linearGradient>
        <linearGradient id="grade" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#FFC300" stop-opacity="0.22"/>
          <stop offset="0.5" stop-color="#000" stop-opacity="0"/>
          <stop offset="1" stop-color="#00E5FF" stop-opacity="0.14"/>
        </linearGradient>
      </defs>
      <rect width="${w}" height="${h}" fill="url(#sky)"/>
      <circle cx="${sunX}" cy="${sunY}" r="70" fill="#FFC300" opacity="0.85"/>
      <circle cx="${sunX}" cy="${sunY}" r="110" fill="#FFC300" opacity="0.18"/>
      ${mountains(w, h, 400, 300)}
      <rect y="400" width="${w}" height="80" fill="#101318"/>
      <path d="M0,400 Q${w * 0.25},380 ${w * 0.5},402 T${w},398 V480 H0 Z" fill="#0c0e12"/>
      <path d="M0,418 Q${w * 0.4},396 ${w * 0.62},416 T${w},414 V480 H0 Z" fill="#000" opacity="0.55"/>
      <rect x="${50}" y="${70}" width="${w * 0.36}" height="${40}" fill="#000" opacity="0.5"/>
      <rect x="${52}" y="${120}" width="${w * 0.22}" height="${16}" fill="#000" opacity="0.42"/>
      <rect x="${w * 0.55}" y="${340}" width="${w * 0.3}" height="${18}" fill="#000" opacity="0.4"/>
      <rect width="${w}" height="${h}" fill="url(#grade)"/>
      <rect width="${w}" height="${h}" fill="url(#v)"/>
      <g filter="url(#g)"><rect width="${w}" height="${h}" fill="#ccc" opacity="0.3"/></g>
    </svg>`
  )
}

export const storyboardSteps = [
  {
    id: '01',
    title: 'Frame Extraction',
    tag: 'ARCHIVIST',
    desc: '47 messy stills de-warped, denoised and re-timed into a usable timeline.',
    seed: 1,
    hue: 45,
  },
  {
    id: '02',
    title: 'B-Roll Sourcing',
    tag: 'DIRECTOR',
    desc: 'Empty scenes filled with sourced archival B-roll via live Pexels tool calls.',
    seed: 3,
    hue: 190,
  },
  {
    id: '03',
    title: 'Ken Burns Choreography',
    tag: 'EDITOR',
    desc: 'Dead photos get a director\'s camera — GPU pan & zoom tied to the narration.',
    seed: 5,
    hue: 320,
  },
  {
    id: '04',
    title: 'Audio Sync',
    tag: 'SCREENWRITER',
    desc: 'Filler words cut, cadence mapped, music ducked 6dB under the voiceover.',
    seed: 8,
    hue: 90,
  },
  {
    id: '05',
    title: 'Final Cut',
    tag: 'ORCHESTRATOR',
    desc: 'All tracks composited and graded. One MP4, sealed and timestamped.',
    seed: 12,
    hue: 10,
  },
]
