from sqlalchemy import Column, Integer, String, Float, JSON

from database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, unique=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    category = Column(String, index=True)
    price = Column(Float, index=True)
    stock = Column(Integer, default=0)
    # Structured attributes (e.g. {"waterproof": true, "color": "brown"}) —
    # this is what makes the fast filter path possible, rather than relying
    # on parsing free-text descriptions.
    attributes = Column(JSON, default={})
