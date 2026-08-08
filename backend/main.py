import os

import httpx
from fastapi import FastAPI
from qdrant_client import QdrantClient

app = FastAPI(title="ecommerce-assistant-backend")

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

qdrant = QdrantClient(url=QDRANT_URL)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/qdrant")
def health_qdrant():
    try:
        collections = qdrant.get_collections()
        return {"status": "ok", "collections": [c.name for c in collections.collections]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/health/ollama")
def health_ollama():
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        return {"status": "ok", "models": models}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
