"""Modal render dispatch shim.

``app.services.renders.dispatch_modal`` imports ``spawn_render`` lazily from
this module so the API container stays importable without the ``modal``
package installed. The real function call happens on Modal's hosted
infrastructure; locally we only enqueue it through the Modal client.
"""
import logging
from typing import Any

logger = logging.getLogger("chronocut.modal_render")


async def spawn_render(job_id: str, render_id: str, revision: int, profile: str) -> Any:
    """Fire one ``run_render`` invocation on the deployed Modal app (Path A)."""
    try:
        import modal  # optional dependency; API container may not have it
    except Exception as e:  # pragma: no cover - depends on install choice
        logger.warning("modal client unavailable: %s", e)
        raise

    from modal.function import Function  # type: ignore

    try:
        fn = Function.from_name("chronocut-run-render", dryrun=False)
    except Exception as e:
        logger.warning("modal function 'chronocut-run-render' not deployed: %s", e)
        raise

    return fn.spawn(job_id, render_id, int(revision), profile)
