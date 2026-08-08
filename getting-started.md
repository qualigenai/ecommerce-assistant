# Getting started — AI e-commerce assistant practice project

Everything you need to begin, in one place. Confirmed environment, Day 1
setup steps, then the full 15-day plan for reference as you go.

---

## Confirmed environment (as of setup)

| Component | Status |
|---|---|
| OS | Windows, PowerShell |
| Ollama | v0.32.5, installed and running |
| Local model | `llama3.2:latest` (3B, 2.0GB) — already pulled |
| GPU | Intel UHD Graphics, integrated, no dedicated VRAM — **CPU inference** |
| Docker Desktop | v29.1.2 |
| Docker Compose | v2.40.3-desktop.1 |
| WSL2 | Confirmed, default distro `docker-desktop` |

**Model decision**: `llama3.2:3b` on CPU. Expect a few seconds per response
during agent testing — normal for CPU-only inference, not a problem to fix
now. If it's genuinely too slow once the agent is running (Day 7+), the
documented fallback is Groq's free-tier API serving the same open-weight
model family, swapped in with no prompt changes.

---

## Design philosophy: cost-effective and fast, AI only where it earns its place

The business goal is always speed + low cost + a satisfied user — AI is a
means to that end, not the goal itself. Concretely:

- **Structured filter queries** (SQL/FastAPI, no AI) handle any query that
  maps cleanly to known attributes — category, price range, boolean flags
  like "waterproof". These are near-instant and cost nothing per query.
- **The AI path** (embeddings + local LLM agent) only runs for what filters
  genuinely can't handle: ambiguous phrasing, synonyms, multi-turn context
  ("what about in blue?"), or comparison/reasoning requests.
- **Routing between the two is a simple heuristic**, not AI itself: if the
  query matches known attribute vocabulary and a numeric price pattern,
  route to filters; otherwise fall through to the AI path.

This keeps the common case (most searches) fast and free, and reserves the
slower, locally-hosted LLM call for the cases that actually need reasoning
— which is also the most defensible answer to "why AI here" in front of a
client or in an interview.

```
Customer query arrives
   │
   ├─ Parses cleanly into known filters? (category, price, boolean attrs)
   │
   ├─ YES → structured filter query (SQL) → fast, cheap, deterministic
   │
   └─ NO  → embedding search + LLM agent → handles ambiguity,
            synonyms, multi-turn, comparison
```

---

## Day 1 setup — do this first

**1. Create your project folder** and place these files (already generated,
see the earlier files in this conversation — `CLAUDE.md`, `docker-compose.yml`,
and the `backend/` folder with `Dockerfile`, `requirements.txt`, `main.py`):

```
ecommerce-assistant/
├── CLAUDE.md
├── docker-compose.yml
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    └── main.py
```

**2. Build and start the backend + vector DB:**

```powershell
docker compose up --build
```

**3. Confirm all three services are healthy** (open a second terminal):

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/health/qdrant
curl http://localhost:8000/health/ollama
```

`/health/ollama` should return `"status": "ok"` and list `llama3.2:latest` —
this confirms the backend container can reach your natively-running Ollama
through `host.docker.internal`, the one new piece of plumbing in this setup.

**4. Scaffold the frontend:**

```powershell
npx create-next-app@latest frontend --typescript --tailwind --app
```

**Day 1 is done when**: all three health checks return `ok`, and
`npx create-next-app` completes without errors. Commit the repo at this
point — "Day 1: environment setup, Qdrant + FastAPI + Ollama connectivity
confirmed."

---

## Full day-wise plan

### Phase 1 — Project setup & audit (Days 1–2)
- **Day 1**: Environment setup (above)
- **Day 2**: Audit doc (simulated client site), finalize product schema, acceptance-criteria doc

### Phase 2 — Retail data model & catalog pipeline (Days 3–4)
- **Day 3**: Seed 30–50 products with structured attribute fields (`category`,
  `price`, `waterproof: bool`, etc. — not just free-text descriptions, since
  this is what makes the filter path possible). FastAPI CRUD endpoints.
  **Also build the structured filter endpoint** (`/search?category=boots&waterproof=true&price_lt=100`)
  — plain SQL query params, no AI, fast baseline. This ships a working,
  cost-free search on Day 3, before any AI is involved.
- **Day 4**: Embedding pipeline (`all-MiniLM-L6-v2` → Qdrant) for the semantic
  fallback path, refresh mechanism design, and the routing heuristic that
  decides filter-path vs. AI-path per query.

### Phase 3 — Recommendation engine (Days 5–6)
- **Day 5**: Embedding-similarity `/recommend/{product_id}` endpoint
- **Day 6**: Cold-start fallback logic, unit tests

### Phase 4 — Chatbot with live cart/order tools (Days 7–9)
- **Day 7**: Agent skeleton wired to `llama3.2:3b` via Ollama, handling only
  the queries the routing heuristic sends to the AI path (ambiguous, ⁣multi-turn,
  comparison) — not simple filterable queries, which stay on the fast path.
  **Sanity-check tool-selection accuracy here before building further** — if shaky, this is the moment to reconsider the model.
- **Day 8**: Tool definitions (`search_products`, `check_stock`, `add_to_cart`, `order_status`)
- **Day 9**: Conversation memory, integration test script (10 queries, correct tool selection)

### Phase 5 — Chat frontend & UX (Days 10–12)
*Least overlap with your existing portfolio — budget the most attention here.*
- **Day 10**: Chat widget UI, SSE streaming
- **Day 11**: Structured product-card rendering inside chat (often the hardest day — budget 2 sessions if needed)
- **Day 12**: Mobile responsive pass, loading/error states

### Phase 6 — Testing & optimization (Days 13–14)
- **Day 13**: Playwright e2e tests (desktop + mobile), latency measurement, caching
- **Day 14**: Adversarial/prompt-injection testing, bug fixes

### Phase 7 — Documentation & case study (Day 15)
- **Day 15**: Hand-off README, architecture diagram, client-facing case study write-up, publish as open source

---

## Pacing note

At 3–4 hrs/day, treat the numbers above as **sessions**, not calendar days —
Days 8, 9, and 11 commonly need 2 sessions each. Realistic total: **~4 weeks**
at your pace, working ~5 days/week. Don't compress Day 2 or Day 15 to save
time — those two non-code deliverables are what make this read as a real
engagement rather than a tutorial clone.

---

## Working with Claude Code each day

1. Open the session with `CLAUDE.md` in the repo root — it's read automatically
2. Give Claude Code that day's single target from the plan above, not the whole week
3. Ask for tests before implementation on the agent/recommendation logic
4. Review every diff before accepting
5. Commit at the end of the session with a message matching the day's target
