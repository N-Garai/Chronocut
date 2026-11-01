"""Standalone render worker (Path B renderer, no web server).

Runs on GitHub Actions (or any machine with ffmpeg + Firestore creds):

    python -m app.workers.render_worker --render-id r-abc

It reads the render document (job_id / revision / profile), fetches the EDL
revision, renders it with the EDL compiler, uploads the artifact to Supabase
Storage when configured, and writes the final URL back to Firestore.
Idempotent: an already-READY render is skipped.
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("chronocut.render_worker")


def _get_render_doc(render_id: str) -> Optional[Dict[str, Any]]:
    from app.services.renders import get_render
    return get_render(render_id)


async def run(render_id: str) -> int:
    from app.config import settings
    from app.services.renders import mark_status

    doc = _get_render_doc(render_id)
    if not doc:
        logger.error("render %s not found", render_id)
        return 2
    if doc.get("status") == "READY":
        logger.info("render %s already READY; skipping", render_id)
        return 0

    job_id = str(doc.get("job_id"))
    revision = int(doc.get("revision") or 0)
    profile = str(doc.get("profile") or "preview_480")

    from app.edl.store import get_revision
    rev_doc = get_revision(job_id, revision) or {}
    edl = rev_doc.get("edl") or doc.get("edl")
    if not edl:
        mark_status(job_id, render_id, "FAILED", error="no EDL revision found")
        logger.error("no EDL revision %s for job %s", revision, job_id)
        return 3

    mark_status(job_id, render_id, "RENDERING")

    from app.services.storage import render_dir
    out_dir = render_dir(job_id, render_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{profile}.mp4")

    def progress_cb(pct: int, msg: str) -> None:
        logger.info("[%s] %s %s%%", profile, msg, pct)

    from app.edl.compiler import quick_render_check, render_edl
    from app.tools.otio_export import write_otio
    from app.services.renders import update_render

    try:
        report = await render_edl(edl, out_path, profile_name=profile, job_id=job_id,
                                  progress_cb=progress_cb)
        if not report.get("ok") or not os.path.exists(out_path):
            mark_status(job_id, render_id, "FAILED",
                        error=str(report.get("error") or "render failed")[:300])
            return 4
        check = quick_render_check(out_path, kind=str(doc.get("kind") or "preview"))
        url = ""
        upload = upload_artifact(out_path, job_id, render_id)
        if upload:
            url = upload
        final_url = url or f"/api/v1/jobs/{job_id}/renders/{render_id}/video"
        mark_status(job_id, render_id, "READY", path=out_path, url=final_url,
                    duration=float(check.get("duration") or 0.0),
                    error="" if check.get("pass") else str(check.get("warning") or ""))
        try:
            write_otio(edl, os.path.join(out_dir, f"{profile}.otio"))
        except Exception:
            pass
        update_render(render_id, {"checks": {k: check.get(k) for k in
                                             ("duration", "audio", "black_first_frame", "pass")}})
        logger.info("render %s ready -> %s", render_id, final_url)
        return 0
    except Exception as e:
        logger.exception("render %s crashed", render_id)
        mark_status(job_id, render_id, "FAILED", error=str(e)[:300])
        return 5


def upload_artifact(path: str, job_id: str, render_id: str) -> str:
    """Upload to Supabase Storage when configured; returns the public/signed URL
    or "" when skipped. Never raises: the local API URL is the fallback."""
    from app.config import settings
    base_url = (settings.SUPABASE_URL or "").strip().rstrip("/")
    key = (settings.SUPABASE_SERVICE_KEY or "").strip()
    if not base_url or not key:
        return ""
    try:
        import requests
        object_path = f"{job_id}/{render_id}/{os.path.basename(path)}"
        bucket = "renders"
        resp = requests.post(
            f"{base_url}/storage/v1/object/{bucket}/{object_path}",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/octet-stream",
                "x-upsert": "true",
            },
            data=open(path, "rb"),
            timeout=600,
        )
        if resp.status_code not in (200, 201):
            logger.warning("supabase upload failed: %s %s", resp.status_code, resp.text[:200])
            return ""
        # Public bucket -> stable URL; otherwise mint a signed URL from the service key.
        public = f"{base_url}/storage/v1/object/public/{bucket}/{object_path}"
        try:
            import requests as rq
            check = rq.get(public, timeout=30)
            if check.status_code == 200:
                return public
        except Exception:
            pass
        sign = rq.post(
            f"{base_url}/storage/v1/object/sign/{bucket}/{object_path}",
            headers={"Authorization": f"Bearer {key}"},
            json={"expiresIn": 60 * 60 * 24 * 7},  # 7 days
            timeout=60)
        if sign.status_code == 200:
            return f"{base_url}/storage/v1{sign.json().get('signedURL', '')}"
        return ""
    except Exception as e:
        logger.warning("artifact upload skipped: %s", e)
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="ChronoCut standalone render worker")
    parser.add_argument("--render-id", required=True)
    args = parser.parse_args()
    rc = asyncio.get_event_loop().run_until_complete(run(args.render_id))
    sys.exit(rc)


if __name__ == "__main__":
    main()
