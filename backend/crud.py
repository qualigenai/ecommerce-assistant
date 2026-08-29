from typing import Optional

from sqlalchemy.orm import Session

import models
import schemas


def create_product(db: Session, product: schemas.ProductCreate) -> models.Product:
    db_product = models.Product(**product.model_dump())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


def get_product(db: Session, product_id: int) -> Optional[models.Product]:
    return db.query(models.Product).filter(models.Product.id == product_id).first()


def get_products(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Product).offset(skip).limit(limit).all()


def update_product(db: Session, product_id: int, product: schemas.ProductCreate):
    db_product = get_product(db, product_id)
    if not db_product:
        return None
    for key, value in product.model_dump().items():
        setattr(db_product, key, value)
    db.commit()
    db.refresh(db_product)
    return db_product


def delete_product(db: Session, product_id: int) -> bool:
    db_product = get_product(db, product_id)
    if not db_product:
        return False
    db.delete(db_product)
    db.commit()
    return True


def search_products(
    db: Session,
    category: Optional[str] = None,
    price_lt: Optional[float] = None,
    price_gt: Optional[float] = None,
    waterproof: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
):
    """
    The FAST PATH: pure SQL filtering, no AI involved. This is the endpoint
    that should handle the majority of queries — near-instant, zero marginal
    cost per query.
    """
    query = db.query(models.Product)

    if category:
        query = query.filter(models.Product.category.ilike(f"%{category}%"))
    if price_lt is not None:
        query = query.filter(models.Product.price < price_lt)
    if price_gt is not None:
        query = query.filter(models.Product.price > price_gt)

    results = query.offset(skip).limit(limit).all()

    # attributes is a JSON column — filter in Python for portability across
    # SQLite versions rather than relying on SQLite's JSON1 extension syntax
    if waterproof is not None:
        results = [p for p in results if p.attributes.get("waterproof") == waterproof]

    return results


def get_fallback_recommendations(db: Session, product: models.Product, limit: int = 5):
    """
    TRUST PRINCIPLE: Reliability

    Business Purpose:
        Ensure a product detail page always has something useful to show,
        even for a brand-new product that hasn't been through /reindex yet
        (the cold-start case).

    Design Decision:
        Rules-based fallback: same category, ordered by closeness in price
        to the source product. No AI or embeddings involved — this path
        exists specifically for when the embedding path isn't available.

    Benefits:
        - Zero dependency on the vector index being current
        - Deterministic and instantly explainable ("same category, similar
          price") — no similarity score to justify
        - Near-zero cost, same as the Day 3 structured filter path

    Failure Strategy:
        Returns an empty list (not an error) when no other products exist
        in the same category — a genuinely correct answer, not a failure.
        The caller (main.py) is responsible for distinguishing "product
        doesn't exist at all" from "product exists but has no fallback
        candidates" before calling this function.

    Future Validation:
        Compare fallback-driven conversion rate against embedding-driven
        conversion rate — if fallback consistently underperforms, that's
        a signal to re-index more frequently rather than change this logic.
    """
    candidates = (
        db.query(models.Product)
        .filter(models.Product.category == product.category, models.Product.id != product.id)
        .all()
    )
    candidates.sort(key=lambda p: abs(p.price - product.price))
    return candidates[:limit]
