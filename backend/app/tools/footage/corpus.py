import logging

logger = logging.getLogger("chronocut.tools.footage.corpus")

# The semantic footage corpus (M6) is now maintained via the Firestore/local
# store in `clip_search.store_footage` (Gemini embeddings, no CLIP dependency).
# This module re-exports the helpers so the public footage API stays stable.
from app.tools.footage.clip_search import store_footage, corpus_search  # noqa: F401

__all__ = ["store_footage", "corpus_search"]
