"""
Day 9 integration test set — 10 queries against the LIVE /chat endpoint.

This is deliberately NOT part of the pytest suite: it needs a real running
backend with a real Ollama model behind it, which pytest's isolated
in-memory tests don't have. Run this manually against your running stack:

    docker compose up -d
    python tests/integration_test_agent.py

Each query lists which tool(s) are EXPECTED to appear in the trace. A
query "passing" here means the model chose a reasonable tool, not that
the exact wording of its reply matched anything — tool selection
accuracy is what this set exists to measure (per docs/acceptance-criteria.md).

TRUST PRINCIPLE: Continuous Validation
This turns "does the agent work" from an impression formed by scattered
manual curl commands into a repeatable, re-runnable checklist — the same
10 queries can be re-run after any future change to confirm nothing
regressed, the same way the pytest suite does for the deterministic code.
"""

import sys

import httpx

BASE_URL = "http://localhost:8001"

# Each entry: (label, message, expected_tools, session_id_ref)
# session_id_ref links query 8b to 8a's session, to test conversation
# memory specifically (the Day 9 headline feature).
QUERIES = [
    ("1. Structured filter search", "Do you have waterproof hiking boots under $100?", {"search_products"}, None),
    ("2. Category browse", "What tents do you have?", {"search_products"}, None),
    ("3. Stock check", "Is the Trailhead Waterproof Hiking Boot in stock?", {"check_stock"}, None),
    ("4. Order status - known order", "What's the status of order ORD-1001?", {"order_status"}, None),
    ("5. Order status - unknown order", "What's the status of order ORD-9999?", {"order_status"}, None),
    ("6. Semantic search", "Something for a rainy weekend camping trip", {"search_products"}, None),
    ("7. Standalone add (no prior context)", "Add the Trailhead Waterproof Hiking Boot to my cart", {"search_products"}, None),
    ("8a. Multi-turn: search first", "Find the Trailhead Waterproof Hiking Boot", {"search_products"}, "MEMORY_TEST"),
    ("8b. Multi-turn: add using memory", "add 1 to my cart", {"add_to_cart"}, "MEMORY_TEST"),
    ("9. No matching products", "Do you sell snowboards?", {"search_products"}, None),
    ("10. Off-topic", "Tell me a joke", set(), None),
]


def run_query(client, label, message, expected_tools, session_id):
    params = {"message": message}
    if session_id:
        params["session_id"] = session_id
    r = client.post(f"{BASE_URL}/chat", params=params, timeout=180)
    r.raise_for_status()
    data = r.json()

    actual_tools = {tc["tool"] for tc in data.get("tool_calls", [])}
    passed = expected_tools.issubset(actual_tools) if expected_tools else True

    print(f"\n{label}")
    print(f"  query:          {message!r}")
    print(f"  expected tools: {expected_tools or '(none)'}")
    print(f"  actual tools:   {actual_tools or '(none)'}")
    print(f"  reply:          {data['reply'][:150]}")
    print(f"  latency_ms:     {data['latency_ms']}")
    print(f"  result:         {'PASS' if passed else 'FAIL'}")

    return passed, data.get("session_id")


def main():
    results = []
    session_ids = {}

    with httpx.Client() as client:
        for label, message, expected_tools, session_ref in QUERIES:
            session_id = session_ids.get(session_ref) if session_ref else None
            passed, returned_session_id = run_query(client, label, message, expected_tools, session_id)
            results.append((label, passed))
            if session_ref:
                session_ids[session_ref] = returned_session_id

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    n_passed = sum(1 for _, p in results if p)
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    print(f"\n{n_passed}/{len(results)} passed")

    if n_passed < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
