"""Container-aware available-memory reporting.

``psutil.virtual_memory().available`` reads /proc/meminfo, which reports the
HOST's memory, not the cgroup limit — on any container that shares the host
kernel (Docker with a memory cap, gVisor, some PaaS sandboxes) every "low
memory" guard built on it silently never fires and the OOM killer wins.
Render's free tier is a Firecracker microVM where /proc/meminfo happens to be
right, but guards must not depend on that.

``available_mb()`` returns the smaller of the psutil/sysconf estimate and the
cgroup headroom (v2 then v1), so a 512MB container honestly reports ~500MB
even when the host has 64GB free.
"""
import logging
import os

logger = logging.getLogger("chronocut.services.memory")

_CGROUP_V2_DIR = "/sys/fs/cgroup"
_CGROUP_V1_DIR = "/sys/fs/cgroup/memory"


def _cgroup_headroom_mb() -> float:
    """(limit - usage) in MB from cgroup v2 or v1; -1.0 when unlimited/absent."""
    # cgroup v2: memory.max is "max" or a byte count.
    try:
        with open(os.path.join(_CGROUP_V2_DIR, "memory.max"), "r") as f:
            raw = f.read().strip()
        if raw and raw != "max":
            limit = int(raw)
            if 0 < limit < (1 << 50):  # ignore absurd host-wide values
                used = 0
                try:
                    with open(os.path.join(_CGROUP_V2_DIR, "memory.current"), "r") as f:
                        used = int(f.read().strip())
                except Exception:
                    used = 0
                return (limit - used) / (1024 * 1024)
    except Exception:
        pass
    # cgroup v1
    try:
        with open(os.path.join(_CGROUP_V1_DIR, "memory.limit_in_bytes"), "r") as f:
            limit = int(f.read().strip())
        if 0 < limit < (1 << 50):
            used = 0
            try:
                with open(os.path.join(_CGROUP_V1_DIR, "memory.usage_in_bytes"), "r") as f:
                    used = int(f.read().strip())
            except Exception:
                used = 0
            return (limit - used) / (1024 * 1024)
    except Exception:
        pass
    return -1.0


def available_mb() -> float:
    """Best-effort available RAM in MB; 0.0 when truly unknowable so callers
    fail toward the low-memory path."""
    avail = -1.0
    try:
        import psutil  # type: ignore
        avail = psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        pass
    if avail < 0:
        try:
            avail = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
                     / (1024 * 1024))
        except Exception:
            avail = 0.0
    headroom = _cgroup_headroom_mb()
    if headroom >= 0:
        avail = headroom if avail < 0 else min(avail, headroom)
    return max(0.0, avail)
