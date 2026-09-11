# Bug log

Numbered, traceable record of real issues found during testing — not a
design-decision log (that's what the trust-comment templates in the code
are for). Each entry here is something that was actually broken, found via
live testing, not a hypothetical.

Code comments reference these IDs directly (e.g. `# BUG-001 fix`) so the
full context is one lookup away instead of restated inline everywhere.

---

## BUG-001 — Waterproof filter silently matched nothing

- **Found**: Day 7, live testing of `/chat`
- **Severity**: High — agent told a customer no matching products existed when two actually did
- **Component**: `agent.py`, `_execute_tool()`
- **Symptom**: `/chat` query for "waterproof hiking boots under $100" returned 0 results despite 2 real matches in the catalog
- **Root cause**: Ollama's tool-calling returned arguments as strings (`"waterproof": "true"`) despite the schema declaring `boolean`/`number`. `_execute_tool()` passed these straight through to `crud.search_products()`, where `attributes.get("waterproof") == waterproof` compared a real Python `True` to the string `"true"` — always `False`, silently excluding every product.
- **Fix**: Added `_coerce_float()` and `_coerce_bool()`, applied to every tool argument before it reaches `crud.search_products()`.
- **Verified**: Reproduced the exact string-typed arguments from the failing log and confirmed the fixed code returns the correct 2 products.
- **Status**: Fixed and verified live — confirmed via a real /chat call returning the correct 3 products (BOOT-004, BOOT-001, BOOT-999) with correctly typed arguments.

## BUG-002 — Telemetry result_count logged the wrong number

- **Found**: Day 7, comparing `/chat` response against `/telemetry/recent` for the same query
- **Severity**: Medium — the observability log itself was misleading, which undermines the trust framework's own Governance pillar
- **Component**: `main.py`, `/chat` endpoint
- **Symptom**: Telemetry showed `"result_count":1` for a query that found 0 real products
- **Root cause**: `result_count` was set to `len(result["tool_calls"])` (number of tool calls made, almost always 1) instead of the actual number of products those calls returned — inconsistent with every other path (`filter`, `ai`, `recommend`), where `result_count` always means real results.
- **Fix**: Changed to sum `result_count` across each entry in the tool-call trace.
- **Status**: Fixed. Pending live re-test.

## BUG-003 — Model inverted price_lt / price_gt

- **Found**: Day 7, live testing of `/chat`
- **Severity**: Medium — LLM reasoning limitation, not a code defect
- **Component**: `llama3.2:3b` tool-call reasoning (model behavior, not our code)
- **Symptom**: "under $100" produced `price_gt: 100` instead of `price_lt: 100`
- **Root cause**: Small local models are measurably less reliable at mapping natural-language comparison direction to the correct tool parameter.
- **Fix**: Mitigation, not a guaranteed fix — added explicit examples to the tool schema descriptions and system prompt ("under $X" -> `price_lt`, "over $X" -> `price_gt`). This reduces the error rate but does not eliminate it, since the model can still occasionally get it wrong.
- **Status**: Mitigated. Not independently verifiable without repeated live testing across many phrasings — worth tracking the error rate over time rather than treating this as closed.

## BUG-005 — Model injects unrequested filter values

- **Found**: Day 7, live testing of `/chat` (query: "Do you have any tents under $200?")
- **Severity**: Medium — LLM over-specification, not a code defect. Same customer-facing symptom as BUG-001 (false "no results") but a different root cause.
- **Component**: `llama3.2:3b` tool-call argument generation (model behavior, not our code)
- **Symptom**: Customer asked only about tents under $200 (no mention of waterproofing). Model's tool call included `"waterproof":"false"` anyway, which correctly (and precisely) excluded 2 real matching tents (`TENT-001` $189.99, `TENT-002` $159.99 — both `waterproof:true`) that never should have been filtered out.
- **Root cause**: The model fabricated a value for a parameter the customer never mentioned, rather than omitting it. Confirmed this is NOT a coercion failure — BUG-001's fix correctly turned the string `"false"` into a real Python `False`; the bug is the model deciding to send that field at all.
- **Fix**: Mitigation via prompt — explicit instruction to omit any parameter not stated by the customer, rather than guessing a value.
- **Status**: Mitigation applied, not independently verifiable without repeated live testing across many phrasings (same caveat as BUG-003). Worth tracking how often this recurs.

---

## BUG-007 — add_to_cart couldn't resolve a product name to a real ID within one turn

- **Found**: Day 8, live testing of `/chat` ("Add the Trailhead Waterproof Hiking Boot to my cart", "Add 10 QuickBoil Backpacking Stoves to my cart")
- **Severity**: High — add_to_cart was effectively unusable for a natural first-time request, since customers only ever provide a product name, never a numeric ID
- **Component**: `agent.py`, `run_agent()` — single-hop tool-calling architecture
- **Symptom**: Model called `add_to_cart` with a fabricated `product_id` (`"null"` as a string, then `101`, neither real) instead of first looking the product up
- **Root cause**: `run_agent()` performed exactly one round of tool-calling, then disabled tools for the follow-up completion. The model had no way to call `search_products` first, see the real ID, and then call `add_to_cart` — it got one shot, and guessed when it lacked the ID it needed.
- **Positive finding**: Despite the architecture gap, BUG-001's type coercion and the existence check in `_tool_add_to_cart` both caught the fabricated IDs correctly — neither failing test produced a false "added to cart" confirmation. The trust guardrails held even while the orchestration was incomplete.
- **Fix**: Rewrote `run_agent()` as a bounded loop (`MAX_TOOL_ITERATIONS = 4`) — tools stay enabled across rounds, so the model can search, see a real ID, then act on it, all within one customer turn. Capped to guarantee the turn always terminates even if the model keeps requesting tools.
- **Verified**: Simulated the exact search-then-add_to_cart chain with mocked model responses — confirmed the loop correctly passes the real ID from the search result into the add_to_cart call, and confirmed the iteration cap forces a plain-text answer after 4 rounds rather than looping indefinitely.
- **Status correction (Day 8, later same day)**: The simulation only proves the loop *mechanics* are correct given scripted responses — it does NOT prove the real llama3.2:3b model will reliably choose to chain search_products -> add_to_cart on its own. Live testing of the actual compound request ("Find the Trailhead Waterproof Hiking Boot and add it to my cart") returned `{"reply":"", "tool_calls":[]}` after 76.5s — the model produced neither a tool call nor any text. This is a distinct failure mode, not the fabricated-ID failure this fix targeted. Downgrading status accordingly.
- **Further observation (Day 8, after BUG-009's fix)**: retested with quantity specified ("...and add 2 of them to my cart") — result was worse, not better: the model sent completely empty search arguments (`query:""`, all filters zeroed), unlike every simpler test where it correctly populated `query` with the product name. This suggests instruction complexity itself degrades this model's argument quality, not just its willingness to chain tool calls — a sharper hypothesis than "the model wants quantity confirmation first."
- **Decisive test**: "Find the Trailhead Waterproof Hiking Boot and add 1 to my cart" — explicit product name, explicit quantity, no ambiguity left to resolve. `search_products` was called correctly (5 results, real product found), but `add_to_cart` was never called — the reply instead asked "Would you like to add this to your cart?", directly contradicting a request that already said "add it." This rules out quantity ambiguity and points at prompt-level ambiguity instead: "never add something on their behalf without explicit confirmation" may read to a small model as "always ask before adding," and neither tool description previously stated that search_products' result should feed into add_to_cart.
- **Fix (Day 8, controlled experiment)**: Single-variable change — SYSTEM_PROMPT and add_to_cart's tool description rewritten to (1) state an explicit add-to-cart request already IS confirmation, no second ask needed, and (2) give an explicit worked example of the search-then-act chain. No code, loop, or tool logic touched, to isolate whether this was a prompt-level gap before considering anything architectural.
- **Further live evidence (Day 8, after BUG-010's fix)**: same canonical request produced yet another distinct failure shape: `add_to_cart` was called (progress — the model did attempt to chain), but with `product_id:"search_products"` — the model confused the **name of the other tool** with the product ID it was supposed to extract from that tool's result. `_tool_add_to_cart`'s existing validation correctly rejected this (`success:false`, `error:"Invalid product_id: 'search_products'"`), and the reply was honest ("I need to find the Trailhead Waterproof Hiking Boot first"). No fabrication — BUG-011's safety boundary held.
- **Evidence summary across all observed variants**:

  | Model behavior | Outcome |
  |---|---|
  | `product_id=1` (real ID) | ✅ add_to_cart works correctly |
  | `product_id="null"` | ❌ rejected safely |
  | `product_id=101` (fabricated number) | ❌ rejected safely |
  | `product_id="search_products"` | ❌ rejected safely — confuses tool identity with a product ID |
  | No add_to_cart call at all, claims success in text | ❌ was the BUG-011 fabrication; now blocked |
  | No add_to_cart call at all, asks for confirmation | 🟡 safe but incomplete |

  Every failure mode has been safe — the tool-execution layer has never once produced an incorrect cart state. The unresolved problem is entirely in the model's ability to reliably extract and pass a real ID from one tool's result into another tool's call — a tool-chaining/grounding reliability limit at this model size, not a gap in the application.
- **Final controlled experiment (Day 8)**: added an explicit sentence to SYSTEM_PROMPT ruling out tool names, "null," and made-up numbers as `product_id`, and instructing the model to wait for `search_products`' result before calling `add_to_cart`. Single variable, no code touched. Result: `search_products` was called correctly (5 results), but `add_to_cart` was not called at all this time — a different failure shape than any of the three prior variants (fabricated ID, "null," or the tool-name confusion), but still not a successful chain. BUG-011's guard correctly returned the honest fallback rather than any fabricated success.
- **Conclusion**: three distinct, increasingly explicit prompt experiments have now been tried — (1) removing the "ask for confirmation" ambiguity, (2) an explicit worked example of the search-then-act chain, (3) an explicit rule against placeholder IDs. Each produced a different failure shape, never a reliable success. This pattern — the failure mode changing shape under prompt pressure rather than resolving — is itself evidence that the ceiling is the model's grounded multi-step tool-chaining capability at 3B scale, not a specific wording gap that a fourth prompt attempt would close.
- **Decision**: per the agreed plan, stopping prompt iteration here. BUG-007 is closed as a **documented model-capability limitation**, not marked "Fixed." The resolution path is architectural, not further prompting: a deterministic fallback / multi-step confirmation flow (e.g., the application itself resolves the product ID from a completed search before ever proposing an add-to-cart action to the model, rather than relying on the model to extract and pass it correctly) — a natural fit for Day 9's conversation-memory work, where the search result can persist across turns instead of needing to be perfectly chained within one.
- **What Day 8 actually delivered here, worth stating plainly**: the tool-execution and response-grounding layers have proven completely safe across every observed failure variant — not one of them ever produced an incorrect cart state or a fabricated confirmation. The limitation is narrow and well-understood, not a general reliability problem with the system.
- **Status**: Closed as a documented model-capability limitation. Not "Fixed" — the underlying chaining behavior was never resolved, only safely contained. Revisit architecturally on Day 9.

## BUG-008 — Model returns neither a tool call nor text on a compound request

- **Found**: Day 8, live testing of `/chat` ("Find the Trailhead Waterproof Hiking Boot and add it to my cart")
- **Severity**: High — worse than a wrong answer, this is a blank one. An empty string reaching a real customer is a hard failure of the whole point of the assistant.
- **Component**: `agent.py`, `run_agent()`'s loop-exit condition, and `llama3.2:3b`'s response to compound instructions
- **Symptom**: `{"reply":"", "tool_calls":[]}` after 76.5s — the model's message had neither `tool_calls` nor non-empty `content`
- **Root cause — not yet confirmed, two candidates**:
  1. **Model limitation**: a 3B model may not reliably parse "find X and add it to my cart" as a two-step plan requiring sequential tool calls, especially compared to the single-action requests that worked (plain search, plain stock check, plain order lookup — all confirmed working live before this).
  2. **Code gap**: `run_agent()`'s current exit condition (`if not tool_calls: return`) treats *any* absence of tool calls as "the model is done," even when the model's content is also empty. That's not "done," that's an anomaly, and the code currently can't tell the difference.
- **What this does NOT change**: the standalone add_to_cart test (fabricated `product_id: "null"`) is still correctly understood — that failure mode is unrelated and still confirms the model has no real ID without a prior search, which is exactly why the multi-round loop was built in the first place. This finding doesn't undermine that reasoning, it surfaces a second, separate gap on top of it.
- **Fix**: Parts A, B, C implemented — (A) the loop no longer treats empty-tool-calls-and-empty-content as completion, it nudges once and continues, bounded by the existing `MAX_TOOL_ITERATIONS`; (B) the forced final answer now has a hard, honest fallback message if it too comes back empty — a blank string can never reach a customer; (C) `/chat`'s telemetry now flags a functionally empty reply as `success:false`, not just exceptions. Part D (prompt tightening) deliberately left untouched, per decision, to isolate whether the code fix alone resolves the live failure before changing the prompt as a second variable.
- **Verified**: Reproduced the exact live failure (round 1 returns empty tool_calls + empty content, matching the real log) via a simulated model response sequence — confirmed the loop now recovers via the nudge and successfully completes the search -> add_to_cart chain. Separately confirmed the hard fallback fires with an honest message when the model never recovers across all iterations. Full regression suite (Day 6's 4 tests, plus BUG-001/BUG-006 spot checks) still passes.
- **Status**: Fixed and verified via simulation. **Confirmed live** (Day 8, same day) — re-running the exact same compound request produced a real, non-blank reply with a genuine tool call, no nudge even needed that time.

## BUG-009 — Placeholder default values (0, "") wrongly treated as real filters

- **Found**: Day 8, live re-test of the compound request after BUG-008's fix
- **Severity**: High — search silently returns zero results for a product that genuinely exists, in a way that looks identical to a real "not found" case
- **Component**: `agent.py`, `_tool_search_products()`
- **Symptom**: Tool call included `category:""`, `price_gt:0`, `price_lt:0` alongside a correct `query` field. The old `has_filters` check treated any non-`None` value as a real filter, so it took the structured path with a self-contradictory `price_lt:0 AND price_gt:0` — a condition no real product can satisfy — guaranteeing zero results regardless of the actual query.
- **Root cause**: `_coerce_float("0")` correctly turns a placeholder into a real `0.0` (BUG-001 working as designed) — the gap was one level up: nothing distinguished a meaningful zero/empty value from a placeholder one before deciding a real filter was requested.
- **Fix**: Two changes, applied together per team decision: (1) normalize placeholders before any routing decision — empty-string `category` and non-positive price bounds become `None`; `waterproof` is deliberately kept, since a real customer statement like "waterproof hiking boot" is genuine signal, not a placeholder (consistent with BUG-005's precedent). (2) Gate the structured-filter path on `category` presence specifically, mirroring the same principle `routing.py` already applies at the Day 4 routing layer — a category is a strong signal, a bare price/waterproof value alone is not enough to skip semantic understanding.
- **Scope boundary, explicitly deferred**: hybrid filtering (applying price/waterproof as a filter *on top of* semantic search results) was deliberately left out of this fix — see LIMITATION-001 below.
- **Verified**: Reproduced the exact bad arguments from the live log (mocked embeddings, since this sandbox can't reach Hugging Face) — confirmed the real product is now found via the semantic path instead of returning zero results. Also re-verified structured filtering (BUG-001), the BUG-005 no-phantom-filter scenario, pure semantic search, and two additional edge cases (empty category alone, everything empty) — all correct. Full Day 6 regression suite (4 tests) still passes.
- **Status**: Fixed and verified in isolation. Pending live re-test.

## BUG-006 — result_count was still inconsistent for tools that returned errors as list items

- **Found**: Day 8, live testing of `/chat` (order ORD-5555, unknown order)
- **Severity**: Medium — a recurrence of BUG-002's underlying lesson (observability must mean what it claims), surfaced in a new layer
- **Component**: `agent.py` — every `_tool_*` function and `_execute_tool()`'s trace-building
- **Symptom**: `order_status` for an unknown order correctly replied "not found," but `result_count` still showed `1`
- **Root cause**: No consistent contract across tool functions for what to return on failure. `search_products`/`check_stock` returned `[]` when nothing was found (correct). `add_to_cart`/`order_status` returned a single-item list containing an error object instead, so `len(result)` was always `1` regardless of success or failure for those two tools.
- **Fix**: Every tool function now returns a consistent `{"success": bool, "results": [...], "error": str|None}` via a shared `_tool_result()` helper. `result_count = len(results)`, always `0` on any genuine failure, everywhere. Trace entries also now carry a per-tool `success` flag, not just a per-turn one.
- **Verified**: Unit-tested `order_status` on an unknown ID and `add_to_cart` on insufficient stock — both confirmed `results: []` on failure. Full Day 6 regression suite (4 tests) still passes after the rewrite.
- **Status**: Fixed and verified in isolation. Pending live re-test.

## BUG-013 — Model writes a tool call out as literal text instead of issuing a real one

- **Found**: Day 9, live testing of `/chat` (category-browse and compound "find + add" requests)
- **Severity**: High — a new, third failure shape distinct from anything previously catalogued: the model produces a JSON-shaped blob describing a tool call, but never calls the tool, and that blob reaches the customer verbatim as if it were the answer
- **Component**: `agent.py`, `run_agent()`'s loop-exit condition — the same "no tool_calls" branch BUG-008 already hardens, but against a different symptom
- **Symptom**: `tool_calls: []` with non-empty `content` shaped like `{"name":"search_products","parameters{"category":"","query":"Trailhead Waterproof Hiking Boot","waterproof":null}}` — note the malformed JSON (missing colon after `"parameters"`). Prior code treated any non-empty `content` with empty `tool_calls` as "the model has a final answer" and returned it straight to the customer.
- **Root cause**: Ollama's tool-calling parser didn't recognize the model's output as a real tool call, so it fell through as plain chat content. The existing empty-content check (BUG-008) only catches a *blank* reply — it has no way to recognize a *non-blank* reply that is actually a broken tool-call attempt, not a real answer.
- **Distinction from prior bugs**:
  - BUG-008 = model returns nothing at all (empty content, empty tool_calls)
  - BUG-011 = model fabricates a success claim in natural language
  - BUG-013 = model produces a garbled JSON blob that isn't natural language at all, and it reaches the customer unmodified — a real UX/trust problem in its own right (unprofessional at best, a minor internal-schema information leak at worst)
- **Fix**: Added `_looks_like_tool_call_json()` — a narrow heuristic requiring the content to start with `{` AND mention both `"name"` and a `parameters`/`arguments` key, to avoid false-positiving on a legitimate answer that happens to start with a brace or mention those words in prose. Reuses BUG-008's exact nudge-and-continue mechanism rather than introducing new architecture: content matching this shape is treated the same as empty content was already treated — not a valid final answer, so nudge once and retry within the existing bounded loop (`MAX_TOOL_ITERATIONS`). Applied at both checkpoints in `run_agent()` — the per-round completion check and the forced-final-answer path after the iteration cap — so the same leak can't occur at either exit point.
- **Verified**: Detector tested against the exact malformed example from the live log (missing colon and all) plus a well-formed `"arguments"`-keyed variant — both correctly caught; three legitimate replies (a normal offer, a reply starting with an unrelated brace, a reply that mentions "name" and "parameters" conversationally without being JSON-shaped) confirmed no false positives. Full end-to-end loop simulated: round 1 malformed JSON → nudge → round 2 real `search_products` call → round 3 clean final answer, matching the recovery observed live. Regression-checked against BUG-011 (fabricated-claim guard still fires correctly) and BUG-008 (genuine empty-content nudge still fires correctly). Worst case also verified: if the model emits the malformed pattern on every round, including the forced final call, the existing hard fallback fires and no raw JSON ever reaches the customer.
- **Status**: Fixed and verified.

---

## Open, not yet fixed

## BUG-011 — Model claims add_to_cart succeeded without ever calling the tool

- **Found**: Day 8, live re-test of the BUG-007 prompt-only experiment ("Find the Trailhead Waterproof Hiking Boot and add 1 to my cart")
- **Severity**: Critical — this is a fabricated confirmation of a transactional action, the worst category of failure this project's trust framework exists to prevent. A real customer would believe an item was added to their cart when it was not.
- **Component**: model output generation (`llama3.2:3b`'s final-answer text), not tool execution — every existing guardrail (BUG-001 coercion, BUG-006 success/error structure, existence checks) protects against the model calling a tool *incorrectly*; none of them protect against the model **not calling a tool at all** and narrating success anyway.
- **Symptom**: `tool_calls` contains only `search_products` — `add_to_cart` was never invoked. The reply states "I have added 1 to your cart... Your cart now contains 1 item," which is entirely fabricated; `_MOCK_CART` was never touched.
- **Root cause — confirmed via diagnostic round-by-round logging**: added temporary `[AGENT DEBUG]` prints to `run_agent()` showing each round's raw model content and tool calls. Round 1 correctly called `search_products` (real product found). Round 2 showed `tool_calls=[]` with content directly asserting "I have added 1 ... to your cart" — confirmed on the real `llama3.2:3b` model, not just a scripted simulation. A control test ("find X" with no add request) correctly did NOT fabricate a claim, narrowing this to specifically transactional-intent requests, not generic unreliability. This is a final-response grounding gap, not an agent-loop or tool-execution defect — ruled out both of those via the same evidence.
- **What this confirms about the architecture**: `agent.py`'s own original design comment anticipated exactly this gap — the system prompt's "never invent" instruction was always described as "a soft constraint... a first line of defense, not a substitute for" a hard groundedness check. This is the case that hard check was meant to catch.
- **Fix**: A table-driven `TRANSACTIONAL_TOOLS` registry plus a grounding guard (`_reply_claims_unverified_transaction`, `_build_grounding_fallback`, `_finalize_reply`) that both return paths in `run_agent()` (normal completion and the forced-final-answer path) are routed through. Keywords are past-tense/completion-specific ("i have added," "cart now contains") to avoid false-positiving on legitimate offers/questions ("would you like to add..."). The fallback preserves what was actually found (from the last successful `search_products`/`check_stock` call in the trace) rather than collapsing to a generic error — explicitly distinguishing "I found X" from "I changed something" for the customer. Adding a future transactional tool (`remove_from_cart`, `place_order`, ...) requires only a new registry entry, no new branching logic.
- **Verified**: All 6 acceptance criteria confirmed — (1) the exact real `llama3.2:3b` failure from the live logs is now correctly blocked with an honest, product-preserving fallback; (2) a genuinely verified `add_to_cart` success passes through completely unchanged; (3) all 3 real observed offer/question phrasings ("would you like to add...") do NOT false-positive; (4) a mock future tool added via registry entry alone is correctly guarded with zero new branching; (5) the forced-final-answer path (after hitting `MAX_TOOL_ITERATIONS`) is also guarded, confirmed by forcing the cap; (6) full regression suite (4/4 pytest tests) plus BUG-001/BUG-006/BUG-009 spot-checks all still hold.
- **Known limitation, accepted deliberately**: this is keyword-based, not true language understanding. It closes the specific, observed, reproduced failure — it is not a guarantee against every conceivable phrasing of a fabricated claim. Documented explicitly as a containment layer, not a substitute for the model behaving correctly.
- **Live re-test (Day 8)**: "Find the Trailhead Waterproof Hiking Boot in the catalog" (search-only) confirmed criterion 3 live — correct offer phrasing, not flagged. But "...and add 1 to my cart" produced a near-miss: `add_to_cart` was still never called, and the reply said "I will add 1 pair to your cart... Would you like to continue shopping or checkout?" — future tense, not the past-tense "I have added" the keyword list targets, so it evaded `TRANSACTIONAL_TOOLS` entirely. Practically as misleading as the original fabrication (the "checkout" framing implies the item is already in the cart), just phrased differently. This is the accepted keyword-matching limitation manifesting as a real, observed case, not a hypothetical.
- **Keyword extension (Day 8)**: added `"i will add"` and `"i'll add"` to `TRANSACTIONAL_TOOLS["add_to_cart"]["keywords"]` to catch the future-tense fabrication observed live. Re-verified against: (1) the exact real future-tense reply from the live log — now correctly blocked; (2) the original past-tense fabrication — still correctly blocked, no regression; (3) all 3 real observed offer/question phrasings — still correctly pass through unchanged. Full pytest suite (4/4) still passes.
- **Documented trade-off, verified rather than assumed**: explicitly tested the conditional-offer case named as a concern before implementing — `"I will add it once you confirm the size."` **is also blocked** by this keyword addition, even though it's a genuine pending offer, not a fabrication. This was anticipated and accepted as a deliberate trade-off rather than an unknown risk: the keyword is inherently coarser than true intent, and this is the concrete cost of that coarseness. Not fixed in this pass — flagged as a candidate for the structural check below.
- **Longer-term direction, explicitly deferred, not started**: a structural check — "did the reply presume a cart mutation happened (e.g. references a total, offers checkout) AND was the corresponding tool actually executed successfully" — would be more precise than enumerating phrases, and is the natural next evolution of this guard. Not pursued now; today's fix is a targeted containment patch, consistent with the project's established pattern of fixing the observed, reproduced failure first rather than redesigning ahead of evidence.
- **Status**: Fixed and verified against both known fabrication phrasings (past-tense and future-tense) with no regression on genuine offers, plus the conditional-offer trade-off explicitly tested and documented rather than left as a surprise. Pending final live confirmation on the user's machine.

## BUG-010 — Category presence gate trusts any non-empty value, including hallucinated ones

- **Found**: Day 8, live testing of BUG-009's fix (Tests 2 and 5 of the 5-test verification sequence)
- **Severity**: High — a direct regression on a scenario that previously worked correctly (Day 4's original `/assistant/search` handled "something for a rainy weekend camping trip" correctly; this same query now fails via `/chat`)
- **Component**: `agent.py`, `_tool_search_products()` — the category gate added by BUG-009's fix
- **Symptom, two forms of the same root cause**:
  1. **Test 5**: model called with `category:"Camping Gear"` — not a real category anywhere in the catalog. The gate trusted it as real, took the structured path, matched nothing, and completely discarded the good semantic query that would have found relevant products (tents, rain jackets).
  2. **Test 2**: model called with `category:"Hiking Boots"` (a real category) alongside a specific `query` ("Trailhead Waterproof Hiking Boot"). The gate correctly took the structured path, but the query text was discarded entirely, returning all 6 boots in the category instead of the 1 specific product the customer named.
- **Root cause**: BUG-009's fix correctly gated on "is category present," but never validated *whether the category is real*, and never considered using the query as a secondary narrowing signal even when category is genuinely valid. "Non-empty" and "trustworthy" were treated as the same thing — they aren't, for a value that comes from the model rather than the customer directly.
- **Related debt already flagged elsewhere**: `routing.py`'s own `CATEGORIES` list carries a comment acknowledging it's manually maintained and would ideally be queried from the catalog in production. The same gap applies here — worth fixing both from a single real source rather than hardcoding a second list.
- **Proposed fix (not yet applied)**: Validate `category` against the catalog's actual distinct categories (queried from the database, not a hardcoded list — avoids the exact staleness risk `routing.py` already flags about itself) before trusting it as a gate. An unrecognized category normalizes to `None`, same treatment as an empty string. Test 2's remaining precision-loss (real category + specific query both present) is a separate, deeper question — folded into LIMITATION-001 below rather than fixed here, since it's genuinely a hybrid-search feature gap, not a validation bug.
- **Fix**: Implemented `_get_known_categories(db)`, querying `SELECT DISTINCT category FROM products` directly — a single source of truth, never a second hardcoded list to drift out of sync. `_tool_search_products()` now validates `category` (case-insensitively) against this real set before treating it as a gate; an unrecognized value normalizes to `None` and falls through to the existing query/filter-only gates, exactly like an empty string does.
- **Verified**: 6 scenarios — the known-categories helper returns the correct real set; a valid category ("Hiking Boots") still filters correctly (no BUG-001 regression); case-insensitive matching works ("hiking boots" still matches); the exact original BUG-010 failure ("Camping Gear" + a good query) now correctly falls through to the semantic path instead of zeroing results; pure semantic search with no category is unchanged; filter-only fallback (no category, no query) is unchanged. Separately re-confirmed BUG-011's grounding guard is completely unaffected — both fabrication phrasings (past and future tense) still blocked, genuine offers still pass through, and a genuinely verified success still passes through unchanged. Full pytest suite (4/4) still passes.
- **Live confirmation (Day 8)**: "Something for a rainy weekend camping trip" now returns 3 genuinely relevant real products (StormShield tent, Storm Guard rain pack, Basecamp pack) instead of zero — the semantic path is no longer being blocked by a hallucinated category. "Do you have waterproof hiking boots under $100?" (valid, real category) still correctly filters to the right 2-3 products — no regression on the structured path.
- **Status**: Fixed — confirmed via unit-level verification AND live testing with the real model on both the original failing scenario and the regression-check scenario.

## BUG-004 — /chat latency exceeds the Day 2 acceptance criteria

- **Found**: Day 7, live testing
- **Severity**: Medium — a real, measured gap against a written acceptance criterion, not a correctness bug
- **Component**: `agent.py`, `run_agent()` — two sequential CPU-only model inference passes per request
- **Symptom**: 8.1s and 26.8s observed, against a 5s target in `docs/acceptance-criteria.md`
- **Root cause**: One inference pass to decide the tool call, a second to generate the final answer from the tool result — both run on CPU with no GPU.
- **Update (Day 8)**: BUG-007's fix (a bounded multi-round tool-calling loop) very likely makes this worse for compound requests specifically — a request needing search_products then add_to_cart now costs up to 3 inference passes instead of 2. Simple single-tool requests are unaffected. Needs live re-measurement, not assumption, once BUG-007 is confirmed live.
- **Update (Day 8, BUG-009 verification)**: a single-tool-call request ("find the Trailhead boot") took 128.4s — the highest number observed yet, on a request that should have been simple. Not yet confirmed whether this was a cold-start cost (first call after a restart) or a genuine new data point. Needs a repeat measurement under known-warm conditions before drawing a conclusion.
- **Update (Day 10) — real, warm-condition measurements finally taken**: Built `measure_latency.py`, instrumented `agent.py` to time each model call and tool execution individually, and ran 5 warm samples across 6 request shapes against the live stack (real Ollama, real seeded catalog).
- **Result — every non-generative layer is exonerated**: fast filter path (6.8–8.8ms), routed filter path (21.7–24.1ms), and AI semantic retrieval (78–82ms) all pass their targets by 30–60x margin. The database, routing heuristic, and embedding/vector search were never the bottleneck at any point in this investigation.
- **Result — the actual cost is generation length, not tool-calling complexity**: round-by-round breakdown shows the tool-decision round consistently costs ~3–8s, while the natural-language final-answer round consistently costs ~27–44s — 4 to 10x more. Cross-referencing against the live container logs, the slow responses are the long, bulleted product-detail replies; the one comparatively fast final-answer round (7.3s) produced a visibly shorter reply. This is a 3B model's raw CPU-only token-generation throughput, not an architectural inefficiency in this codebase.
- **Result — single-tool and compound requests cost about the same**: `chat_single_tool` (31.6–52.6s) and `chat_compound_single_turn` (12.4–33.1s) overlap substantially. The earlier assumption that compound requests are categorically more expensive because they need more rounds doesn't hold — both request shapes resolved in 2 rounds live, and the dominant cost in both is the same final-answer generation step, not the number of tool calls.
- **Corroborating evidence, caught live, not synthetic**: one `chat_single_tool` cold-start run hit `_call_ollama`'s 60s httpx timeout outright (`rounds: None`, 60098.9ms total) — and BUG-012's fallback fired correctly, confirmed in a real failure during this very investigation, not a staged test.
- **Verdict**: `/chat`'s 5s target was never achievable for open-ended natural-language generation on CPU-only 3B local inference — this isn't a defect to patch, it's a target that didn't account for the hardware/model constraints the project deliberately chose (open-source, self-hostable, no paid API). The fast and routed filter paths, and pure retrieval, all genuinely meet their targets; only free-text generation doesn't, and can't, without either a larger/GPU-backed model (outside this project's stated cost-effectiveness goal) or a change to what "acceptable latency" means for a generative reply.
- **Fix**: A decision, not a code change — propose amending `docs/acceptance-criteria.md`'s Performance section to set an honest, separate target for `/chat` specifically (e.g., time-to-first-token instead of time-to-full-reply), and prioritizing the still-open UX criterion "Chat UI streams tokens as they arrive" — which turns this from a real latency problem into a solved *perceived*-latency problem, without touching the model or hardware.
- **Status**: Root-caused and measured live under real, warm conditions. Not marked "Fixed" — no code change here reduces actual generation time; the honest resolution is a target correction (adopted below) plus streaming as the follow-up UX fix, not a patch to this component.

---

## Known limitations (not bugs)

These are deliberate scope boundaries, not defects — tracked so they're not rediscovered as "surprise" bugs later.

## LIMITATION-001 — No true hybrid search: neither path uses both signals at once

- **Noted**: Day 8, during the BUG-009 fix; expanded Day 8 after Test 2 of the BUG-009 verification sequence
- **What it is, two directions of the same gap**:
  1. When `_tool_search_products()` takes the semantic path (no category, real query present), any `price_lt`/`price_gt`/`waterproof` the model also sent are dropped — only the query text drives the embedding search.
  2. When it takes the structured path (real category present), the `query` text is dropped entirely, even if it names something more specific than the category alone — e.g. a real category ("Hiking Boots") plus a specific product name in `query` returns every product in the category, not the named one.
- **Why it's not fixed alongside BUG-009 or BUG-010**: fixing either direction means real hybrid search — a Qdrant payload filter alongside the vector search, or post-filtering/re-ranking structured results against the query text — which is a feature addition, not a validation or gating fix. Bundling it into either bug would have expanded their scope past what could be verified in isolation.
- **Examples**: "waterproof tents under $200" with no category match won't actually enforce the $200 ceiling. "Find the Trailhead Waterproof Hiking Boot" with category correctly resolved to "Hiking Boots" returns the whole category instead of the one named product.
- **Revisit**: worth prioritizing once there's a concrete case (like Test 2) where the imprecision visibly affects a real customer-facing outcome, rather than fixing preemptively.

## LIMITATION-002 — No de-duplication for repeated identical tool calls within one turn

- **Noted**: Day 9, while verifying the conversation-memory mechanism
- **What it is**: `run_agent()`'s loop has no check for the model calling the exact same tool with the exact same arguments across multiple rounds within one turn. Surfaced via a test mock that (artificially) kept requesting `add_to_cart` every round — the loop executed it 4 times before hitting `MAX_TOOL_ITERATIONS`, which would have added 4 units to the mock cart instead of 1 for a real repeated call.
- **Why it's not fixed now**: not yet observed with the real model, only exposed by an imperfect test mock. Fixing pre-emptively for a hypothetical would be scope creep without evidence it happens in practice — consistent with this project's standing discipline of fixing observed, reproduced failures rather than every theoretical one.
- **What would close it**: a lightweight per-turn de-duplication check — if the same tool name + arguments were already successfully executed earlier in the same turn's trace, skip re-executing and reuse the prior result (or explicitly tell the model it already happened).
- **Revisit**: if a real live test ever shows the actual model repeating an identical tool call within one turn, this becomes a real bug (likely BUG-012), not just a documented limitation.

## LIMITATION-003 — Conversation history growth compounds per-call latency

- **Noted**: Day 10, during BUG-004's live latency investigation
- **What it is**: Day 9's conversation memory correctly fixed BUG-007's *correctness* problem — a product ID found in turn 1 is now reliably usable in turn 2. But every call to the model resends the full accumulated history (system prompt + every prior turn) as context, and the model reprocesses all of it before generating anything. Measured live: turn 2's first model call (deciding to call `add_to_cart`, with the product already resolved) took 29–35s — slower than a *fresh* single-turn request's entire first round (3–8s). Day 9 verified this mechanism works; it never measured what it costs.
- **Why it's not folded into BUG-004**: BUG-004 is about single-turn generation cost, root-caused to reply length. This is a different, additive cost specific to multi-turn conversations, and it will keep growing turn over turn as history accumulates — a customer's 4th or 5th message in the same session will cost more than their 1st, independent of what they're asking. Conflating the two would obscure that this gets worse with conversation length in a way BUG-004 alone doesn't.
- **Scope boundary**: Not a bug — the mechanism works exactly as designed and delivers real correctness value (BUG-007). This is a documented cost of that design, tracked so it isn't mistaken for a regression later, consistent with how LIMITATION-001 and LIMITATION-002 are handled elsewhere in this log.
- **Revisit**: worth addressing if a real conversation ever runs long enough that the accumulated-history cost visibly compounds beyond what MAX_CONVERSATION_MESSAGES's cap already bounds it to — candidates would be trimming history more aggressively than the current cap, or summarizing older turns instead of resending them verbatim. Not pursued now, consistent with this project's standing discipline of fixing observed impact over hypothetical future cost.

## LIMITATION-004 — Streaming's benefit is bounded by round 1's own latency, which is volatile and silent

- **Noted**: Day 11, live smoke test of `/chat/stream` (`stream_smoke_test.py`)
- **What it is**: Day 11 added token-by-token streaming for `/chat`'s final answer, directly targeting BUG-004's measured bottleneck (the long generation round). The mechanism itself works — verified live, zero malformed chunks, zero unexpected errors. But live testing surfaced a gap the design hadn't accounted for: any round where the model is deciding whether to call a tool produces **zero content** (the same empty-content-means-tool-call pattern documented since Day 8), so nothing streams during it. That round's real latency, measured live across three back-to-back identical requests, was **5.5s, 29.9s, and 89.7s** — wildly volatile, and during all of it the customer sees nothing at all. Streaming the eventual answer doesn't help if the customer has already been staring at a blank screen for up to a minute and a half before there's anything to stream.
- **Corroborating finding, not itself the point**: the two-turn scenario in the same smoke test independently reproduced LIMITATION-003's turn-2 cost (32.0s TTFT for turn 2's `add_to_cart` decision) via a completely different code path (streaming vs. Day 10's non-streaming benchmark) — good cross-confirmation that LIMITATION-003 is real, not a benchmark artifact.
- **Why it's not a regression or a bug in the streaming code**: `run_agent_stream()` does exactly what it was designed to do — stream content the moment it exists. The gap is that for a request needing a tool call, content doesn't exist yet during the most latency-heavy, unpredictable part of the request. That's an inherent property of tool-calling models, not a defect introduced by Day 11.
- **Fix — a status event, not more streaming**: since round 1 genuinely cannot stream content it hasn't generated, the honest fix is a `status` event ("Looking that up...", "Still working on it...", "Finishing up...") emitted the instant each round begins, before the model has produced anything. This does not reduce real latency — that would overclaim what it does — it only guarantees the customer is never left with literally zero feedback during the slowest part of the request. Added the same day, verified against the same mocked round sequences used for BUG-013/BUG-011 parity, with no interference with the correction mechanism.
- **Status**: Root-caused and mitigated same day. The underlying volatility (5.5s to 89.7s for an identical request) remains open and unexplained — worth investigating separately if it recurs, since an 84-second spread on the exact same request is a larger question than streaming alone can answer.

## BUG-014 — BUG-013's detector missed a mixed prose+JSON tool-call leak

- **Found**: Day 14, live end-to-end testing of the real frontend against the real running stack (not simulated) — the first live conversation to exercise a multi-turn "add from a product card" flow through the actual browser UI.
- **Severity**: High — raw internal JSON reached the customer verbatim, the exact outcome BUG-013 exists to prevent.
- **Component**: `agent.py`, `_looks_like_tool_call_json()`.
- **Symptom**: The customer asked to add a product found earlier in the conversation to their cart. The model replied with a sentence of plain English **followed by** a tool-call JSON blob:
  `"It seems like I need to search for the product again to get its numeric product_id.\n\n{"name": "search_products", "parameters": {"category":"Hiking Boots","query":"Meadowbrook Casual Hiker"}}"`
  This reached the customer's screen unmodified, visible in the actual frontend.
- **Root cause**: `_looks_like_tool_call_json()` required the ENTIRE message to start with `{` (`stripped.startswith("{")`). BUG-013's original finding (Day 11) was always pure-JSON content with nothing before it, so that check was never exercised against prose-then-JSON until real, unscripted live use hit it. The prose prefix meant `startswith("{")` was `False`, so the detector waved the leak straight through as a legitimate final answer.
- **Fix**: Removed the position requirement — the detector now checks for the tool-call shape (a `{`, plus the substrings `"name"` and `parameters`/`arguments`) **anywhere** in the content, not only at position zero. Also had to correct a first attempt at this fix: an initial regex-based version was too strict and stopped matching the ORIGINAL Day 11 malformed-JSON case, because that case is missing a closing quote around `"parameters"` (that missing quote is literally what makes it malformed) — the regex demanded well-formed quote structure the malformed input never had. Reverted to a substring-based check, which tolerates malformed internal structure the same way the original design always intended.
- **Verified**: Tested against the exact real leaked text from this live session (now caught), the original Day 11 malformed-JSON case (still caught, confirming the regex regression was caught before shipping), a well-formed `"arguments"`-keyed variant (still caught), four legitimate replies including one that contains the leak's own prose sentence ALONE with no JSON (correctly NOT flagged — confirms the fix didn't overcorrect into blocking honest text that merely resembles the lead-in), and a full end-to-end reproduction of the exact live scenario (nudge fires, model retries, conversation recovers to a clean confirmation instead of leaking JSON).
- **Status**: Fixed and verified against the real live-observed text, pending a live re-test against the actual running stack.
