from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String
from sqlalchemy.sql import func

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


class QueryLog(Base):
    """Observability trace for every routed query — the append-only log
    described in the trust & reliability framework. Not a full telemetry
    vault, but the schema is deliberately simple enough to query directly
    or graduate to something heavier later without a rewrite."""

    __tablename__ = "query_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    query_text = Column(String)
    path = Column(String, index=True)  # "filter" or "ai"
    reason = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    latency_ms = Column(Float)
    result_count = Column(Integer)
    success = Column(Boolean, default=True)
    error = Column(String, nullable=True)
