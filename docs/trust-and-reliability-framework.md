# Trust &amp; reliability framework

Trust isn't a Day 15 checkbox — it's engineered in from the first line of
code. This document defines four pillars, scoped realistically for a
practice project (not a full enterprise control plane), and maps each one to
where it lands in the existing 15-day plan.

## The four pillars, scoped for this project

### 1. Reliability
**What it means here**: the system degrades gracefully, never catastrophically.
- The fast filter path never depends on the AI path being available (already
  true by design since Day 2)
- Every external call (Ollama, Qdrant) has a timeout and a defined fallback
  response, not a raw exception reaching the customer
- Health checks (Day 1) are the floor, not the ceiling — reliability also
  means *known, bounded* failure modes under load

### 2. Observability
**What it means here**: every request leaves a trace you can actually look at.
- A lightweight, append-only request log: timestamp, query text, which path
  it was routed to (filter vs. AI), latency, result count, success/failure
- This starts **today, Day 4** — the routing heuristic is exactly the
  decision that should be logged, since "why did this query go where it
  went" is the first question anyone debugging or auditing the system will
  ask
- Not a full OLAP/DuckDB telemetry vault like Control Hub — a single SQLite
  table is proportionate here, but the schema is designed so it *could*
  graduate to that later without a rewrite

### 3. Governance
**What it means here**: decisions are traceable and reviewable after the fact.
- Every AI-path response records which model and prompt version produced it
- Every agent tool call (Day 8 onward) is logged with its inputs and result,
  not just the final answer — so a wrong answer can be traced back to which
  tool call caused it
- No cost ledger needed for external APIs (everything's local/free), but the
  same log doubles as a *compute-time ledger* — useful evidence for the
  cost-effectiveness story this project is already built around

### 4. Continuous validation
**What it means here**: correctness is tested continuously, not assumed.
- The acceptance-criteria doc (Day 2) already defines what "correct" means —
  this pillar is about automatically checking against it, not just eyeballing
  results
- A **groundedness check** for the AI path: when the agent references a
  product, verify that product ID actually exists in the catalog before the
  response goes out — a lightweight hallucination guard, not a full
  Control-Hub-grade reliability engine, but the same underlying principle
- The Day 9 integration test set (10 queries, correct tool/path selection)
  is this pillar's concrete deliverable

## How this threads through the remaining days

| Day | Trust element added |
|---|---|
| 4 (today) | Request logging (path, latency, query) starts now, alongside the routing heuristic |
| 5–6 | Recommendation fallback logic already *is* a reliability pattern — log when cold-start fallback fires |
| 7–9 | Log every agent tool call; add the groundedness check on product references |
| 10–12 | Surface latency/path info in the UI optionally (e.g. a subtle "answered instantly" vs "AI-assisted" indicator) — turns observability into a user-facing trust signal, not just an internal log |
| 13–14 | Testing phase becomes: run the acceptance criteria as actual automated checks against the logs, not manual spot-checks |
| 15 | Hand-off docs include how to read the request log and what the groundedness check catches |

## What this deliberately does NOT include

To keep this proportionate to a practice project rather than over-building:
- No RBAC/multi-tenant auth (would add for a real multi-user enterprise deployment)
- No dedicated observability dashboard (the log itself is queryable directly; a
  Streamlit view like Control Hub's is a good "if I had one more day" extension,
  not a core requirement here)
- No external monitoring/alerting service — everything stays local and open source
