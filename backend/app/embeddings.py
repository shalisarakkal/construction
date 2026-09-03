"""Local embedding model wrapper. Uses sentence-transformers (free, offline
after first download, no API key) rather than an OpenAI embedding API, per
the privacy/cost tradeoff flagged during planning: these documents may
include proprietary engineering notes in later phases even though the NJ
regulation PDFs used for Phase 1 testing are public. Swappable later by
replacing this module's implementation without touching callers, since both
upload and query paths only depend on `embed_texts` / `embed_query`.
"""

from functools import lru_cache

import numpy as np

from .config import settings


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model_name)


def embed_texts(texts: list[str]) -> np.ndarray:
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.astype("float32")


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]
