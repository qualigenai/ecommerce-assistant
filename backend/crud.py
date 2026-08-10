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
