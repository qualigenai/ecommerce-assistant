"""
Day 12 — Accuracy verification. See docs/acceptance-criteria.md, section 2.

Two checks, both against the LIVE catalog (not hardcoded expected IDs,
since the catalog can and has grown - e.g. BOOT-999 showing up in later
runs than the original seed set):

  1. Structured filter correctness - for each filter combination, assert
     EVERY returned product actually satisfies the filter. Not a spot
     check on one product; a blanket assertion across all results.
  2. AI-path grounding - ask /chat about a real product's price/stock,
     independently fetch the true values via /search, and confirm the
     reply's numbers match. Also checks the honest-refusal case: asking
     about a product that doesn't exist should get an honest "not
     found," never a fabricated answer.

Usage:
    python accuracy_check.py [--base-url http://localhost:8001]
"""
import argparse
import re

import httpx


def check_filter_no_false_positives(client: httpx.Client, base_url: str) -> bool:
    print("\n--- 1. Structured filters return ONLY matching products ---")
    all_ok = True

    checks = [
        ({"category": "Hiking Boots"}, lambda p: p["category"] == "Hiking Boots"),
        ({"category": "Hiking Boots", "waterproof": "true"}, lambda p: p["attributes"].get("waterproof") is True),
        ({"category": "Hiking Boots", "price_lt": 80}, lambda p: p["price"] < 80),
        ({"category": "Hiking Boots", "price_gt": 100}, lambda p: p["price"] > 100),
    ]

    for params, predicate in checks:
        try:
            r = client.get(f"{base_url}/search", params=params, timeout=10)
            r.raise_for_status()
            results = r.json()
            violations = [p for p in results if not predicate(p)]
            ok = len(violations) == 0
            print(f"  {params} -> {len(results)} results, {len(violations)} violate the filter: "
                  f"{'PASS' if ok else 'FAIL'}")
            if violations:
                print(f"    violating products: {[p.get('sku') for p in violations]}")
            all_ok = all_ok and ok
        except Exception as e:
            print(f"  {params}: FAIL (request error: {e})")
            all_ok = False

    return all_ok


def check_ai_path_grounding(client: httpx.Client, base_url: str) -> bool:
    print("\n--- 2. AI-path (/chat) answers are grounded in live catalog data ---")
    all_ok = True

    # Get ground truth directly from the catalog, not hardcoded.
    try:
        r = client.get(f"{base_url}/search", params={"category": "Hiking Boots"}, timeout=10)
        r.raise_for_status()
        catalog = r.json()
        target = next((p for p in catalog if p["sku"] == "BOOT-001"), None)
        if not target:
            print("  SKIP - BOOT-001 (Trailhead Waterproof Hiking Boot) not found in current "
                  "catalog; can't run a grounded cross-check without a known real product.")
            return None
    except Exception as e:
        print(f"  FAIL (couldn't fetch ground truth: {e})")
        return False

    true_price = target["price"]
    true_stock = target["stock"]
    print(f"  Ground truth from /search: {target['name']} - price=${true_price}, stock={true_stock}")

    try:
        r = client.post(f"{base_url}/chat",
                         params={"message": f"What is the price and stock of the {target['name']}?"},
                         timeout=70)
        r.raise_for_status()
        reply = r.json().get("reply", "")
        print(f"  /chat reply: {reply!r}")

        price_str = f"{true_price:.2f}".rstrip("0").rstrip(".")
        price_mentioned = str(true_price) in reply or price_str in reply
        stock_mentioned = str(true_stock) in reply
        ok = price_mentioned and stock_mentioned
        print(f"  price ({true_price}) mentioned: {price_mentioned}, "
              f"stock ({true_stock}) mentioned: {stock_mentioned}: {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    except Exception as e:
        print(f"  FAIL (request error: {e})")
        all_ok = False

    return all_ok


def check_honest_refusal_on_unknown_product(client: httpx.Client, base_url: str) -> bool:
    print("\n--- 3. Honest refusal for a product that doesn't exist (no fabrication) ---")
    fake_name = "Zephyr Cloudwalker Antigravity Boot"
    try:
        r = client.post(f"{base_url}/chat",
                         params={"message": f"What is the price and stock of the {fake_name}?"},
                         timeout=70)
        r.raise_for_status()
        reply = r.json().get("reply", "").lower()
        print(f"  /chat reply: {reply!r}")

        # It should NOT confidently state a specific price/stock for a product
        # that was never returned by search_products.
        fabricated_price = bool(re.search(r"\$\d+(\.\d+)?", reply))
        honest_signals = any(kw in reply for kw in [
            "couldn't find", "could not find", "not found", "no product",
            "doesn't exist", "does not exist", "unable to find", "no matching",
        ])
        ok = honest_signals and not fabricated_price
        print(f"  fabricated a price: {fabricated_price}, honest refusal language present: "
              f"{honest_signals}: {'PASS' if ok else 'FAIL'}")
        return ok
    except Exception as e:
        print(f"  FAIL (request error: {e})")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8001")
    args = parser.parse_args()

    results = {}
    with httpx.Client() as client:
        results["filter_no_false_positives"] = check_filter_no_false_positives(client, args.base_url)
        results["ai_path_grounded"] = check_ai_path_grounding(client, args.base_url)
        results["honest_refusal_unknown_product"] = check_honest_refusal_on_unknown_product(client, args.base_url)

    print("\n=== Accuracy check summary ===")
    for name, passed in results.items():
        label = "SKIPPED" if passed is None else ("PASS" if passed else "FAIL")
        print(f"  {name}: {label}")

    print("\n--- Markdown block, paste-ready for docs/acceptance-criteria.md ---")
    fp_ok = results["filter_no_false_positives"]
    grounded_ok = results["ai_path_grounded"]
    print(f"- [{'x' if fp_ok else ' '}] Structured filter queries return only products matching the "
          f"stated filters - no false positives")
    print(f"- [{'x' if grounded_ok else ' '}] AI-path responses are grounded in live catalog data "
          f"(price, stock) fetched at answer-time, never from the model's own memory")


if __name__ == "__main__":
    main()
