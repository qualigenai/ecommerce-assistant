# Acceptance criteria

Mirrors the acceptance criteria from the original freelance-style brief this
practice project is modeled on, made concrete and measurable for this build.

## 1. Reliability

- [ ] All services (backend, Qdrant, Ollama, frontend) start cleanly via
      `docker compose up` &mdash; **wording doesn't match current
      architecture**: `docker compose up` starts backend + Qdrant only;
      Ollama runs natively on the host (verified live, Day 12: reachable
      and healthy independent of Compose); no frontend exists yet
      (Day 14+). Left unchecked and unreconciled on purpose until the
      frontend is actually built, per Day 12 discussion &mdash; rather than
      quietly reinterpreting the box to make it pass.
- [x] Health-check endpoints (`/health`, `/health/qdrant`, `/health/ollama`)
      return `ok` before any feature is considered working &mdash; verified
      live (Day 12, `reliability_check.py`): all three return `ok`.
- [x] The fast filter path never depends on the AI path being available &mdash;
      structured search keeps working even if the LLM is down &mdash; verified
      live (Day 12): with Ollama deliberately stopped, `/search` still
      returned correct results in 10.0ms; `/chat` failed *honestly*
      instead of hanging &mdash; BUG-012's fallback fired at the ~60s httpx
      timeout, confirming that guarantee under a real failure, not a
      simulated one.

## 2. Accuracy

- [x] Structured filter queries return only products matching the stated
      filters (category, price range, boolean attributes) &mdash; no false
      positives &mdash; verified live (Day 12, `accuracy_check.py`): four
      filter combinations checked against every returned product
      individually, zero violations.
- [x] AI-path responses are grounded in live catalog data (price, stock)
      fetched at answer-time, never from the model's own memory &mdash;
      verified live (Day 12): asked `/chat` for a real product's price
      and stock, independently fetched the true values via `/search`,
      and the reply's numbers matched exactly ($89.99, 42). Also
      confirmed the honest-refusal case: asked about a nonexistent
      product, got an honest "no product found," not a fabricated price.
- [x] A 10-query test set (built on Day 9, `tests/integration_test_agent.py`)
      exercises each tool/path and conversation memory across two turns —
      pass rate depends on live model behavior each run, not a one-time
      guarantee; re-run after any future change

## 3. Performance

- [x] Fast filter path responds in under 300ms &mdash; measured live (Day 10):
      6.8&ndash;8.8ms (`/search`), 21.7&ndash;24.1ms (`/assistant/search`,
      routed). See `docs/bug-log.md`, BUG-004.
- [x] AI path (semantic retrieval only) responds in under 5 seconds &mdash;
      measured live (Day 10): 78&ndash;82ms (`/assistant/search`, semantic
      branch). Retrieval was never the bottleneck; see BUG-004.
- [ ] `/chat`'s full generative reply responds in under 5 seconds &mdash;
      **not met as originally written**. Measured live (Day 10):
      31.6&ndash;52.6s for a single-tool request, 12.4&ndash;33.1s for a
      compound request &mdash; driven entirely by CPU-only 3B-model
      generation time (the natural-language final-answer round), not by
      retrieval, routing, or tool execution, all of which pass their own
      targets above. A 5s full-reply target was never achievable for
      open-ended generation on this hardware/model combination without
      abandoning the project's open-source, self-hostable, no-paid-API
      goal. Revised target, pending the streaming item below:
      time-to-first-token under 5s, full-reply latency tracked but not
      gated. See `docs/bug-log.md`, BUG-004 (root-caused, Day 10) and
      LIMITATION-003 (conversation-history growth compounds this further
      on turn 2+).
- [ ] Chat UI streams tokens as they arrive rather than waiting for the full
      response &mdash; now the direct, load-bearing fix for the item above:
      turns an unmet full-reply latency target into a met
      time-to-first-token target, without requiring a larger or
      GPU-backed model.

## 4. Security & code quality

- [ ] No secrets or API keys committed to Git (`.gitignore` covers `.env`)
- [ ] User input sanitized before being passed to the LLM
- [ ] Basic rate limiting on AI-path endpoints
- [ ] Code reviewed (diff-by-diff with Claude Code) before each daily commit

## 5. UX

- [ ] Chat widget usable on both desktop and a simulated mobile viewport
- [ ] Responses render as conversational text plus product cards (image,
      price, add-to-cart), not plain text
- [ ] Empty, loading, and error states are all handled, not just the happy path

## 6. Documentation

- [ ] Hand-off README written for a non-technical reader
- [ ] Architecture diagram included
- [ ] Case study write-up completed (problem, approach, stack, results)

---

**Definition of done for the project overall**: every checkbox above is
checked, and a person with no involvement in the build could follow the
hand-off README to run the project and understand what it does.
