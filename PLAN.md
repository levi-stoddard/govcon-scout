# GovCon Scout — Master Plan
*Created 2026-07-16 · Status: pre-registration, full-time operator, fix-and-upgrade path*

---

## 1. How to use Claude (your question #1)

**Fable 5 vs Claude Code is not a model choice — it's a tool choice.** Both run the same Claude models. Use each where it's strong:

| Tool | Use it for |
|---|---|
| **Cowork (here, Fable 5)** | Strategy, research, reviewing leads, writing docs/quotes, scheduled daily lead scans, analyzing pipeline output |
| **Claude Code (terminal)** | Fixing and extending the Python app. Your venv is Windows and Streamlit runs locally — Claude Code edits, runs, and tests directly on your machine in a fast loop |

**Recommended workflow:** design and specs here → hand the spec to Claude Code to implement → bring results back here for review. This PLAN.md is that spec.

**Your app's internal LLM (Gemini via CrewAI) is a separate question.** You can keep Gemini or swap to the Claude API — but that matters far less than the fixes below. "Flawless" agents come from moving math and rules OUT of the LLM, not from a better LLM.

---

## 2. Critical fixes (do these before anything else)

### FIX 1 — The Scout searches the wrong database ⚠️ HIGHEST PRIORITY
`tools/sam_tool.py` queries **USASpending.gov = contracts already awarded**. You cannot bid on those. Your SAM.gov key sits unused in `.env`.

- Rewrite `sam_tool.py` to call the real SAM.gov Get Opportunities API (`https://api.sam.gov/opportunities/v2/search`) for **live** Combined Synopsis/Solicitations and Sources Sought.
- Keep the USASpending query — but move it to the **Analyst** where it belongs (historical pricing). It's the right data for the wrong agent right now.

### FIX 2 — Fictional margins
The Analyst estimates supplier cost as `floor_price × 0.55`. That's an invented number driving real bid decisions. Change `go_no_go` logic: **no GO verdict without a real supplier price** (Google CSE result, or manual verification link clicked). Estimated-cost leads get a `VERIFY_COST` status, never `GO`.

### FIX 3 — Compliance theater
`crew_runner.py` hardcodes `country_of_origin="US"` — so the Red-Team can never catch a violation. Instead: fetch the actual solicitation text from the SAM.gov description URL, parse for FAR 52.225-x clauses, and default COO to `UNKNOWN` → REVIEW. Never assume US.

### FIX 4 — LLMs doing math
Floor/ceiling/margin/bid math currently runs through Gemini prompts and can silently vary. Move ALL arithmetic into plain Python (`sourcing_calculator.py` already exists — route everything through it). LLM agents should only: parse solicitation text, judge relevance, write bid notes. This is the single biggest reliability upgrade.

### FIX 5 — Security
Live API keys are hardcoded in `config.py` (fallback Google key) and committed in `.env`. **Rotate all keys now**, delete the hardcoded fallback, add `.env` to `.gitignore`.

### FIX 6 — Consistency
README says 15% margin; `agents.py` says 25%. Pick one (suggest 25% minimum for micro-purchases — small dollar amounts need fat margins to be worth your time) and define it once in `config.py`.

---

## 3. What I'd do differently in real life (your question #2)

### The pond matters more than the fishing rod
Most true micro-purchases (< $10K) **never appear on SAM.gov**. They flow through:

1. **DLA DIBBS** (dibbs.bsm.dla.mil) — thousands of small NSN-based RFQs daily, many under $10K, automated award to low bidder. This is THE micro-contract pond for commodities.
2. **SAM.gov** — simplified acquisitions $10K–$250K (auto set-aside for small business under the "rule of two"), Sources Sought, Combined Synopsis.
3. **Unison Marketplace** (ex-FedBid) — reverse auctions for commodity buys.
4. **GSA eBuy / Advantage** — requires a GSA Schedule (later-stage goal, not now).

**Add DIBBS as a second Scout source.** It has no public API, but RFQs are downloadable as batch text files — a parser is straightforward and this is where your niche lives.

### The niche is a filter profile, not a product category
Don't pick "gloves" or "tools." Pick opportunities that pass ALL of these gates:

- **Exact NSN or part-number match** — you win on price, not proposal writing
- **Domestic (BAA-compliant) supply exists** at a distributor you can buy from
- **Shipping < 5% of bid** — small, light, non-hazmat
- **No landmines:** no QPL/QML source restrictions, no first-article testing, no cold chain, no hazmat, no 6505 (regulated medical)
- **≥ 3 historical awards** with visible price spread (your FPDS data — used correctly this time)
- **Low competition:** historical awards show < 4 unique bidders
- **≥ 25% margin after real supplier quote + shipping**

Good FSC hunting grounds meeting this profile: 5305/5310 (fasteners), 5120 (hand tools), 4240 (safety equipment), 9905 (signs/plates), 7510 (office supplies), 8010 (paints — watch hazmat).

### 52.219-14 is your biggest legal landmine
On set-aside supply contracts you must be the **manufacturer or a "regular dealer."** Pure dropshipping can violate the nonmanufacturer rule. Mitigation: the nonmanufacturer rule requires you to supply the product of a *small* US manufacturer (or get a waiver) — your compliance agent should flag this on every set-aside lead, and it's a reason to prefer **unrestricted micro-purchases and DIBBS spot buys** early on, where this pressure is lower.

### Fulfillment (you're undecided)
Start with **buy-and-reship**: order to yourself, inspect, apply MIL-STD-129 labeling if required, ship. Dropshipping direct from Grainger to a DoD depot fails packaging/labeling requirements and torches your CAGE reputation with late/wrong deliveries. Hold inventory only after you see repeat NSNs.

### Expectation setting
Win rates on DIBBS commodity RFQs run low single digits early. Full-time capacity means volume: target 20–50 quotes/week once registered, expect the flywheel (past-performance → better win rate) to take 3–6 months. The agents' job is to make 50 quotes/week take 2 hours instead of 20.

---

## 4. Roadmap

### Phase 0 — Registrations (start TODAY, runs parallel to everything)
These are the true bottleneck — weeks of government processing, zero code required:

1. Get a UEI + register entity on **SAM.gov** (free — never pay a third party)
2. **CAGE code** (assigned via SAM registration)
3. **DIBBS account** (needs CAGE) + JCP certification (DD 2345) to see export-controlled drawings
4. Small-business self-certification in SAM; WOSB/EDWOSB via SBA **only if eligible** — otherwise remove WOSB prioritization from `config.py` and target Total Small Business set-asides
5. Business bank account + Wide Area Workflow (WAWF/PIEE) registration for getting paid

### Phase 1 — Fix the app (Claude Code, ~1 week)
Fixes 1–6 above, in that order.

### Phase 2 — Add the real niche sources (~2 weeks)
- DIBBS batch-file parser as second Scout source
- Solicitation full-text fetch for real clause detection
- Deterministic scoring against the filter profile in §3
- Daily scheduled scan + digest of top 5 leads (can run as a Cowork scheduled task)

### Phase 3 — Operate (ongoing)
- Quote log (win/loss, margin, competitor count) — feed win-rate data back into the priority score
- Quote package generator (DIBBS quote / SF-1449 fields pre-filled for human review)
- Post-award checklist: supplier PO, packaging/labeling, WAWF invoicing

---

## 5. Non-negotiables for "flawless"

1. Numbers never come from an LLM — Python computes, LLM explains
2. No GO without a verified supplier price
3. No bid submission without human review (you sign, agents prep)
4. COO unknown = REVIEW, always
5. Every discarded lead keeps an audit trail (you have this — keep it)
