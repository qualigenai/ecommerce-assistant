"""
Day 11 — /chat/stream live smoke test. See docs/bug-log.md.

This is the live verification agent.py's run_agent_stream() docstring
calls out as still needed: everything about the streaming logic itself
(the buffer-then-correct pattern, BUG-011/BUG-013 parity) was unit-tested
against mocked Ollama chunk sequences, not a real Ollama instance. This
script is what actually confirms the real NDJSON chunk shape matches what
agent.py assumes, and reports the real time-to-first-token win.

Usage:
    python stream_smoke_test.py [--base-url http://localhost:8001] [--runs 3]

Requires the same seeded catalog + running stack as measure_latency.py.
"""
import argparse
import json
import time

import httpx


def stream_once(client: httpx.Client, base_url: str, message: str, session_id: str = None):
    params = {"message": message}
    if session_id:
        params["session_id"] = session_id

    t_start = time.monotonic()
    t_first_token = None
    events = []
    reply_text = ""
    session_id_seen = None

    with client.stream("POST", f"{base_url}/chat/stream", params=params, timeout=120) as r:
        r.raise_for_status()
        event_type = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event_type = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                events.append((event_type, data))
                if event_type == "session":
                    session_id_seen = data.get("session_id")
                if event_type == "status":
                    print(f"    [status @ {(time.monotonic()-t_start)*1000:.0f}ms] {data.get('message')}")
                if event_type == "token":
                    if t_first_token is None:
                        t_first_token = time.monotonic()
                    reply_text += data.get("text", "")
                if event_type == "correction" and data.get("reply"):
                    reply_text = data["reply"]
                if event_type == "done":
                    break

    t_end = time.monotonic()
    ttft_ms = (t_first_token - t_start) * 1000 if t_first_token else None
    total_ms = (t_end - t_start) * 1000

    done_data = next((d for etype, d in events if etype == "done"), {})
    corrections = [d for etype, d in events if etype == "correction"]

    return {
        "message": message,
        "session_id": session_id_seen,
        "ttft_ms": round(ttft_ms, 1) if ttft_ms else None,
        "total_ms": round(total_ms, 1),
        "event_sequence": [e for e, _ in events],
        "correction_fired": len(corrections) > 0,
        "final_reply": done_data.get("reply", reply_text),
        "rounds": done_data.get("rounds"),
    }


def run(base_url: str, runs: int):
    results = []
    with httpx.Client() as client:
        print(f"\n=== /chat/stream smoke test: single-tool request, {runs} runs ===\n")
        for i in range(runs):
            r = stream_once(client, base_url, "Find the Trailhead Waterproof Hiking Boot in the catalog")
            results.append(r)
            print(f"run {i+1}: TTFT={r['ttft_ms']}ms  total={r['total_ms']}ms  "
                  f"rounds={r['rounds']}  correction_fired={r['correction_fired']}")
            print(f"  events: {r['event_sequence']}")
            print(f"  reply: {r['final_reply'][:100]!r}\n")

        print(f"\n=== /chat/stream smoke test: real Day 9 two-turn scenario ===\n")
        r1 = stream_once(client, base_url, "Find the Trailhead Waterproof Hiking Boot")
        print(f"turn 1: TTFT={r1['ttft_ms']}ms  total={r1['total_ms']}ms  session_id={r1['session_id']}")
        r2 = stream_once(client, base_url, "Add 1 to my cart", session_id=r1["session_id"])
        print(f"turn 2: TTFT={r2['ttft_ms']}ms  total={r2['total_ms']}ms  "
              f"correction_fired={r2['correction_fired']}")
        print(f"  reply: {r2['final_reply'][:150]!r}")

    warm = results[1:] if len(results) > 1 else results
    ttfts = [r["ttft_ms"] for r in warm if r["ttft_ms"]]
    if ttfts:
        print(f"\n--- Summary (warm runs) ---")
        print(f"Time-to-first-token: min={min(ttfts):.1f}ms  "
              f"avg={sum(ttfts)/len(ttfts):.1f}ms  max={max(ttfts):.1f}ms")
        print(f"Compare against BUG-004's non-streaming full-reply numbers "
              f"(31.6-52.6s) to see the real perceived-latency win.")

    any_correction = any(r["correction_fired"] for r in results + [r1, r2])
    print(f"\nAny correction events fired during this run: {any_correction}")
    if any_correction:
        print("(Not itself a failure — it means BUG-011/BUG-013's guard caught "
              "something live. Worth checking WHICH run and reading its reply.)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    run(args.base_url, args.runs)
