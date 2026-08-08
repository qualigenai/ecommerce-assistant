# AI-powered e-commerce assistant — practice project

## Goal
Build a practice AI shopping assistant (smart search, product recommendations,
conversational chatbot) on a demo e-commerce catalog, following the same
deliverables as a real freelance engagement: audit, toolset recommendation,
implementation, testing, hand-off documentation. This is a portfolio case
study — code quality and documentation matter as much as functionality.

## Constraints
- 100% open source stack, no paid vendor APIs
- LLM: Ollama running llama3.2:3b locally (already installed, not containerized —
  runs natively on Windows host, reachable at http://localhost:11434)
- Everything else runs in Docker via docker-compose

## Tech stack
- Frontend: Next.js + Tailwind CSS
- Backend: FastAPI (Python)
- Vector DB: Qdrant (Docker container)
- Embeddings: sentence-transformers `all-MiniLM-L6-v2` (local, via Python)
- Agent/orchestration: LangChain, tool-calling against llama3.2:3b via Ollama
- Database: SQLite for dev
- E2E testing: Playwright
- Dev partner: Claude Code (this session)

## Folder conventions
- `/backend` — FastAPI app, catalog CRUD, embeddings pipeline, agent + tools
- `/frontend` — Next.js app, chat widget, product pages
- `/docs` — audit.md, acceptance-criteria.md, hand-off README, case study
- `/tests` — pytest (backend), Playwright (e2e)

## Working style
- Small, reviewable diffs — one day's target per session, not the whole plan
- Tests before implementation where practical, especially for tool-calling
  and recommendation logic
- Commit at the end of each session with a message matching that day's target

## Current phase
Day 1 — repo & environment setup. Target: `docker-compose up` runs Qdrant +
FastAPI with health checks passing, Next.js scaffold with seed catalog loads,
Ollama reachable from FastAPI container.
