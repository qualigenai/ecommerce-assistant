"""
Day 13 — Security verification. See docs/acceptance-criteria.md, section 4.

The sanitize.py and rate_limit.py MODULES were already unit-tested in
isolation (control chars, length limits, injection-signal flagging,
per-IP window expiry) before this ever touched main.py. What can only be
confirmed live is that the actual FastAPI wiring works: does /chat really
return 400 on bad input, and 429 after real repeated requests?

Usage:
    python security_check.py [--base-url http://localhost:8001]
"""
import argparse

import httpx


def check_input_sanitization(client: httpx.Client, base_url: str) -> bool:
    print("\n--- 1. Input sanitization (/chat returns 400 on bad input) ---")
    all_ok = True

    cases = [
        ("empty message", ""),
        ("whitespace only", "   "),
        ("way too long", "a" * 3000),
    ]
    for label, message in cases:
        try:
            r = client.post(f"{base_url}/chat", params={"message": message}, timeout=15)
            ok = r.status_code == 400
            print(f"  {label}: {'PASS' if ok else 'FAIL'} (status={r.status_code})")
            all_ok = all_ok and ok
        except Exception as e:
            print(f"  {label}: FAIL (request error: {e})")
            all_ok = False

    # A normal, legitimate message should still go through untouched.
    # timeout=120, not 70 - LIMITATION-004 (Day 11) already measured this
    # exact request type taking up to 89.7s live on a volatile round. A
    # shorter timeout here would produce a false FAIL from the test
    # script itself, not a real sanitization problem.
    try:
        r = client.post(f"{base_url}/chat", params={"message": "Find the Trailhead Waterproof Hiking Boot"}, timeout=120)
        ok = r.status_code == 200
        print(f"  legitimate message still works: {'PASS' if ok else 'FAIL'} (status={r.status_code})")
        all_ok = all_ok and ok
    except Exception as e:
        print(f"  legitimate message still works: FAIL (request error: {e})")
        all_ok = False

    return all_ok


def check_rate_limiting(client: httpx.Client, base_url: str) -> bool:
    print("\n--- 2. Rate limiting (/chat returns 429 after repeated requests) ---")
    print("  Sending 12 rapid requests with deliberately EMPTY messages.")
    print("  This is intentional, not a shortcut: FastAPI's Depends() runs")
    print("  rate_limit_ai_path BEFORE sanitize_chat_message() inside the")
    print("  endpoint body, so an invalid message still counts against the")
    print("  limit and fails fast (400) instead of costing a real, slow")
    print("  model call each time. This actually proves something the real")
    print("  message version wouldn't: the limiter applies independent of")
    print("  whether the request body is valid, exactly as it should for a")
    print("  defense against being hammered.")

    statuses = []
    for i in range(12):
        try:
            r = client.post(f"{base_url}/chat", params={"message": ""}, timeout=15)
            statuses.append(r.status_code)
            print(f"  request {i+1}: {r.status_code}"
                  + (f"  Retry-After={r.headers.get('retry-after')}" if r.status_code == 429 else ""))
        except Exception as e:
            print(f"  request {i+1}: FAIL (request error: {e})")
            statuses.append(None)

    got_429 = 429 in statuses
    first_ten_were_400 = statuses[:10] == [400] * 10
    print(f"\n  First 10 requests correctly reached input validation (400): "
          f"{'PASS' if first_ten_were_400 else 'FAIL'}")
    print(f"  At least one later request hit the rate limit (429): {'PASS' if got_429 else 'FAIL'}")
    if not got_429:
        print("  NOTE: if this is the first security_check.py run in the last 60s, "
              "earlier manual testing this minute may have already used up part of "
              "the window. Re-run once, back-to-back, if this unexpectedly fails.")
    return got_429 and first_ten_were_400


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8001")
    args = parser.parse_args()

    results = {}
    with httpx.Client() as client:
        results["input_sanitization"] = check_input_sanitization(client, args.base_url)
        results["rate_limiting"] = check_rate_limiting(client, args.base_url)

    print("\n=== Security check summary ===")
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print("\n--- Markdown block, paste-ready for docs/acceptance-criteria.md ---")
    print(f"- [{'x' if results['input_sanitization'] else ' '}] User input sanitized before being passed to the LLM")
    print(f"- [{'x' if results['rate_limiting'] else ' '}] Basic rate limiting on AI-path endpoints")


if __name__ == "__main__":
    main()
