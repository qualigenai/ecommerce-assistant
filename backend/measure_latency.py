"""
Day 10 — BUG-004 latency benchmark. See docs/bug-log.md.

Hits the running backend directly (Docker Compose stack must already be
up: backend, Qdrant, Ollama) and measures real, warm-condition latency
across the four request shapes the acceptance criteria actually care
about. Run 1 of each category is discarded as a cold-start cost, per
BUG-004's own open question about whether its 128.4s outlier was
cold-start or genuine.

Usage:
    python measure_latency.py [--base-url http://localhost:8000] [--runs 5]

Requires a seeded catalog with a real "Trailhead Waterproof Hiking Boot"
product and a real "Hiking Boots" category (same fixtures every other
live test in this project has used) and a reindexed Qdrant collection
(POST /reindex) so the AI-path query has something to actually find.
"""
import argparse
import statistics
import time
from typing import Dict, List

import httpx

# Acceptance criteria targets (docs/acceptance-criteria.md, Performance)
FAST_TARGET_MS = 300
AI_TARGET_MS = 5000
# Compound chat has no explicit target in the acceptance criteria — this
# script still measures it, since it's the case BUG-004 is actually
# about, but reports it without a pass/fail verdict until Day 10 decides
# on an honest tiered budget.


def timed_get(client: httpx.Client, url: str, params: dict) -> float:
    t0 = time.monotonic()
    r = client.get(url, params=params, timeout=120)
    r.raise_for_status()
    return (time.monotonic() - t0) * 1000, r.json()


def timed_post(client: httpx.Client, url: str, params: dict) -> float:
    t0 = time.monotonic()
    r = client.post(url, params=params, timeout=120)
    r.raise_for_status()
    return (time.monotonic() - t0) * 1000, r.json()


def summarize(label: str, samples_ms: List[float], target_ms: float = None, detail: List[dict] = None) -> Dict:
    warm = samples_ms[1:] if len(samples_ms) > 1 else samples_ms
    result = {
        "label": label,
        "all_samples_ms": [round(s, 1) for s in samples_ms],
        "warm_min_ms": round(min(warm), 1),
        "warm_median_ms": round(statistics.median(warm), 1),
        "warm_max_ms": round(max(warm), 1),
        "target_ms": target_ms,
        "pass": (max(warm) <= target_ms) if target_ms else None,
        "detail": detail or [],
    }
    return result


def run(base_url: str, runs: int) -> List[Dict]:
    results = []
    with httpx.Client() as client:

        # --- 1. Fast filter path: pure SQL, no AI, /search directly ---
        samples = []
        for _ in range(runs):
            ms, _ = timed_get(client, f"{base_url}/search",
                               {"category": "Hiking Boots", "waterproof": "true", "price_lt": 200})
            samples.append(ms)
        results.append(summarize("fast_filter (/search)", samples, FAST_TARGET_MS))

        # --- 2. Routed fast path: /assistant/search with clean structured signals ---
        samples = []
        for _ in range(runs):
            ms, _ = timed_get(client, f"{base_url}/assistant/search",
                               {"q": "waterproof hiking boots under $200"})
            samples.append(ms)
        results.append(summarize("routed_filter (/assistant/search)", samples, FAST_TARGET_MS))

        # --- 3. AI semantic path: vague query, no clean category/price match ---
        samples = []
        for _ in range(runs):
            ms, _ = timed_get(client, f"{base_url}/assistant/search",
                               {"q": "something for a rainy weekend camping trip"})
            samples.append(ms)
        results.append(summarize("ai_semantic (/assistant/search)", samples, AI_TARGET_MS))

        # --- 4. Chat, single tool call, no conversation history ---
        samples, detail = [], []
        for i in range(runs):
            ms, body = timed_post(client, f"{base_url}/chat",
                                   {"message": "Find the Trailhead Waterproof Hiking Boot in the catalog"})
            samples.append(ms)
            detail.append({"run": i + 1, "rounds": body.get("rounds"),
                            "model_latency_ms": body.get("model_latency_ms")})
        results.append(summarize("chat_single_tool (/chat)", samples, AI_TARGET_MS, detail))

        # --- 5. Chat, compound request within ONE turn (search + add) ---
        samples, detail = [], []
        for i in range(runs):
            ms, body = timed_post(client, f"{base_url}/chat",
                                   {"message": "Find the Trailhead Waterproof Hiking Boot and add 1 to my cart"})
            samples.append(ms)
            detail.append({"run": i + 1, "rounds": body.get("rounds"),
                            "model_latency_ms": body.get("model_latency_ms")})
        # No target_ms — this is the case BUG-004 needs a real decision on.
        results.append(summarize("chat_compound_single_turn (/chat)", samples, None, detail))

        # --- 6. Chat, the actual Day 9 scenario: find (turn 1), add (turn 2) ---
        samples, detail = [], []
        for i in range(runs):
            session_id = None
            _, body1 = timed_post(client, f"{base_url}/chat",
                                   {"message": "Find the Trailhead Waterproof Hiking Boot"})
            session_id = body1.get("session_id")
            t0 = time.monotonic()
            _, body2 = timed_post(client, f"{base_url}/chat",
                                   {"message": "Add 1 to my cart", "session_id": session_id})
            turn2_ms = (time.monotonic() - t0) * 1000
            samples.append(turn2_ms)  # measuring turn 2's cost specifically
            detail.append({"run": i + 1, "turn2_rounds": body2.get("rounds"),
                            "turn2_model_latency_ms": body2.get("model_latency_ms")})
        results.append(summarize("chat_two_turn_day9 (/chat, turn 2 only)", samples, AI_TARGET_MS, detail))

    return results


def print_report(results: List[Dict]):
    print("\n=== BUG-004 latency benchmark (warm runs only, run 1 discarded as cold-start) ===\n")
    for r in results:
        verdict = "" if r["target_ms"] is None else (" [PASS]" if r["pass"] else " [FAIL]")
        target_str = f" (target: {r['target_ms']}ms)" if r["target_ms"] else " (no target set)"
        print(f"{r['label']}{target_str}{verdict}")
        print(f"  min={r['warm_min_ms']}ms  median={r['warm_median_ms']}ms  max={r['warm_max_ms']}ms")
        print(f"  all samples: {r['all_samples_ms']}")
        if r["detail"]:
            for d in r["detail"]:
                print(f"  {d}")
        print()

    print("\n--- Markdown block, paste-ready for docs/bug-log.md BUG-004 update ---\n")
    print("| Path | Target | Warm min | Warm median | Warm max | Verdict |")
    print("|---|---|---|---|---|---|")
    for r in results:
        target_str = f"{r['target_ms']}ms" if r["target_ms"] else "none set"
        verdict = "n/a" if r["target_ms"] is None else ("PASS" if r["pass"] else "FAIL")
        print(f"| {r['label']} | {target_str} | {r['warm_min_ms']}ms | {r['warm_median_ms']}ms | {r['warm_max_ms']}ms | {verdict} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    results = run(args.base_url, args.runs)
    print_report(results)
