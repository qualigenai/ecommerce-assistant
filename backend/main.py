import os
from typing import List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

import crud
import schemas
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


# ---------- Structured filter search — THE FAST PATH (Day 3) ----------
# No AI involved. Handles any query that maps cleanly to known attributes.

@app.get("/search", response_model=List[schemas.ProductOut])
def search(
    category: Optional[str] = None,
    price_lt: Optional[float] = None,
    price_gt: Optional[float] = None,
    waterproof: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    return crud.search_products(
        db, category=category, price_lt=price_lt, price_gt=price_gt, waterproof=waterproof
    )
