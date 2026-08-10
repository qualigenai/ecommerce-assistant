from typing import Any, Dict

from pydantic import BaseModel


class ProductBase(BaseModel):
    sku: str
    name: str
    description: str
    category: str
    price: float
    stock: int
    attributes: Dict[str, Any] = {}


class ProductCreate(ProductBase):
    pass


class ProductOut(ProductBase):
    id: int

    class Config:
        from_attributes = True
