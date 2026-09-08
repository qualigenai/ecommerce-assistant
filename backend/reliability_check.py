"""
Day 12 — Reliability verification. See docs/acceptance-criteria.md, section 1.

Formally confirms what earlier days have already observed working in
passing (docker compose health, the fast path's independence from the
AI path), rather than building anything new. Two parts:

  1. Automated — health endpoints and fast-path correctness. Runs
     straight through, no intervention needed.
  2. Semi-automated — proving the fast path survives Ollama being down.
     This genuinely requires you to stop Ollama mid-run (there's no way
     to fake that from inside this script), so it pauses and waits for
     you to do it, then continues.

Usage:
    python reliability_check.py [--base-url http://localhost:8001]
"""
import argparse
import time

import httpx


def check_health_endpoints(client: httpx.Client, base_url: str) -> bool:
    print("\n--- 1. Health endpoints ---")
    all_ok = True
    for path in ("/health", "/health/qdrant", "/health/ollama"):
        try:
            r = client.get(f"{base_url}{path}", timeout=10)
            body = r.json()
            ok = r.status_code == 200 and body.get("status") == "ok"
            print(f"  {path}: {'PASS' if ok else 'FAIL'}  ({body})")
            all_ok = all_ok and ok
        except Exception as e:
            print(f"  {path}: FAIL  (request error: {e})")
            all_ok = False
    return all_ok


def check_fast_path_correctness(client: httpx.Client, base_url: str) -> bool:
    print("\n--- 2. Fast filter path returns correct, real results ---")
    try:
        r = client.get(f"{base_url}/search", params={"category": "Hiking Boots"}, timeout=10)
        r.raise_for_status()
        results = r.json()
        ok = isinstance(results, list) and len(results) > 0
        print(f"  /search?category=Hiking Boots -> {len(results) if ok else 0} results: "
              f"{'PASS' if ok else 'FAIL'}")
        return ok
    except Exception as e:
        print(f"  FAIL (request error: {e})")
        return False


def check_fast_path_survives_ollama_down(client: httpx.Client, base_url: str) -> bool:
    print("\n--- 3. Fast path independence from the AI path (Reliability box 3) ---")
    print("  This step needs Ollama stopped by hand — there's no way to fake that")
    print("  from inside this script.")
    print("  In another terminal: stop Ollama (close the app, or")
    print("  `docker compose stop ollama` if it's containerized in your setup).")
    input("  Press Enter here once Ollama is confirmed stopped...")

    all_ok = True

    # /search should be completely unaffected - pure SQL, no AI dependency.
    try:
        t0 = time.monotonic()
        r = client.get(f"{base_url}/search", params={"category": "Hiking Boots"}, timeout=10)
        ms = (time.monotonic() - t0) * 1000
        ok = r.status_code == 200 and len(r.json()) > 0
        print(f"  /search with Ollama down: {'PASS' if ok else 'FAIL'} ({ms:.1f}ms, "
              f"{len(r.json()) if ok else 0} results)")
        all_ok = all_ok and ok
    except Exception as e:
        print(f"  /search with Ollama down: FAIL (request error: {e})")
        all_ok = False

    # /chat should fail HONESTLY (BUG-012's fallback) - not hang, not crash,
    # not return a blank reply.
    try:
        t0 = time.monotonic()
        r = client.post(f"{base_url}/chat", params={"message": "find hiking boots"}, timeout=70)
        ms = (time.monotonic() - t0) * 1000
        body = r.json()
        reply = body.get("reply", "")
        ok = r.status_code == 200 and reply.strip() != ""
        print(f"  /chat with Ollama down: {'PASS' if ok else 'FAIL'} ({ms:.1f}ms)")
        print(f"    reply: {reply!r}")
        if ms > 65000:
            print("    NOTE: took close to the 60s Ollama timeout - expected here, "
                  "confirms BUG-012's except-path is what caught this, not a hang.")
        all_ok = all_ok and ok
    except httpx.TimeoutException:
        print("  /chat with Ollama down: FAIL - request timed out client-side. "
              "This would mean BUG-012's fallback did NOT fire in time - a regression worth investigating.")
        all_ok = False
    except Exception as e:
        print(f"  /chat with Ollama down: FAIL (unexpected error: {e})")
        all_ok = False

    print("\n  Remember to restart Ollama before continuing to other Day 12 checks.")
    input("  Press Enter once Ollama is back up...")
    return all_ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8001")
    args = parser.parse_args()

    results = {}
    with httpx.Client() as client:
        results["health_endpoints"] = check_health_endpoints(client, args.base_url)
        results["fast_path_correct"] = check_fast_path_correctness(client, args.base_url)
        results["fast_path_survives_ollama_down"] = check_fast_path_survives_ollama_down(client, args.base_url)

    print("\n=== Reliability check summary ===")
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print("\n--- Markdown block, paste-ready for docs/acceptance-criteria.md ---")
    print(f"- [{'x' if results['health_endpoints'] else ' '}] All services (backend, Qdrant) start cleanly; "
          f"health-check endpoints return ok before any feature is considered working")
    print(f"- [{'x' if results['fast_path_survives_ollama_down'] else ' '}] The fast filter path never depends "
          f"on the AI path being available")


if __name__ == "__main__":
    main()
