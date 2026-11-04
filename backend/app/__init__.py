# Backend package

import os as _os

# Bundled ffmpeg lives in backend/bin; PowerShell/cmd sessions often don't
# have it on PATH, and every ffmpeg invocation in the codebase shells out by
# the bare name "ffmpeg" (WinError 2 otherwise). Prepending here — before any
# app module runs, in both the API server and spawned worker children — makes
# the binary discoverable regardless of the launching shell.
_BIN = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "bin")
if _os.path.isdir(_BIN):
    if _os.name == "nt":
        _sep = ";"
        _os.environ["PATH"] = _BIN + _sep + _os.environ.get("PATH", "")
    else:
        _os.environ["PATH"] = _BIN + _os.pathsep + _os.environ.get("PATH", "")
