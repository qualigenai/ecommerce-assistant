import os
from typing import List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

import crud
import embeddings
import routing
import schemas
import telemetry
import vector_store
from database import Base, engine, get_db
from seed_data import seed_if_empty

app = FastAPI(title="ecommerce-assistant-backend")

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

qdrant = QdrantClient(url=QDRANT_URL)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    count = seed_if_empty(db)
    print(f"Catalog ready with {count} products (0 means already seeded).")
    # Embedding + indexing is NOT run automatically on startup — it's a
    # deliberate step via /reindex, so a slow model load never blocks the
    # health checks or delays the container reporting healthy.


# ---------- Health checks (from Day 1) ----------

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
        models_list = [m["name"] for m in r.json().get("models", [])]
        return {"status": "ok", "models": models_list}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ---------- Product CRUD (Day 3) ----------

@app.post("/products", response_model=schemas.ProductOut)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    return crud.create_product(db, product)


@app.get("/products", response_model=List[schemas.ProductOut])
def list_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_products(db, skip=skip, limit=limit)


@app.get("/products/{product_id}", response_model=schemas.ProductOut)
def read_product(product_id: int, db: Session = Depends(get_db)):
    db_product = crud.get_product(db, product_id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product


@app.put("/products/{product_id}", response_model=schemas.ProductOut)
def update_product(product_id: int, product: schemas.ProductCreate, db: Session = Depends(get_db)):
    db_product = crud.update_product(db, product_id, product)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product


@app.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    deleted = crud.delete_product(db, product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "deleted", "id": product_id}


@app.get("/search", response_model=List[schemas.ProductOut])
def search(
    category: Optional[str] = None,
    price_lt: Optional[float] = None,
    price_gt: Optional[float] = None,
    waterproof: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """The fast path — pure SQL filtering, no AI involved."""
    return crud.search_products(
        db, category=category, price_lt=price_lt, price_gt=price_gt, waterproof=waterproof
    )


# ---------- Embeddings & semantic search (Day 4) ----------

@app.post("/reindex")
def reindex(db: Session = Depends(get_db)):
    """Refresh the vector index from the current catalog. Call this after
    any catalog change — in production this would be triggered by a
    webhook on product create/update rather than run manually."""
    products = crud.get_products(db, limit=1000)
    count = vector_store.upsert_products(products, embeddings.embed_texts)
    return {"status": "ok", "indexed": count}


@app.get("/search/semantic")
def semantic_search(q: str, limit: int = 5, db: Session = Depends(get_db)):
    """The AI path's retrieval step — embedding similarity, no LLM call yet
    (that's Day 7). Used directly here so it can be tested in isolation."""
    with telemetry.timed() as elapsed:
        vector = embeddings.embed_text(q)
        results = vector_store.semantic_search(vector, limit=limit)
        payload = [r.payload for r in results]
    telemetry.log_query(db, query_text=q, path="ai", latency_ms=elapsed(), result_count=len(payload))
    return payload


# ---------- Combined assistant endpoint — the routing heuristic in action ----------

@app.get("/assistant/search")
def assistant_search(q: str, db: Session = Depends(get_db)):
    """
    The single entry point a chat UI or search bar would actually call.
    Decides fast-path vs AI-path using the routing heuristic, executes the
    right one, and logs the decision for observability — per the trust &
    reliability framework, every routed query leaves a trace.
    """
    decision = routing.route_query(q)

    with telemetry.timed() as elapsed:
        try:
            if decision["path"] == "filter":
                f = decision["filters"]
                results = crud.search_products(
                    db,
                    category=f["category"],
                    price_lt=f["price_lt"],
                    price_gt=f["price_gt"],
                    waterproof=f["waterproof"],
                )
                payload = [schemas.ProductOut.model_validate(p).model_dump() for p in results]
            else:
                vector = embeddings.embed_text(q)
                vresults = vector_store.semantic_search(vector, limit=5)
                payload = [r.payload for r in vresults]
            success, error = True, None
        except Exception as e:
            # TRUST PRINCIPLE: Reliability
            #
            # Business Purpose:
            #     Keep the search experience available even when one path
            #     (filter or AI) fails unexpectedly.
            #
            # Design Decision:
            #     Catch broadly at the routing-execution boundary and
            #     degrade to an empty result plus a logged error, rather
            #     than letting an unhandled exception reach the customer.
            #
            # Benefits:
            #     - No single failure mode takes down the whole endpoint
            #     - The failure is still fully recorded, never hidden
            #
            # Failure Strategy:
            #     success=False and the exception message are captured
            #     here and logged via telemetry.log_query() below — every
            #     failure is visible and traceable, not silent.
            #
            # Future Validation:
            #     Error rate trend over time (Layer 1: Reliability metrics)
            #
            # See also: docs/trust-and-reliability-framework.md
            payload = []
            success, error = False, str(e)

    latency = elapsed()
    # OBSERVABILITY + GOVERNANCE PRINCIPLE:
    # Every routed query is logged with its path, reason, and confidence —
    # not just success/failure. This is what makes a routing decision
    # reviewable after the fact: an auditor or engineer can answer "why did
    # this query go where it went" from the log alone, without needing to
    # reproduce the request.
    telemetry.log_query(
        db, query_text=q, path=decision["path"], latency_ms=latency,
        result_count=len(payload), reason=decision["reason"],
        confidence=decision["confidence"], success=success, error=error,
    )

    return {
        "query": q,
        "path": decision["path"],
        "reason": decision["reason"],
        "confidence": decision["confidence"],
        "filters_used": decision["filters"],
        "latency_ms": round(latency, 1),
        "results": payload,
    }


# ---------- Recommendations (Day 5) ----------

@app.get("/products/{product_id}/recommendations")
def get_recommendations(product_id: int, limit: int = 5, db: Session = Depends(get_db)):
    """Embedding-similarity 'related products' for a product detail page.
    Reuses the same Qdrant index built by /reindex on Day 4."""
    with telemetry.timed() as elapsed:
        similar = vector_store.recommend_similar(product_id, limit=limit)
        if similar is None:
            latency = elapsed()
            # GOVERNANCE PRINCIPLE:
            # The missing-index (cold-start) case is logged as an explicit
            # failure, not silently swallowed into an empty success
            # response. A 0-result success and a "not indexed" failure
            # look identical to a customer but mean very different things
            # to an engineer investigating the log later — this keeps them
            # distinguishable.
            telemetry.log_query(
                db, query_text=f"recommend:{product_id}", path="recommend",
                latency_ms=latency, result_count=0, success=False,
                error="Product not indexed in Qdrant — run /reindex, or this is a cold-start case for Day 6.",
            )
            raise HTTPException(
                status_code=404,
                detail="Product not indexed for recommendations yet. Run /reindex, "
                       "or this is a cold-start product (Day 6 will add a fallback).",
            )
        payload = [r.payload for r in similar]
        latency = elapsed()

    # OBSERVABILITY PRINCIPLE:
    # Every recommendation request is logged with latency, result count,
    # and success/failure status.
    #
    # This creates an audit trail that allows engineers to investigate
    # failures, monitor performance trends, and validate recommendation
    # quality over time.
    telemetry.log_query(
        db, query_text=f"recommend:{product_id}", path="recommend",
        latency_ms=latency, result_count=len(payload), success=True,
    )
    return {"product_id": product_id, "latency_ms": round(latency, 1), "recommendations": payload}


# ---------- Observability (Day 4) ----------

@app.get("/telemetry/recent")
def recent_telemetry(limit: int = 20, db: Session = Depends(get_db)):
    """Inspect the query log directly — the point of logging every request
    is that it's actually reviewable, not just written and forgotten."""
    # OBSERVABILITY PRINCIPLE:
    # A log that can only be written to and never queried isn't
    # observability, it's just storage. Exposing the log directly is what
    # turns every entry logged elsewhere in this file into something an
    # engineer can actually act on.
    import models as m
    rows = db.query(m.QueryLog).order_by(m.QueryLog.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "query": r.query_text,
            "path": r.path,
            "reason": r.reason,
            "confidence": r.confidence,
            "latency_ms": round(r.latency_ms, 1) if r.latency_ms else None,
            "result_count": r.result_count,
            "success": r.success,
            "error": r.error,
        }
        for r in rows
    ]
