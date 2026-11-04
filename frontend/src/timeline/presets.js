/**
 * timeline/presets.js — shared option lists for the left-rail panels and the
 * inspector. Values must stay in sync with the server op validation
 * (backend/app/edl/operations.py) and the render filter allow-lists
 * (backend/app/edl/compiler.py).
 */
export const GRADES = ['clean', 'nostalgic', 'professional', 'cinematic', 'warm', 'neutral', 'teal_orange', 'bw']
export const MOTIONS = ['hold', 'push_in', 'pull_out', 'pan_left', 'pan_right', 'parallax', 'ken_burns_in', 'ken_burns_out', 'slowmo_0.5', 'speed_ramp']
export const TRANSITIONS = ['cut', 'crossfade_0.5s', 'crossfade_1s', 'dissolve', 'dip_black', 'fade']

export const TRANSITION_LABELS = {
  cut: 'Cut',
  'crossfade_0.5s': 'Crossfade 0.5s',
  'crossfade_1s': 'Crossfade 1s',
  dissolve: 'Dissolve',
  dip_black: 'Dip to black',
  fade: 'Fade',
}

export const TEXT_PRESETS = [
  { id: 'title', label: 'Title card', text: 'Your title here', durationMs: 3000 },
  { id: 'lower_third', label: 'Lower third', text: 'Name · Role', durationMs: 4000 },
  { id: 'caption', label: 'Caption', text: 'A short caption line', durationMs: 2500 },
]
