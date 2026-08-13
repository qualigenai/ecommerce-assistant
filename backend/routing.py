import re
from typing import Any, Dict, Optional

# Known catalog categories — kept in sync manually with seed_data.py for this
# practice project; in production this would be queried from the catalog
# itself rather than hardcoded.
CATEGORIES = [
    "Hiking Boots", "Backpacks", "Tents", "Jackets", "Sleeping Bags",
    "Camp Stoves", "Water Bottles", "Headlamps", "Gloves", "Socks",
    "Trekking Poles",
]

PRICE_UNDER_RE = re.compile(
    r"under\s*\$?(\d+(?:\.\d+)?)|less than\s*\$?(\d+(?:\.\d+)?)|below\s*\$?(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
PRICE_OVER_RE = re.compile(
    r"over\s*\$?(\d+(?:\.\d+)?)|more than\s*\$?(\d+(?:\.\d+)?)|above\s*\$?(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _match_category(query: str) -> Optional[str]:
    q = query.lower()
    for cat in CATEGORIES:
        if cat.lower() in q or cat.lower().rstrip("s") in q:
            return cat
    return None


def _match_price_lt(query: str) -> Optional[float]:
    m = PRICE_UNDER_RE.search(query)
    if m:
        return float(next(g for g in m.groups() if g))
    return None


def _match_price_gt(query: str) -> Optional[float]:
    m = PRICE_OVER_RE.search(query)
    if m:
        return float(next(g for g in m.groups() if g))
    return None


def _match_waterproof(query: str) -> Optional[bool]:
    return True if "waterproof" in query.lower() else None


def route_query(query: str) -> Dict[str, Any]:
    """
    Decide whether a query can be answered on the fast, free structured-
    filter path, or needs to fall through to the AI path (semantic search +
    agent).

    No AI model is called to make this decision — it's a plain rule-based
    heuristic. That's itself part of the cost-effective design: even the
    routing decision doesn't cost anything.

    Returns path, filters, a human-readable reason (which signals drove the
    decision), and a confidence score. IMPORTANT: confidence here means
    confidence in the ROUTING decision itself (how cleanly the query matched
    known structured signals) — it is NOT a measure of answer quality or
    groundedness. Those are separate, tracked at the response stage, not
    the routing stage. Conflating the two would overstate what this number
    actually certifies.
    """
    category = _match_category(query)
    price_lt = _match_price_lt(query)
    price_gt = _match_price_gt(query)
    waterproof = _match_waterproof(query)

    extra_signals = [s for s in (price_lt, price_gt, waterproof) if s is not None]

    if category and extra_signals:
        # Base confidence for having a category match at all, plus a bump
        # per additional structured signal (price bound, known attribute),
        # capped at 1.0. Three extra signals is effectively a fully
        # unambiguous, filterable query.
        confidence = round(min(1.0, 0.5 + 0.2 * len(extra_signals)), 2)

        matched = [f"category='{category}'"]
        if price_lt is not None:
            matched.append(f"price_lt={price_lt}")
        if price_gt is not None:
            matched.append(f"price_gt={price_gt}")
        if waterproof is not None:
            matched.append("waterproof=true")

        return {
            "path": "filter",
            "filters": {
                "category": category,
                "price_lt": price_lt,
                "price_gt": price_gt,
                "waterproof": waterproof,
            },
            "reason": "Matched structured signals: " + ", ".join(matched)
            + " -> routed to the fast filter path.",
            "confidence": confidence,
        }

    if category and not extra_signals:
        # A category alone is a weak, ambiguous signal — routing to AI is
        # the safer choice, but this is worth flagging as a borderline case
        # rather than pretending it's a clean AI-path query.
        return {
            "path": "ai",
            "filters": None,
            "reason": (
                f"Category '{category}' matched, but no price range or known "
                "attribute keyword was found alongside it — not enough "
                "structured signal for the fast path alone."
            ),
            "confidence": 0.5,
        }

    return {
        "path": "ai",
        "filters": None,
        "reason": (
            "No known category, price pattern, or attribute keyword "
            "detected — this query needs semantic understanding, not "
            "structured filtering."
        ),
        "confidence": 1.0,
    }
