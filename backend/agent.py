import json
import os
from typing import Any, Dict, List

import httpx
from sqlalchemy.orm import Session

import crud
import embeddings
import models
import schemas
import vector_store

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = "llama3.2:latest"

# TRUST PRINCIPLE: Governance
#
# Business Purpose:
#     Prevent the agent from inventing products, prices, or stock levels
#     that were never returned by a real catalog lookup.
#
# Design Decision:
#     The system prompt explicitly forbids answering from the model's own
#     "knowledge" of the catalog — it has none, and is told so — and
#     requires every product claim to come from a tool call result.
#
# Benefits:
#     - Directly closes the hallucination risk this whole hybrid
#       architecture exists to manage
#     - The rule is enforced at the prompt level, not just hoped for
#
# Failure Strategy:
#     This is a soft constraint, not a hard one — a small local model can
#     still ignore the instruction. Day 9's groundedness check (verifying
#     referenced product IDs actually exist in the catalog) is the hard
#     enforcement layer this prompt rule is a first line of defense for,
#     not a substitute for.
#
# Future Validation:
#     Groundedness rate — % of agent responses whose product references
#     are verifiably present in a preceding tool result (Day 9)
SYSTEM_PROMPT = (
    "You are a helpful shopping assistant for an outdoor retail store. "
    "You do not know what products are in the catalog from memory — you "
    "must use the search_products tool to look up real products before "
    "answering any question about what's available, in stock, or priced "
    "at a given amount. Never invent a product name, price, or stock "
    "level. If the tool returns no results, say so honestly rather than "
    "guessing. "
    "When the customer says 'under $X', 'less than $X', or 'below $X', "
    "use price_lt=X. When they say 'over $X', 'more than $X', or "
    "'above $X', use price_gt=X. Do not confuse these two directions. "
    "Only include a parameter if the customer actually mentioned it. Do "
    "not guess or assume a value (e.g. waterproof=true/false) for any "
    "attribute the customer did not bring up — omit that parameter "
    "entirely rather than inventing a value for it. "
    "Use check_stock to confirm real-time availability before telling a "
    "customer something is in stock. "
    "When the customer explicitly asks you to add a product to their "
    "cart, that request is already confirmation to perform the "
    "add-to-cart action — do not ask them to confirm again. "
    "If the customer names a product but you do not yet know its "
    "numeric product_id, first call search_products. After "
    "search_products returns the matching product, use the returned "
    "product_id in add_to_cart. For example, 'find the Trailhead "
    "Waterproof Hiking Boot and add 1 to my cart' means: (1) call "
    "search_products for the Trailhead Waterproof Hiking Boot, (2) take "
    "the matching product_id from the result, (3) call add_to_cart with "
    "that product_id and quantity=1, (4) report the result honestly. "
    "The product_id you pass to add_to_cart must be the actual numeric "
    "id field from a search_products or check_stock result — never a "
    "tool name, the word 'null', a made-up number, or any other "
    "placeholder. If you do not have a real numeric id yet, call "
    "search_products first and wait for its result before calling "
    "add_to_cart. If "
    "the customer only asks you to find or search for a product, with "
    "no request to add it, do not call add_to_cart — searching and "
    "adding are separate actions. "
    "Use order_status only when the customer provides an order ID; if "
    "the tool reports the order was not found, say so honestly — never "
    "invent an order status, tracking number, or delivery date."
    # BUG-003 mitigation (price direction) and BUG-005 mitigation
    # (fabricated/unrequested parameter values) — see docs/bug-log.md.
    # Neither is a hard guarantee; both reduce, not eliminate, the
    # underlying model behavior.
    #
    # BUG-007 experiment (Day 8): removed the "confirmed... explicit
    # confirmation" phrasing, which live testing suggested a small model
    # was reading as "ask before adding" rather than "don't guess when
    # unconfirmed." Added explicit search-then-act chaining instructions
    # with a worked example, since neither tool description previously
    # stated that search_products' result feeds into add_to_cart. This
    # is a single controlled variable change — no code/architecture
    # touched — to isolate whether the ambiguity was prompt-level.
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search the outdoor retail product catalog. Use category/price/"
                "waterproof for specific, filterable requests. Use query for "
                "vague, descriptive, or comparative requests where the customer "
                "hasn't named an exact category or spec."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "e.g. 'Hiking Boots', 'Tents'"},
                    "price_lt": {
                        "type": "number",
                        "description": "Maximum price. Use for 'under $X', 'less than $X', 'below $X'. Example: 'under $100' means price_lt=100.",
                    },
                    "price_gt": {
                        "type": "number",
                        "description": "Minimum price. Use for 'over $X', 'more than $X', 'above $X'. Example: 'over $100' means price_gt=100.",
                    },
                    "waterproof": {
                        "type": "boolean",
                        "description": "Only set this if the customer explicitly asked about waterproofing. Omit it entirely otherwise — do not guess.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Free-text description for semantic search, used when structured filters aren't enough",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "Check real-time stock for a specific product the customer named.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name_or_sku": {
                        "type": "string",
                        "description": "The product's name or SKU, as the customer referred to it, e.g. 'Trailhead Waterproof Hiking Boot' or 'BOOT-001'",
                    },
                },
                "required": ["product_name_or_sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": (
                "Add a specific product to the customer's cart. Call this "
                "tool when the customer has explicitly requested that a "
                "specific product be added to their cart and has provided "
                "a quantity (or clearly implies quantity=1). If the "
                "customer named the product but you don't yet know its "
                "numeric product_id, first call search_products to find "
                "it, then call this tool with the returned id. Do not "
                "call this tool when the customer only asks to find, "
                "search for, or view a product."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "The numeric product ID, from a prior search_products or check_stock result"},
                    "quantity": {"type": "integer", "description": "How many units, defaults to 1"},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "order_status",
            "description": "Look up the status of an existing order by order ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID, e.g. 'ORD-1001'"},
                },
                "required": ["order_id"],
            },
        },
    },
]


def _call_ollama(messages: List[Dict[str, Any]], use_tools: bool = True) -> Dict[str, Any]:
    payload = {"model": MODEL, "messages": messages, "stream": False}
    if use_tools:
        payload["tools"] = TOOLS
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def _coerce_float(value: Any) -> Any:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes"):
            return True
        if v in ("false", "0", "no"):
            return False
    return None


# BUG-006 fix — see docs/bug-log.md.
#
# TRUST PRINCIPLE: Governance
#
# Business Purpose:
#     Make result_count mean the same thing everywhere: the number of
#     genuine business objects returned, never the number of list items
#     (which could include an error object) or the number of tool calls.
#
# Design Decision:
#     Every _tool_* function now returns this exact shape instead of a
#     bare list. `success` reflects whether the action/lookup completed
#     without an error condition; `results` holds only genuine business
#     objects (empty on any failure); `error` is a human-readable reason,
#     present only when success is False.
#
# Benefits:
#     - result_count = len(results) is now unambiguous for every tool,
#       including add_to_cart and order_status, which previously wrapped
#       failures in a single-item list and were always counted as "1"
#     - success is now tracked per tool call, not just per chat turn
#
# Failure Strategy:
#     A lookup that legitimately finds nothing (e.g. search_products with
#     no matches) is success=True with empty results — that's a correct
#     answer, not a failure. Only genuine error conditions (invalid input,
#     product doesn't exist, insufficient stock, order not found) set
#     success=False.
#
# Future Validation:
#     Per-tool success rate over time — a tool with a persistently low
#     success rate signals either a UX problem (customers asking for
#     things that don't exist) or a tool-design problem worth revisiting.
def _tool_result(success: bool, results: List[Dict[str, Any]] = None, error: str = None) -> Dict[str, Any]:
    return {"success": success, "results": results or [], "error": error}


# TRUST PRINCIPLE: Reliability
#
# Business Purpose:
#     Give the demo a working cart without building a real persistence
#     layer, order system, or auth — out of scope for this project.
#
# Design Decision:
#     A single in-memory cart (module-level list) and a small, fixed set
#     of mock orders. Both are honestly bounded: add_to_cart checks real
#     stock before confirming, and order_status returns "not found" for
#     any ID outside the fixed mock set rather than fabricating a
#     plausible-looking status for it.
#
# Benefits:
#     - The agent never lies about order data it doesn't actually have,
#       even though the "backend" behind it is mocked
#     - Demonstrates the tool-call pattern a real cart/order system would
#       plug into later, without needing to build one now
#
# Failure Strategy:
#     The cart resets on every backend restart — acceptable for a demo,
#     called out explicitly here so it's never mistaken for a real
#     persistence guarantee.
#
# Future Validation:
#     Replace with a real Cart/Order table and this becomes a live
#     integration test target with no change to the tool schema.
_MOCK_CART: List[Dict[str, Any]] = []

_MOCK_ORDERS = {
    "ORD-1001": {"status": "Shipped", "eta": "2 business days"},
    "ORD-1002": {"status": "Processing", "eta": "4-6 business days"},
}


# BUG-009 fix — see docs/bug-log.md.
#
# TRUST PRINCIPLE: Reliability
#
# Business Purpose:
#     Make search_products behave correctly when the model sends a real
#     query alongside placeholder or partial filter values, instead of
#     letting a stray 0 or "" silently override a perfectly good query.
#
# Design Decision:
#     Two-part fix, not one:
#     1. Normalize placeholder values BEFORE deciding anything: empty
#        string category becomes None, non-positive price bounds become
#        None (no product in this catalog costs $0 or less, so a price
#        bound of exactly 0 is never a meaningful constraint — it's the
#        model filling in a blank, not a real customer request).
#     2. Define the routing contract explicitly, since normalization alone
#        doesn't answer "what if a real filter AND a real query are both
#        present at once": if query is present, semantic search runs
#        first and any remaining real filters are applied as a POST-filter
#        on top of it — combining relevance with precision — rather than
#        the old either/or split where any non-None filter silently
#        discarded the query entirely.
#
# Benefits:
#     - Closes the exact failure: query="Trailhead Waterproof Hiking Boot"
#       + waterproof=true (a real, legitimate filter here) now correctly
#       finds the product, instead of price_lt=0/price_gt=0 placeholders
#       forcing an impossible structured-only search
#     - Generalizes correctly: a genuinely combined request like "show me
#       waterproof jackets under $150" (real category + real price + real
#       intent) now also benefits from semantic relevance ranking, not
#       just blunt SQL filtering
#
# Failure Strategy:
#     If query and every filter normalize away to nothing, returns an
#     honest empty result rather than guessing.
#
# Future Validation:
#     Compare result relevance between the old filter-only path and this
#     hybrid path on the same queries — the hybrid path should never be
#     worse, since it's a strict narrowing of already-relevant results.
# BUG-010 fix — see docs/bug-log.md.
#
# TRUST PRINCIPLE: Reliability
#
# Business Purpose:
#     Stop a hallucinated category (one that doesn't exist in the real
#     catalog) from silently steering a search down the wrong path and
#     discarding a query that would have found the right product.
#
# Design Decision:
#     Query the database directly for the real, current set of distinct
#     categories, rather than maintaining a separate hardcoded list.
#     routing.py's own CATEGORIES list already carries a documented
#     comment acknowledging this exact staleness risk ("in production
#     this would be queried from the catalog itself") — this fix takes
#     that path instead of duplicating the same technical debt here.
#
# Benefits:
#     - Closes BUG-010: "Camping Gear" (a category that has never
#       existed in this catalog) is no longer trusted just because it's
#       a non-empty string — it's checked against what's actually there.
#     - Case-insensitive matching absorbs small model casing variance
#       ("hiking boots" vs "Hiking Boots") without over- or under-
#       matching against real categories.
#     - Single source of truth — this can never drift out of sync with
#       the catalog the way a second hardcoded list could.
#
# Failure Strategy:
#     An unrecognized category is normalized to None, not rejected with
#     an error — it falls through to the same query/filter-only gates
#     _tool_search_products already has for a genuinely absent category,
#     so a hallucinated category degrades gracefully into "search by
#     meaning instead," not a hard failure.
#
# Future Validation:
#     Track how often a supplied category fails validation — a
#     persistently high rate would suggest the model needs a stricter
#     category enum in the tool schema itself, not just correction here.
def _get_known_categories(db: Session) -> set:
    rows = db.query(models.Product.category).distinct().all()
    return {r[0] for r in rows if r[0]}


def _tool_search_products(arguments: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    BUG-009 fix — see docs/bug-log.md.

    TRUST PRINCIPLE: Reliability

    Business Purpose:
        Make sure a specifically-named product is actually found, even
        when the model pads its tool call with placeholder defaults.

    Design Decision:
        Two changes, applied together:
        (1) Normalize placeholders before any decision is made — an
            empty-string category, or a price bound of 0 or less, is
            treated as "not specified," not as a real constraint (no
            product in this catalog costs $0 or less, so a price bound
            of exactly 0 can never be a meaningful customer request).
        (2) Gate the structured-filter path on `category` specifically,
            not on "any filter is present." This mirrors the same
            principle routing.py already applies at the Day 4 routing
            layer: a category is a strong, unambiguous signal; a bare
            price or waterproof flag with no category is not enough on
            its own to justify skipping semantic understanding.

    Benefits:
        - Closes BUG-009: a real product search no longer fails with a
          self-contradictory price_lt=0 AND price_gt=0 filter just
          because the model sent zeros it didn't mean.
        - waterproof=True is deliberately KEPT, not normalized away —
          unlike a placeholder zero, a customer saying "waterproof
          hiking boot" is real signal, and BUG-005's fix already covers
          the case where the model invents an unrequested value.

    Failure Strategy:
        With no category and no query, falls back to filter-only search
        using whatever real price/waterproof constraints remain after
        normalization — an empty answer here is a legitimate outcome,
        not an error, since the model gave us nothing usable to search.

    Future Validation:
        KNOWN LIMITATION, tracked separately, not fixed here: when the
        semantic path is taken, waterproof/price are not applied as a
        filter on top of the embedding results — see "Known limitations"
        at the end of the bug log. Deliberately out of scope for this fix.
    """
    category = arguments.get("category")
    if isinstance(category, str) and category.strip() == "":
        category = None

    # BUG-010: a non-empty category isn't necessarily a REAL one — the
    # model can hallucinate a category that has never existed in this
    # catalog (e.g. "Camping Gear"). Validate against the actual
    # distinct categories in the database before trusting it as a gate.
    if category is not None:
        known = _get_known_categories(db)
        match = next((c for c in known if c.lower() == category.strip().lower()), None)
        category = match  # None if no real category matched

    price_lt = _coerce_float(arguments.get("price_lt"))
    if price_lt is not None and price_lt <= 0:
        price_lt = None
    price_gt = _coerce_float(arguments.get("price_gt"))
    if price_gt is not None and price_gt <= 0:
        price_gt = None

    waterproof = _coerce_bool(arguments.get("waterproof"))

    query = arguments.get("query")
    if isinstance(query, str) and query.strip() == "":
        query = None

    # Gate 1: a real category always means the structured filter path.
    if category is not None:
        results = crud.search_products(
            db, category=category, price_lt=price_lt, price_gt=price_gt, waterproof=waterproof,
        )
        return _tool_result(True, [schemas.ProductOut.model_validate(p).model_dump() for p in results])

    # Gate 2: no category, but a real query -> semantic search.
    if query:
        vector = embeddings.embed_text(query)
        vresults = vector_store.semantic_search(vector, limit=5)
        return _tool_result(True, [r.payload for r in vresults])

    # Gate 3: no category, no query -> filter-only search on whatever
    # price/waterproof constraints survived normalization.
    if price_lt is not None or price_gt is not None or waterproof is not None:
        results = crud.search_products(
            db, category=None, price_lt=price_lt, price_gt=price_gt, waterproof=waterproof,
        )
        return _tool_result(True, [schemas.ProductOut.model_validate(p).model_dump() for p in results])

    # Nothing usable at all — a legitimate empty answer, not an error.
    return _tool_result(True, [])


def _tool_check_stock(arguments: Dict[str, Any], db: Session) -> Dict[str, Any]:
    term = (arguments.get("product_name_or_sku") or "").strip()
    if not term:
        return _tool_result(False, [], error="No product name or SKU provided")
    product = db.query(models.Product).filter(models.Product.sku == term).first()
    if not product:
        product = db.query(models.Product).filter(models.Product.name.ilike(f"%{term}%")).first()
    if not product:
        # A lookup that legitimately found no match — not a system error.
        return _tool_result(True, [])
    return _tool_result(True, [{
        "id": product.id, "sku": product.sku, "name": product.name,
        "stock": product.stock, "price": product.price,
    }])


def _tool_add_to_cart(arguments: Dict[str, Any], db: Session) -> Dict[str, Any]:
    product_id = arguments.get("product_id")
    quantity = int(_coerce_float(arguments.get("quantity")) or 1)

    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return _tool_result(False, [], error=f"Invalid product_id: {product_id!r}")

    product = crud.get_product(db, product_id)
    if not product:
        return _tool_result(False, [], error=f"No product with id {product_id}")
    if product.stock < quantity:
        return _tool_result(
            False, [],
            error=f"Insufficient stock for {product.name}: requested {quantity}, available {product.stock}",
        )

    _MOCK_CART.append({"product_id": product_id, "name": product.name, "quantity": quantity})
    return _tool_result(True, [{
        "status": "added", "product": product.name, "quantity": quantity,
        "cart_size": len(_MOCK_CART), "mock_data": True,
    }])


def _tool_order_status(arguments: Dict[str, Any]) -> Dict[str, Any]:
    order_id = (arguments.get("order_id") or "").strip()
    order = _MOCK_ORDERS.get(order_id)
    if not order:
        return _tool_result(False, [], error=f"No order found with id {order_id}")
    return _tool_result(True, [{"order_id": order_id, **order, "mock_data": True}])


def _execute_tool(name: str, arguments: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    BUG-001 fix — see docs/bug-log.md for full detail.

    TRUST PRINCIPLE: Reliability

    Business Purpose:
        Ensure the agent's tool calls actually filter correctly, every
        time, regardless of what shape the model returns its arguments in.

    Design Decision:
        Explicitly coerce every argument to its real Python type
        (float for prices, bool for waterproof) before it ever reaches
        crud.search_products(), instead of passing the model's raw JSON
        straight through. Generalized into a dispatcher so every tool
        goes through the same discipline, not just search_products.

    Benefits:
        - Closes a real, confirmed bug: small local models via Ollama
          frequently return tool arguments as strings ("true", "100")
          even when the schema declares number/boolean. Passing "true"
          through uncoerced meant `attributes.get("waterproof") == "true"`
          was comparing a real bool to a string and was ALWAYS False —
          silently zeroing out every waterproof-filtered search.
        - The fix defends against the LLM's output shape, not just its
          content — never trust an external system's types without
          checking them, and a model's tool-call arguments are exactly
          that: external, untrusted input.

    Failure Strategy:
        If a value can't be coerced (garbage input), it becomes None and
        is simply not applied as a filter, rather than raising or silently
        matching nothing. An unrecognized tool name returns a failed
        _tool_result() rather than raising, so one bad tool call can't
        crash the whole agent turn.

    Future Validation:
        Track how often coercion actually changes a value (i.e. the model
        sent a string instead of the native type) — a high rate is a
        signal to reconsider tool-calling reliability at this model size.
    """
    if name == "search_products":
        return _tool_search_products(arguments, db)
    if name == "check_stock":
        return _tool_check_stock(arguments, db)
    if name == "add_to_cart":
        return _tool_add_to_cart(arguments, db)
    if name == "order_status":
        return _tool_order_status(arguments)
    return _tool_result(False, [], error=f"Unknown tool: {name}")


# BUG-007 fix — see docs/bug-log.md.
#
# TRUST PRINCIPLE: Reliability
#
# Business Purpose:
#     Let the agent actually complete requests like "add the Trailhead
#     boot to my cart" in one turn, without fabricating a product ID it
#     was never given.
#
# Design Decision:
#     A bounded loop (max MAX_TOOL_ITERATIONS rounds) instead of a fixed
#     "one tool round, then one final answer" sequence. Each round, tools
#     stay enabled — so the model can call search_products, see the real
#     product_id in the result, and call add_to_cart with it in the next
#     round, all within a single customer turn.
#
# Benefits:
#     - Closes BUG-007: the model no longer has to guess an ID it was
#       never given — it can look one up first
#     - The loop naturally handles both the simple case (one tool call,
#       done) and the compound case (search, then act) with the same code
#
# Failure Strategy:
#     Bounded at MAX_TOOL_ITERATIONS specifically to prevent an unbounded
#     tool-calling loop — if the model still wants to call a tool after
#     the cap, the final round forces a plain-text answer with tools
#     disabled, so the turn always terminates.
#
# Future Validation:
#     KNOWN TRADE-OFF, tracked against BUG-004: each additional round is
#     another full model inference pass on CPU-only hardware. This fix
#     very likely makes BUG-004's latency numbers worse for compound
#     requests, not better — worth re-measuring specifically (not just
#     assuming) once this is live, and factoring into whatever decision
#     closes BUG-004.
MAX_TOOL_ITERATIONS = 4

# BUG-011 fix — see docs/bug-log.md.
#
# TRUST PRINCIPLE: Governance
#
# Business Purpose:
#     Guarantee that a customer never receives a claim that a
#     transactional action (add to cart, and any future action tool)
#     succeeded unless the trace proves it actually ran and succeeded.
#
# Design Decision:
#     A table-driven registry, not a hardcoded string check bolted onto
#     main.py. Each transactional tool lists the phrases that indicate a
#     COMPLETED claim (past tense — "I have added", "cart now contains")
#     as opposed to an OFFER or QUESTION ("would you like to add..."),
#     which must never trigger this guard. Adding a future transactional
#     tool (remove_from_cart, place_order, ...) means adding one entry
#     here — no new branching logic anywhere else.
#
# Benefits:
#     - Closes BUG-011 deterministically: even if the model fabricates a
#       completion claim again, the application will not let it reach
#       the customer unmodified
#     - Extensible by design — verified requirement, not an afterthought
#     - The fallback preserves what actually happened (what was found)
#       rather than collapsing to a generic "something went wrong,"
#       keeping the finding-vs-changing-state distinction visible to
#       the customer
#
# Failure Strategy:
#     This is keyword-based, not true language understanding — it is a
#     containment layer, not a substitute for the model behaving
#     correctly. It can in principle miss a completion phrase we didn't
#     anticipate, or (rarely) misfire on unusual phrasing. That
#     limitation is accepted deliberately: a keyword guard that catches
#     the real, observed failure case is a large improvement over no
#     guard at all, even though it is not a perfect one.
#
# Future Validation:
#     Track how often this guard actually fires in production — a
#     nonzero rate confirms the model continues to fabricate completions
#     periodically, which is itself useful evidence for whether a larger
#     model or a different chaining strategy is eventually warranted.
TRANSACTIONAL_TOOLS = {
    "add_to_cart": {
        "keywords": [
            "i have added", "i've added", "i added",
            "successfully added", "added it to your cart",
            "added to your cart", "cart now contains",
            "has been added to your cart", "was added to your cart",
            "i will add", "i'll add",
        ],
        "action_description": "added to your cart",
    },
}


def _reply_claims_unverified_transaction(reply: str, trace: List[Dict[str, Any]]) -> str:
    """Returns the tool name if the reply claims a transactional
    completion with no matching successful trace entry, else None."""
    reply_lower = reply.lower()
    for tool_name, config in TRANSACTIONAL_TOOLS.items():
        if any(kw in reply_lower for kw in config["keywords"]):
            verified = any(t["tool"] == tool_name and t["success"] for t in trace)
            if not verified:
                return tool_name
    return None


def _build_grounding_fallback(tool_name: str, trace: List[Dict[str, Any]]) -> str:
    """Builds an honest fallback that preserves what was actually found,
    distinguishing 'I found it' from 'I changed something' — the exact
    reliability boundary this fix exists to make visible."""
    config = TRANSACTIONAL_TOOLS.get(tool_name, {})
    action_description = config.get("action_description", f"completed via {tool_name}")

    product_ref = None
    for entry in reversed(trace):
        if entry["tool"] in ("search_products", "check_stock") and entry["success"]:
            args = entry.get("arguments") or {}
            product_ref = args.get("query") or args.get("product_name_or_sku") or args.get("category")
            if product_ref:
                break

    if product_ref:
        return f"I found {product_ref}, but I couldn't confirm that it was {action_description}."
    return "I wasn't able to confirm that this action was completed successfully."


def _finalize_reply(reply: str, trace: List[Dict[str, Any]]) -> str:
    """Single choke point both return paths in run_agent() go through —
    guarantees the grounding guard can't be bypassed by adding a new
    return statement later without remembering to call it."""
    unverified_tool = _reply_claims_unverified_transaction(reply, trace)
    if unverified_tool:
        return _build_grounding_fallback(unverified_tool, trace)
    return reply


def run_agent(user_message: str, db: Session) -> Dict[str, Any]:
    """
    Multi-round agent: the model can chain multiple tool calls within one
    customer turn (e.g. search_products -> add_to_cart), not just one.

    TRUST PRINCIPLE: Observability
    Every tool call across every round is captured in `trace` and
    returned alongside the reply — not just logged internally. A caller
    (or an engineer debugging a bad answer) can see exactly what was
    searched, what came back, and whether each step succeeded — not just
    the final text.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    trace = []
    for round_num in range(1, MAX_TOOL_ITERATIONS + 1):
        response = _call_ollama(messages, use_tools=True)
        msg = response["message"]
        tool_calls = msg.get("tool_calls") or []
        content = (msg.get("content") or "").strip()

        # BUG-011 INVESTIGATION (temporary, Day 8) — see docs/bug-log.md.
        # Diagnostic only, no behavior change: trace previously only
        # recorded EXECUTED tool calls, so a round where the model
        # returned plain text with no tool call was invisible. This is
        # exactly the gap that let a fabricated "I added it to your
        # cart" reach the customer without any record of what the model
        # actually decided that round. Printed to container stdout
        # (docker compose logs backend) rather than persisted, since
        # this is a one-time investigation, not the eventual
        # observability answer.
        print(
            f"[AGENT DEBUG] round={round_num} "
            f"content={content!r} "
            f"tool_calls={[tc['function']['name'] for tc in tool_calls]}",
            flush=True,
        )

        if not tool_calls:
            if content:
                # Model has what it needs and is ready to answer in plain text.
                return {"reply": _finalize_reply(content, trace), "tool_calls": trace}

            # BUG-008 fix — see docs/bug-log.md.
            #
            # TRUST PRINCIPLE: Reliability
            #
            # Business Purpose:
            #     Never let a blank response reach a customer.
            #
            # Design Decision:
            #     No tool call AND no text is not "the model is done" — it's
            #     an anomaly. Treating it as completion (the old behavior)
            #     silently produced an empty reply. Instead, nudge the model
            #     once and let it try again, consuming one of the existing
            #     bounded iterations rather than adding new unbounded retry
            #     logic.
            #
            # Benefits:
            #     - Gives the model one real chance to recover before giving
            #       up, without risking an infinite loop (still bounded by
            #       MAX_TOOL_ITERATIONS, unchanged)
            #     - Makes the anomaly visible in the message history sent to
            #       the model, rather than silently returning nothing
            #
            # Failure Strategy:
            #     If every remaining iteration still produces nothing, the
            #     loop falls through to the hard fallback below rather than
            #     looping forever or returning blank.
            #
            # Future Validation:
            #     Track how often this nudge path fires — a high rate would
            #     suggest the model needs a prompt-level fix (proposed, not
            #     applied yet per this round's scope), not just a retry.
            messages.append(msg)
            messages.append({
                "role": "user",
                "content": (
                    "You didn't call a tool or provide an answer. Please "
                    "either call the appropriate tool to look up real "
                    "information, or give the customer a plain-text answer."
                ),
            })
            continue

        messages.append(msg)
        for tc in tool_calls:
            name = tc["function"]["name"]
            arguments = tc["function"]["arguments"]
            result = _execute_tool(name, arguments, db)
            print(
                f"[AGENT DEBUG] round={round_num} executed tool={name} "
                f"args={arguments} success={result['success']} "
                f"result_count={len(result['results'])} error={result['error']!r}",
                flush=True,
            )
            trace.append({
                "tool": name, "arguments": arguments,
                "success": result["success"],
                "result_count": len(result["results"]),
                "error": result["error"],
            })
            messages.append({"role": "tool", "content": json.dumps(result)})

    # Hit the iteration cap while the model still wanted to call tools (or
    # kept returning nothing) — force a final plain-text answer so the turn
    # always terminates.
    final = _call_ollama(messages, use_tools=False)
    final_content = (final["message"].get("content") or "").strip()
    if final_content:
        return {"reply": _finalize_reply(final_content, trace), "tool_calls": trace}

    # BUG-008 hard fallback: even the forced final answer came back empty.
    # An honest, fixed message is the floor — a blank string must never be
    # what a customer sees.
    return {
        "reply": (
            "I wasn't able to process that request. Could you try "
            "rephrasing it, or asking in two separate steps?"
        ),
        "tool_calls": trace,
    }
