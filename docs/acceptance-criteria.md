# Acceptance criteria

Mirrors the acceptance criteria from the original freelance-style brief this
practice project is modeled on, made concrete and measurable for this build.

## 1. Reliability

- [ ] All services (backend, Qdrant, Ollama, frontend) start cleanly via
      `docker compose up`
- [ ] Health-check endpoints (`/health`, `/health/qdrant`, `/health/ollama`)
      return `ok` before any feature is considered working
- [ ] The fast filter path never depends on the AI path being available &mdash;
      structured search keeps working even if the LLM is down

## 2. Accuracy

- [ ] Structured filter queries return only products matching the stated
      filters (category, price range, boolean attributes) &mdash; no false
      positives
- [ ] AI-path responses are grounded in live catalog data (price, stock)
      fetched at answer-time, never from the model's own memory
- [ ] A 10-query test set (built on Day 9) correctly routes each query to the
      right path and selects the right tool

## 3. Performance

- [ ] Fast filter path responds in under 300ms
- [ ] AI path responds in under 5 seconds on CPU-only local inference
      (looser than a typical 2&ndash;3s cloud-API target, reflecting the
      cost/latency trade-off of local, free inference &mdash; documented
      explicitly rather than hidden)
- [ ] Chat UI streams tokens as they arrive rather than waiting for the full
      response

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
