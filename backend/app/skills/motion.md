# Camera Motion

Per-shot camera moves (pure ffmpeg, free). Pick ONE move per shot; stacking moves
reads as unstable.

- **hold**: static frame. For interviews, titles, or when the footage is already moving.
- **push_in**: slow zoom toward the subject. Builds intensity / emphasis (climax).
- **pull_out**: slow zoom away. Reveals context / releases tension.
- **pan_left / pan_right**: slow lateral drift. Adds life to static images; use for
  "setup" beats and establishing shots.
- **parallax**: zoom + slight lateral drift (fake depth). For stylized motion graphics.
- **slowmo_0.5**: 50% speed (setpts). For emotional / tension beats.
- **speed_ramp**: accelerate within the shot. For energetic montages.

Rule: match the move to the emotion. Climax → push_in; tension → slowmo; release →
pull_out; setup → pan. Never apply a zoom move to already-moving video footage
(use pan/crop instead) to avoid stutter.
