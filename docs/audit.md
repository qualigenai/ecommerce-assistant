# Site & architecture audit

**Subject**: AI-Powered E-commerce Assistant (practice/portfolio project)
**Audit date**: Day 2
**Auditor role**: This document is written the way it would be for a real client
engagement &mdash; as if handed an existing site and asked "where does AI fit,
and what has to change to support it."

---

## 1. Current state (as of end of Day 1)

| Layer | Status | Notes |
|---|---|---|
| Frontend | Next.js 16.3.0 scaffold, default starter page only | No product catalog, no pages built yet |
| Backend | FastAPI, three health-check endpoints only | No business logic yet |
| Search | None | No product data exists to search |
| Data store | SQLite planned, not yet created | Schema not yet finalized |
| Vector DB | Qdrant running, no collections | Confirmed reachable, unused |
| AI model | Ollama running `llama3.2:3b` locally | Confirmed reachable, unused |
| Version control | Git initialized, pushed to GitHub | `main` branch active |

**Summary**: this is a greenfield build rather than a retrofit, but the audit
discipline is deliberately applied anyway &mdash; on a real client engagement,
this same document would instead describe an existing live site's search
mechanism (SQL `LIKE` queries, third-party search widget, etc.), its data
model, and its traffic patterns before any AI work begins.

## 2. Data model requirements

For AI-assisted search and recommendations to work, the product catalog needs
structured fields, not just free-text descriptions:

| Field | Type | Purpose |
|---|---|---|
| `sku` | string | Unique identifier |
| `name` | string | Display name |
| `description` | text | Feeds embeddings for semantic search |
| `category` | string | Used by the fast filter path |
| `price` | float | Used by the fast filter path |
| `stock` | integer | Live availability, checked at answer-time |
| `attributes` | key-value (e.g. `waterproof: true`) | Used by the fast filter path |

This schema is what gets built on Day 3.

## 3. Integration points identified

| Point | What happens here |
|---|---|
| Search bar | Routes to fast filter path or AI path, per the routing heuristic |
| Product detail page | "Related products" recommendation widget |
| Chat widget (new) | Conversational assistant for ambiguous or multi-turn queries |
| Cart | Agent tool for adding items during a chat conversation |

## 4. Constraints carried into the build

- 100% open-source stack, no paid vendor APIs (see `docs/problem-statement-and-solution.md`)
- AI is additive, not a replacement for structured search &mdash; the fast
  filter path is the default, AI is the fallback for what filters can't
  resolve
- Local inference only (Ollama, CPU) &mdash; response latency budget set
  accordingly in the acceptance criteria

## 5. Risks / open questions

- Catalog size for this demo (30&ndash;50 products) is far smaller than a real
  store &mdash; recommendation cold-start logic (Day 6) is more load-bearing
  here than it would be on a catalog with real interaction history
- CPU-only local inference may not meet a strict latency target under load;
  documented fallback is a hosted open-weight model (Groq) if needed
