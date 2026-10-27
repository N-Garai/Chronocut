export const loaderEvents = [
  'BOOT AGENT RUNTIME',
  'ALLOC SANDBOX :: 512MB',
  'MOUNT STATE BANK :: JOB_0001',
  'ROUTING SEQUENTIAL [archivist -> scripting]',
  'SPAWN worker : audio_parse@0.3',
  'SPAWN worker : vision_tag@0.3',
  'GRID LOCK :: deterministic edges enforced',
  'CALIBRATE MODEL :: temp 0.2',
  'EQUILIBRIUM :: ready to ingest',
]

export const terminalFeed = [
  {
    agent: 'ARCHIVIST',
    tone: 'think',
    line: 'Parsing ZIP manifest... 12 audio / 47 photos discovered.',
  },
  {
    agent: 'ARCHIVIST',
    tone: 'ok',
    line: 'Transcribing interview_01.wav -> 4,212 words timestamped.',
  },
  {
    agent: 'ARCHIVIST',
    tone: 'think',
    line: 'Running speaker diarization... segmenting oral history passages.',
  },
  {
    agent: 'SCREENWRITER',
    tone: 'think',
    line: 'Cutting filler words :: um, like, you know (removed 31.4%).',
  },
  {
    agent: 'SCREENWRITER',
    tone: 'ok',
    line: 'Narrative arc detected :: [origin -> migration -> legacy].',
  },
  {
    agent: 'DIRECTOR',
    tone: 'tool',
    line: "Tool Call: B-roll search for '1960s harbor, film grain'.",
  },
  {
    agent: 'DIRECTOR',
    tone: 'tool',
    line: 'Tool Call: Archive fetch "vintage family portrait" (3 assets).',
  },
  {
    agent: 'DIRECTOR',
    tone: 'ok',
    line: 'Storyboard locked :: 12 shots, 4 scene transitions, motion layer.',
  },
  {
    agent: 'EDITOR',
    tone: 'think',
    line: 'Rendering timeline... compositing audio bed + b-roll.',
  },
  {
    agent: 'EDITOR',
    tone: 'tool',
    line: 'ffmpeg :: libx264 crf 18, two-pass encode 1920x1080@24fps.',
  },
  {
    agent: 'EDITOR',
    tone: 'think',
    line: 'Syncing voiceover to narration timestamps... ducking music 6dB.',
  },
  {
    agent: 'EDITOR',
    tone: 'ok',
    line: 'Final cut sealed :: CHRONOCUT_0001.mp4 (214 MB, 03:47).',
  },
  {
    agent: 'ORCHESTRATOR',
    tone: 'ok',
    line: 'White-box research report compiled :: sources + timestamps + tool calls.',
  },
  {
    agent: 'ORCHESTRATOR',
    tone: 'done',
    line: 'PIPELINE COMPLETE — artifacts ready for download.',
  },
]
