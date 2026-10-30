# GovCon Scout

GovCon Scout is a federal micro-purchase bid scout for small-business resellers. Give it a commodity keyword and it pulls live opportunities from SAM.gov. It prices each one against what the government has actually paid in the past (USASpending/FPDS award history), estimates supplier cost and shipping, and runs every lead through a FAR/DFARS compliance gate. The result is a short list of leads that are worth quoting, with the math and the audit trail visible. It ships as a local Streamlit app, a scheduled scanner, and a SQLite-backed bid tracker. Everything that decides money or legality is deterministic Python covered by an offline test suite.

## Why it's deterministic

The first version was a three-agent CrewAI pipeline (Scout, Analyst, Red-Team) where the LLM computed prices and margins and issued compliance verdicts. In practice the numbers drifted between runs and I couldn't trace where they came from. The compliance agent was also passing leads on insufficient evidence: country of origin was hardcoded to US, and a title-only scan could come back PASS. In the July 2026 rebuild (see [`PLAN.md`](PLAN.md) and [`TESTING.md`](TESTING.md)), I moved every number and every verdict into plain, tested Python and demoted the LLM to writing one optional strategy sentence per lead. The original agent definitions are kept in [`legacy/agents.py`](legacy/agents.py) for reference; nothing imports them.

## Architecture

```
                 Streamlit UI (app.py)          Daily scanner (scan_daily.py)
                          \                         /
                           v                       v
                 GovConScoutCrew.run()   (crew_runner.py: thin entry point)
                           |
                           v
                 run_pipeline()          (pipeline.py: plain Python, no LLM)
                           |
   +-----------------------+---------------------------------------------+
   |  SCOUT     tools/sam_tool.py     live SAM.gov opportunities         |
   |            tools/dibbs_tool.py   optional DIBBS RFQs (bonus source) |
   |               |  dedupe by notice_id                                |
   |               v                                                     |
   |  ANALYST   tools/fpds_tool.py    floor / ceiling / median price     |
   |            tools/supplier_tool.py  real quote, else labeled estimate|
   |            sourcing_calculator.py  shipping + bid math              |
   |               |  _apply_margin()  ->  pricing gate                  |
   |               v                                                     |
   |  COMPLIANCE tools/compliance_tool.py  FAR/DFARS clause parse,       |
   |            BAA/TAA, banned origin, 52.219-14, specialty metals      |
   |               |  run_compliance_check()  ->  compliance gate        |
   +---------------+-----------------------------------------------------+
                   v
     report: recommended_bids / requires_review / discarded_leads
                   |
                   +--> (optional, USE_LLM=true) one strategy sentence per lead
                   +--> db.py (SQLite tracker) / quote_generator.py (quote sheets)
```

There are two independent gates, and a lead is bid-ready only when both clear:

| Gate | Values | Question it answers |
|---|---|---|
| Compliance | `PASS` / `REVIEW` / `FAIL` | Can I legally bid this with the product I'd supply? |
| Pricing | `GO` / `VERIFY_COST` / `BELOW_TARGET` / `NO-GO` | Is the margin real at a price the government will pay? |

`GO` requires a real supplier quote; an estimated cost can never do better than `VERIFY_COST`. `FAIL` leads are discarded with their flags kept as an audit trail. `REVIEW` means a human needs to check something, usually country of origin. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) walks through the margin and verdict logic in detail.

## Data sources

| Source | Used for | Module |
|---|---|---|
| SAM.gov Get Opportunities API (v2 search, v1 notice description) | Live solicitations, sources sought, presolicitations; full description text for clause detection | `tools/sam_tool.py` |
| USASpending.gov (FPDS award data) | Historical floor, inflation-adjusted ceiling, median price, number of distinct winners; market intel tab | `tools/fpds_tool.py`, `analytics.py` |
| DLA DIBBS (optional, experimental) | Bonus NSN-based RFQs parsed from the daily batch file | `tools/dibbs_tool.py` |
| Google Programmable Search (Shopping results) | Real supplier unit prices | `tools/supplier_tool.py` |
| Built-in shipping table | Weight- and destination-based parcel/LTL estimate | `sourcing_calculator.py` |

## The optional LLM layer

There are two places an LLM is used, and neither is in the money path:

- **Bid-note enrichment** (`crew_runner.py`, off by default). After the deterministic report is finished, a single CrewAI agent on Gemini receives the already-computed fields for each lead. It returns one strategy sentence per notice ID, which is appended to that lead's bid note. It cannot change a price, margin, or verdict, and if it fails or returns bad JSON the report is returned unchanged.
- **The Advisor chat** (`assistant.py`). A tool-calling Gemini chat in the app that answers questions by calling the real pipeline, market-stats, niche-scan and tracker functions. The system prompt requires every figure to come from a tool result. The Gemini transport is injectable, so the tool loop is tested offline.

To turn on note enrichment:

```bash
pip install -r requirements-llm.txt
# in .env
USE_LLM=true
GOOGLE_API_KEY=...
```

## Quickstart

Tested with Python 3.13 on Windows.

```bash
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # then fill in SAM_API_KEY at minimum
```

Run the offline test suite. It makes no network calls and needs no keys, so it costs $0:

```bash
python -m pytest tests/ -v
```

60 tests cover bid math to the cent, margin gating, the compliance verdict paths (banned origin, BAA, TAA, 52.219-14, specialty metals, title-only scans), SAM.gov response parsing (against a captured real response), the DIBBS parser, the SQLite layer, and the Advisor's tool loop with a fake transport.

Live smoke test (uses a few requests of your SAM.gov daily quota, no LLM):

```bash
python smoke_test.py "nitrile gloves"
```

Launch the app:

```bash
streamlit run app.py
```

Run the scanner once (saved searches, auto-tracking, quote prep, optional email digest):

```bash
python scan_daily.py --no-email
```

## Known limitations and debt

- `app.py` is a ~1,000-line Streamlit monolith (UI, state, and formatting in one file). It's the next thing I'd split.
- Supplier cost estimates are a heuristic: 55% of the historical floor (`SUPPLIER_COST_ESTIMATE_RATIO`). They are labeled as estimates and capped at `VERIFY_COST`, so they never produce a `GO`. Real quotes come only from Google Programmable Search; Grainger and Zoro keys exist in `config.py` but no adapter uses them yet.
- Personal SAM.gov API keys have a low daily quota. Searches are cached in `.cache/` per keyword/NAICS/day, and full description text is fetched only for the top `SAM_DESC_FETCH_LIMIT` leads (default 5). Leads past that limit are scanned on title only, so they can never reach `PASS`. When the quota runs out (HTTP 429), the error is logged and the search returns an empty list. The UI then shows "no opportunities found", which looks the same as a real empty result.
- Compliance never sees a supplier's country of origin; the pipeline always passes "unknown". A lead can still `PASS` when the full text contains no BAA/TAA clause and no other warning, so `PASS` means "no blocking clause found", not "origin verified".
- When there is no historical ceiling, the bid is set at the target margin with no market check, so a real quote can reach `GO` without price-ceiling evidence.
- The TAA dollar threshold ($183,000) is hardcoded and updates every two years.
- `GEMINI_MODEL` is read in `config.py`, but `assistant.py` and `crew_runner.py` each hardcode `gemini-2.5-flash`. `analytics.beat_this_price` defaults to a 15% margin while the rest of the app uses 25%. `USPS_USER_ID` and the `SHIPPER_*` variables are defined but unused.
- The DIBBS adapter scrapes a consent banner and batch files; any format change makes it return nothing (by design it never raises).
- `INSTALL.md` predates the rebuild and still describes the OpenAI/EasyPost setup.
- Windows launchers (`.bat`) are local-only and not in the repo; use the commands above.

## License

TODO: choose license
