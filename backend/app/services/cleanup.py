import logging
import os
import shutil
import tempfile
import time

logger = logging.getLogger("chronocut.services.cleanup")

# Raw media (audio/photo/video) is only ever held on ephemeral disk here.
# It is NEVER written to Firestore / the JSON store — only lightweight
# metadata (paths, tags, transcripts, embeddings) is persisted.
_TEMP_ROOTS = [
    os.path.join(os.getcwd(), "tmp"),
    os.path.join(tempfile.gettempdir(), "chronocut_assets"),
    os.path.join(tempfile.gettempdir(), "chronocut_render"),
]


def cleanup_temp(max_age_hours: int = 24) -> int:
    """Delete ephemeral media files/dirs older than ``max_age_hours``.

    Returns the number of items removed. Safe to call frequently; cheap.
    """
    removed = 0
    cutoff = time.time() - max_age_hours * 3600
    for base in _TEMP_ROOTS:
        if not os.path.isdir(base):
            continue
        # Flat asset dir: drop individual old files.
        if base.endswith("chronocut_assets") or base.endswith("chronocut_render"):
            for f in os.listdir(base):
                p = os.path.join(base, f)
                try:
                    if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                        os.remove(p)
                        removed += 1
                except Exception:
                    pass
            continue
        # Per-job temp dirs: remove the whole dir once it is older than cutoff.
        for name in os.listdir(base):
            p = os.path.join(base, name)
            try:
                if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
                    removed += 1
            except Exception:
                pass
    return removed
