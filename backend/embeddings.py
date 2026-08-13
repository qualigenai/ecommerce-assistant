from typing import List

from sentence_transformers import SentenceTransformer

_model = None


def get_model() -> SentenceTransformer:
    """Load the model once and reuse it — reloading per request would be
    slow and pointless, since the model itself is stateless."""
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_text(text: str) -> List[float]:
    return get_model().encode(text).tolist()


def embed_texts(texts: List[str]) -> List[List[float]]:
    return get_model().encode(texts).tolist()
