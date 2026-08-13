import os
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "products"
VECTOR_SIZE = 384  # output dimension of all-MiniLM-L6-v2

client = QdrantClient(url=QDRANT_URL)


def ensure_collection():
    # TRUST PRINCIPLE: Reliability
    # Idempotent by design — safe to call before every operation without
    # risking a duplicate-collection error or a crash if Qdrant was
    # restarted since the last check. Callers never need to know or care
    # whether the collection already existed.
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def upsert_products(products, embed_fn) -> int:
    """Embed each product's name + description + category, and store the
    vector in Qdrant alongside the catalog data needed to render a result
    without a second database lookup."""
    ensure_collection()

    texts = [f"{p.name}. {p.description} Category: {p.category}." for p in products]
    vectors = embed_fn(texts)

    points = [
        PointStruct(
            id=p.id,
            vector=vec,
            # GOVERNANCE PRINCIPLE:
            # The full catalog record travels with the vector, not just an
            # ID. Every vector result is self-describing and traceable back
            # to a real product without a second lookup — nothing returned
            # to a caller is ever an opaque ID they have to trust blindly.
            payload={
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "price": p.price,
                "stock": p.stock,
                "attributes": p.attributes,
            },
        )
        for p, vec in zip(products, vectors)
    ]
    # TRUST PRINCIPLE: Reliability
    # Qdrant's upsert is idempotent on point ID — re-running /reindex after
    # a catalog change overwrites existing vectors rather than duplicating
    # them, so reindexing is always safe to repeat.
    client.upsert(collection_name=COLLECTION_NAME, points=points)
    return len(points)


def semantic_search(query_vector: List[float], limit: int = 5):
    ensure_collection()
    return client.search(collection_name=COLLECTION_NAME, query_vector=query_vector, limit=limit)


def recommend_similar(product_id: int, limit: int = 5):
    """
    TRUST PRINCIPLE: Reliability

    Business Purpose:
        Generate "related products" recommendations for a product
        detail page.

    Design Decision:
        Reuse the existing Qdrant search index instead of building and
        maintaining a separate, dedicated recommendation index.

    Benefits:
        - Single source of semantic truth
        - Consistent recommendation and search behavior
        - Reduced infrastructure duplication and no index-sync risk

    Failure Strategy:
        Return None (not an empty list) when a product isn't indexed,
        so the caller can distinguish "genuinely has no related
        products" from "not indexed yet" — see the cold-start handling
        in main.py's get_recommendations().

    Future Validation:
        Click-through rate (CTR)
        Recommendation acceptance rate
        Add-to-cart conversion rate

    See also: docs/trust-and-reliability-framework.md
    """
    ensure_collection()

    points = client.retrieve(collection_name=COLLECTION_NAME, ids=[product_id], with_vectors=True)
    if not points:
        return None

    vector = points[0].vector
    # Ask for one extra, since the product itself is almost always the
    # single closest match to its own vector and needs to be filtered out.
    results = client.search(collection_name=COLLECTION_NAME, query_vector=vector, limit=limit + 1)
    return [r for r in results if r.id != product_id][:limit]
