import json
import os
import time
from typing import Any, Dict, List

import httpx
from sqlalchemy.orm import Session

import conversation
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


# Day 11 (streaming) — see docs/bug-log.md.
#
# TRUST PRINCIPLE: Reliability
#
# Business Purpose:
#     Give BUG-004's actual bottleneck — the long final-answer generation
#     round, 27-44s measured live on Day 10 — a real fix: perceived
#     latency drops to time-to-first-token instead of time-to-full-reply,
#     without touching the model or hardware.
#
# Design Decision:
#     A thin generator over Ollama's NDJSON streaming protocol
#     (stream: true), yielding each raw chunk as-is. Deliberately kept
#     separate from _call_ollama() rather than adding a stream flag to
#     it — the two have different failure/timeout shapes (a stream can
#     legitimately take a while between chunks; a blocking call can't),
#     and keeping them separate means run_agent()'s existing,
#     trust-hardened non-streaming path is never touched by this change.
#
# Failure Strategy:
#     Any error here (connection drop mid-stream, malformed NDJSON line)
#     propagates to the caller as an exception — run_agent_stream()'s own
#     try/except at the endpoint level (main.py) is what converts that
#     into BUG-012's honest customer-facing fallback, same guarantee as
#     the non-streaming path, not a separate weaker one.
def _call_ollama_stream(messages: List[Dict[str, Any]], use_tools: bool = True):
    payload = {"model": MODEL, "messages": messages, "stream": True}
    if use_tools:
        payload["tools"] = TOOLS
    with httpx.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            yield json.loads(line)


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


# BUG-013 fix — see docs/bug-log.md.
#
# TRUST PRINCIPLE: Reliability
#
# Business Purpose:
#     Never let raw, malformed pseudo-tool-call JSON reach the customer
#     as if it were a real answer.
#
# Design Decision:
#     Reuses BUG-008's exact nudge-and-continue mechanism rather than
#     introducing new architecture. Content that looks like an attempted
#     tool call (contains a JSON-object shape mentioning "name" and
#     "parameters"/"arguments") is treated the same way as empty content
#     was already treated — not a valid final answer, so nudge and retry
#     within the existing bounded loop.
#
# BUG-014 fix (Day 14, live frontend testing) — see docs/bug-log.md.
#     The original version only checked whether the ENTIRE message
#     started with '{' — real live testing found the model writing a
#     sentence of plain English FIRST ("It seems like I need to search
#     for the product again..."), THEN the broken JSON tool-call
#     attempt. That content doesn't start with '{', so the old check
#     waved it straight through to the customer. Fixed by searching for
#     the JSON-object pattern anywhere in the content, via regex,
#     instead of requiring it at position zero.
#
# Benefits:
#     - Closes a real, observed failure: the model sometimes writes out
#       a tool call as text (sometimes pure JSON, sometimes prose
#       followed by JSON) instead of issuing a genuine tool call.
#       Previously this passed every check ("content is non-empty") and
#       went straight to the customer.
#     - The regex requires the JSON-object shape AND both "name" and a
#       parameters/arguments key together, to avoid false-positiving on
#       a legitimate answer that happens to mention JSON or braces for
#       unrelated reasons — a customer discussing a shopping assistant
#       essentially never legitimately produces this exact shape.
#
# Failure Strategy:
#     If the model keeps producing this pattern every round, the
#     existing MAX_TOOL_ITERATIONS cap and BUG-008 hard fallback still
#     guarantee the turn terminates with an honest message, never a
#     leaked JSON blob.
#
# Future Validation:
#     Track how often this specific path fires — a high rate would be
#     evidence the model needs a stronger structured-output constraint,
#     not just this containment layer.
def _looks_like_tool_call_json(content: str) -> bool:
    if "{" not in content:
        return False
    lowered = content.lower()
    return '"name"' in lowered and ("parameters" in lowered or "arguments" in lowered)


def run_agent(user_message: str, db: Session, session_id: str = None) -> Dict[str, Any]:
    """
    Multi-round agent: the model can chain multiple tool calls within one
    customer turn (e.g. search_products -> add_to_cart), not just one.

    Day 9: also carries conversation history across turns when a
    session_id is provided — see conversation.py for the full trust
    rationale. This is the deterministic-fallback resolution path
    BUG-007 concluded was the right answer, rather than continuing to
    demand perfect single-turn tool chaining from a 3B model.

    TRUST PRINCIPLE: Observability
    Every tool call across every round is captured in `trace` and
    returned alongside the reply — not just logged internally. A caller
    (or an engineer debugging a bad answer) can see exactly what was
    searched, what came back, and whether each step succeeded — not just
    the final text.
    """
    history = conversation.get_history(session_id) if session_id else []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
        {"role": "user", "content": user_message},
    ]

    def _save(reply: str):
        if session_id:
            conversation.set_history(session_id, messages[1:] + [{"role": "assistant", "content": reply}])

    # Day 10 (BUG-004 investigation) — see docs/bug-log.md.
    #
    # TRUST PRINCIPLE: Observability
    #
    # Business Purpose:
    #     BUG-004's latency numbers (8.1s, 26.8s, 128.4s) were never
    #     broken down by round or by model-vs-tool time, so there was no
    #     way to tell whether a slow request meant "many rounds," "one
    #     very slow inference call," or "cold-start" — the note next to
    #     the 128.4s figure explicitly says this was never confirmed.
    #
    # Design Decision:
    #     Time every model call and every tool execution individually,
    #     and return the breakdown alongside the existing reply/trace
    #     rather than only the one aggregate number /chat already logs.
    #
    # Benefits:
    #     - A single request now shows exactly how many inference passes
    #       it cost and how long each one took, real evidence instead of
    #       a guess about cold-start vs genuine multi-round cost
    #
    # Failure Strategy:
    #     Purely additive — reply/tool_calls keep their existing shape,
    #     nothing downstream breaks if it ignores the new keys.
    def _package(reply: str, trace: List[Dict[str, Any]], rounds: int, model_latency_ms: List[float]) -> Dict[str, Any]:
        return {
            "reply": reply,
            "tool_calls": trace,
            "rounds": rounds,
            "model_latency_ms": [round(ms, 1) for ms in model_latency_ms],
            "total_model_latency_ms": round(sum(model_latency_ms), 1),
        }

    trace = []
    model_latencies: List[float] = []
    for round_num in range(1, MAX_TOOL_ITERATIONS + 1):
        _t0 = time.monotonic()
        response = _call_ollama(messages, use_tools=True)
        model_latencies.append((time.monotonic() - _t0) * 1000)
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
            if content and not _looks_like_tool_call_json(content):
                # Model has what it needs and is ready to answer in plain text.
                final_reply = _finalize_reply(content, trace)
                _save(final_reply)
                return _package(final_reply, trace, round_num, model_latencies)

            # BUG-008 fix, extended by BUG-013 — see docs/bug-log.md.
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
                    "You didn't call a tool or provide an answer — or you "
                    "wrote out a tool call as text instead of actually "
                    "calling it. Please either use the actual tool-calling "
                    "mechanism to call a tool, or give the customer a "
                    "plain-text answer. Do not write JSON in your reply."
                ),
            })
            continue

        messages.append(msg)
        for tc in tool_calls:
            name = tc["function"]["name"]
            arguments = tc["function"]["arguments"]
            _tool_t0 = time.monotonic()
            result = _execute_tool(name, arguments, db)
            tool_latency_ms = (time.monotonic() - _tool_t0) * 1000
            print(
                f"[AGENT DEBUG] round={round_num} executed tool={name} "
                f"args={arguments} success={result['success']} "
                f"result_count={len(result['results'])} error={result['error']!r} "
                f"latency_ms={tool_latency_ms:.1f}",
                flush=True,
            )
            trace.append({
                "tool": name, "arguments": arguments,
                "success": result["success"],
                "result_count": len(result["results"]),
                "error": result["error"],
                "latency_ms": round(tool_latency_ms, 1),
                # Day 14 (UI) — see docs/bug-log.md. The actual product
                # data, not just a count — the frontend renders product
                # cards from THIS, never by parsing the natural-language
                # reply text, so a card can never show a price or image
                # the backend didn't actually return.
                "results": result["results"],
            })
            messages.append({"role": "tool", "content": json.dumps(result)})

    # Hit the iteration cap while the model still wanted to call tools (or
    # kept returning nothing) — force a final plain-text answer so the turn
    # always terminates.
    _final_t0 = time.monotonic()
    final = _call_ollama(messages, use_tools=False)
    model_latencies.append((time.monotonic() - _final_t0) * 1000)
    final_content = (final["message"].get("content") or "").strip()
    if final_content and not _looks_like_tool_call_json(final_content):
        final_reply = _finalize_reply(final_content, trace)
        _save(final_reply)
        return _package(final_reply, trace, MAX_TOOL_ITERATIONS, model_latencies)

    # BUG-008 hard fallback (also covers BUG-013's malformed-JSON case
    # reaching this point): an honest, fixed message is the floor — a
    # blank string, or a raw JSON blob, must never be what a customer sees.
    fallback_reply = (
        "I wasn't able to process that request. Could you try "
        "rephrasing it, or asking in two separate steps?"
    )
    _save(fallback_reply)
    return _package(fallback_reply, trace, MAX_TOOL_ITERATIONS, model_latencies)


# Day 11 (streaming) — see docs/bug-log.md.
#
# TRUST PRINCIPLE: Governance
#
# Business Purpose:
#     Stream tokens to the customer as they're generated (fixing the
#     PERCEIVED latency BUG-004 measured), without silently giving up
#     the two safety guarantees BUG-011 and BUG-013 spent nine bugs'
#     worth of work building — both work by checking the COMPLETE reply
#     before it reaches the customer, which naive token-by-token
#     streaming would bypass entirely.
#
# Design Decision:
#     Stream and buffer simultaneously. Every token is forwarded to the
#     client the moment it arrives (a "token" event) AND accumulated
#     server-side into the same complete-text buffer run_agent() already
#     builds. Once a round's stream ends, the exact same
#     _looks_like_tool_call_json() and _finalize_reply() checks that
#     protect the non-streaming path run against that buffer. If either
#     would have changed what the customer sees, a "correction" event is
#     sent telling the client to replace the just-streamed text with the
#     honest version. A terminal "done" event always carries the final,
#     fully-vetted reply plus the same rounds/model_latency_ms breakdown
#     as run_agent() — regardless of whether a correction fired.
#
# Benefits:
#     - Time-to-first-token becomes the customer-facing latency number
#       instead of time-to-full-reply, directly answering BUG-004's
#       resolution (see docs/bug-log.md) without a larger/GPU-backed model
#     - The safety guarantee is unchanged, not weakened: a customer can
#       see a fabrication or malformed blob flash briefly before a
#       correction replaces it, but they can never be LEFT BELIEVING a
#       false claim or seeing raw internal JSON as the final state —
#       which is the actual guarantee BUG-011/BUG-013 make, not
#       "never visible for a moment"
#     - Tool-decision rounds cost nothing extra to stream: every real
#       log from this project shows content is empty exactly when
#       tool_calls is populated for this model, so streaming every round
#       uniformly (rather than trying to predict which round is "the
#       final one" in advance) never leaks partial tool-call reasoning
#
# Failure Strategy:
#     If the model's streaming NDJSON output doesn't match the exact
#     chunk shape assumed here (e.g. a future Ollama version changes
#     whether content deltas are incremental vs cumulative), this has
#     only been verified against mocked chunk sequences, NOT a live
#     Ollama instance — flagged explicitly for a live smoke test before
#     trusting this in front of real customers, same posture as every
#     other live-verification step this project has taken.
#
# Future Validation:
#     Track how often the "correction" event actually fires in
#     production — if it's frequent, streaming is making fabrications
#     MORE visible (even if briefly), which would be a signal to
#     reconsider whether the guard should hold back the LAST token or
#     two rather than correcting after the fact.
def _package_stream(reply: str, trace: List[Dict[str, Any]], rounds: int, model_latency_ms: List[float]) -> Dict[str, Any]:
    return {
        "reply": reply,
        "tool_calls": trace,
        "rounds": rounds,
        "model_latency_ms": [round(ms, 1) for ms in model_latency_ms],
        "total_model_latency_ms": round(sum(model_latency_ms), 1),
    }


def _consume_stream(messages: List[Dict[str, Any]], use_tools: bool):
    """Runs one streaming Ollama call, yielding ('token', text) events as
    they arrive and returning (full_content, tool_calls, latency_ms) once
    the stream ends. A thin, testable seam between the raw NDJSON chunks
    and run_agent_stream()'s round logic."""
    content_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    t0 = time.monotonic()
    for chunk in _call_ollama_stream(messages, use_tools=use_tools):
        chunk_msg = chunk.get("message") or {}
        delta = chunk_msg.get("content") or ""
        if delta:
            content_parts.append(delta)
            yield ("token", delta)
        if chunk_msg.get("tool_calls"):
            tool_calls = chunk_msg["tool_calls"]
        if chunk.get("done"):
            break
    latency_ms = (time.monotonic() - t0) * 1000
    return "".join(content_parts).strip(), tool_calls, latency_ms


def run_agent_stream(user_message: str, db: Session, session_id: str = None):
    """
    Streaming counterpart to run_agent() — see its docstring for the
    multi-round tool-chaining and conversation-memory rationale, both
    unchanged here. This function only changes HOW the final answer
    reaches the customer (streamed) and adds the buffer-then-correct
    step described above; every trust guarantee from BUG-007 through
    BUG-013 is preserved, not reimplemented differently.

    Yields dicts of shape {"event": ..., "data": ...}:
      - "token":      {"text": str}               — a content delta
      - "tool_call":  {tool, success, ...}         — after each tool runs
      - "correction": {"reply": str}               — replace displayed text
      - "done":       full _package_stream() dict  — always sent last
    """
    history = conversation.get_history(session_id) if session_id else []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
        {"role": "user", "content": user_message},
    ]

    def _save(reply: str):
        if session_id:
            conversation.set_history(session_id, messages[1:] + [{"role": "assistant", "content": reply}])

    trace: List[Dict[str, Any]] = []
    model_latencies: List[float] = []

    # LIMITATION-004 fix — see docs/bug-log.md.
    #
    # TRUST PRINCIPLE: Reliability
    #
    # Business Purpose:
    #     A live smoke test showed the real gap in this design: any round
    #     where the model is deciding whether to call a tool produces NO
    #     content at all (the same empty-content-means-tool-call pattern
    #     documented since Day 8), so the customer sees nothing during
    #     it — and that round's latency was measured live at 5.5s to
    #     89.7s across three back-to-back IDENTICAL requests. Streaming
    #     the eventual answer doesn't help if the customer has already
    #     been staring at a blank screen for up to a minute and a half
    #     before any token exists to stream.
    #
    # Design Decision:
    #     Emit an honest "status" event the instant each round begins,
    #     before the model has produced anything. This does NOT reduce
    #     real latency — LIMITATION-004 is explicit that this doesn't
    #     fix the underlying volatility — it only ensures the customer
    #     is never left with zero feedback during the slowest, least
    #     predictable part of the request.
    #
    # Failure Strategy:
    #     Purely cosmetic/informational — a client that ignores "status"
    #     events loses nothing it had before this change.
    for round_num in range(1, MAX_TOOL_ITERATIONS + 1):
        status_msg = "Looking that up..." if round_num == 1 else "Still working on it..."
        yield {"event": "status", "data": {"message": status_msg}}

        content = ""
        tool_calls: List[Dict[str, Any]] = []
        gen = _consume_stream(messages, use_tools=True)
        try:
            while True:
                kind, text = next(gen)
                if kind == "token":
                    yield {"event": "token", "data": {"text": text}}
        except StopIteration as stop:
            content, tool_calls, latency_ms = stop.value
        model_latencies.append(latency_ms)

        print(
            f"[AGENT STREAM DEBUG] round={round_num} "
            f"content={content!r} "
            f"tool_calls={[tc['function']['name'] for tc in tool_calls]}",
            flush=True,
        )

        if not tool_calls:
            if content and not _looks_like_tool_call_json(content):
                final_reply = _finalize_reply(content, trace)
                _save(final_reply)
                if final_reply != content:
                    yield {"event": "correction", "data": {"reply": final_reply}}
                yield {"event": "done", "data": _package_stream(final_reply, trace, round_num, model_latencies)}
                return

            # BUG-008/BUG-013 nudge path — identical trigger condition to
            # run_agent()'s non-streaming version. If we already streamed
            # malformed-looking content live (BUG-013's case), the client
            # saw it briefly; correct it before retrying.
            if content:
                yield {"event": "correction", "data": {"reply": None}}
            messages.append({"role": "assistant", "content": content, "tool_calls": []})
            messages.append({
                "role": "user",
                "content": (
                    "You didn't call a tool or provide an answer — or you "
                    "wrote out a tool call as text instead of actually "
                    "calling it. Please either use the actual tool-calling "
                    "mechanism to call a tool, or give the customer a "
                    "plain-text answer. Do not write JSON in your reply."
                ),
            })
            continue

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tc in tool_calls:
            name = tc["function"]["name"]
            arguments = tc["function"]["arguments"]
            _tool_t0 = time.monotonic()
            result = _execute_tool(name, arguments, db)
            tool_latency_ms = (time.monotonic() - _tool_t0) * 1000
            trace.append({
                "tool": name, "arguments": arguments,
                "success": result["success"],
                "result_count": len(result["results"]),
                "error": result["error"],
                "latency_ms": round(tool_latency_ms, 1),
                # Day 14 (UI) — see docs/bug-log.md and run_agent()'s
                # matching comment above. Real product data, not just a
                # count — this is what the frontend's "tool_call" event
                # listener actually renders as a product card.
                "results": result["results"],
            })
            yield {"event": "tool_call", "data": trace[-1]}
            messages.append({"role": "tool", "content": json.dumps(result)})

    # Iteration cap hit — force a final streamed answer, tools disabled,
    # same terminal guarantee as run_agent()'s non-streaming hard fallback.
    yield {"event": "status", "data": {"message": "Finishing up..."}}
    gen = _consume_stream(messages, use_tools=False)
    try:
        while True:
            kind, text = next(gen)
            if kind == "token":
                yield {"event": "token", "data": {"text": text}}
    except StopIteration as stop:
        final_content, _, latency_ms = stop.value
    model_latencies.append(latency_ms)

    if final_content and not _looks_like_tool_call_json(final_content):
        final_reply = _finalize_reply(final_content, trace)
        _save(final_reply)
        if final_reply != final_content:
            yield {"event": "correction", "data": {"reply": final_reply}}
        yield {"event": "done", "data": _package_stream(final_reply, trace, MAX_TOOL_ITERATIONS, model_latencies)}
        return

    fallback_reply = (
        "I wasn't able to process that request. Could you try "
        "rephrasing it, or asking in two separate steps?"
    )
    _save(fallback_reply)
    yield {"event": "correction", "data": {"reply": fallback_reply}}
    yield {"event": "done", "data": _package_stream(fallback_reply, trace, MAX_TOOL_ITERATIONS, model_latencies)}
