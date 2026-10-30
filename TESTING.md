# Testing GovCon Scout — verify everything before spending a dime

## What changed (July 2026 rebuild)

1. **Scout now searches LIVE SAM.gov opportunities** (bids you can actually submit). The old version searched USASpending — contracts already awarded to someone else. USASpending is still used, correctly, for historical pricing.
2. **All math is deterministic Python** (`pipeline.py`). The LLM never touches numbers or verdicts. `USE_LLM=false` (default) runs the entire pipeline with zero LLM cost.
3. **GO requires a real supplier quote.** Estimated costs (55%-of-floor heuristic) max out at `VERIFY_COST` — the app will never tell you to bid on a fictional margin.
4. **Compliance never assumes US origin.** Unknown country of origin = REVIEW. A clean scan of only a title can never PASS — full solicitation text is fetched for top leads.
5. **Security:** hardcoded API key removed from `config.py`; `.gitignore` added. **Rotate your keys anyway** — they were sitting in plaintext.
6. Margin unified at **25%** in `config.py` (`MINIMUM_MARGIN_PCT`) — the single source of truth.

## Layer 1 — Unit + pipeline tests (offline, $0, run anytime)

```bash
cd GovConScout
venv\Scripts\activate
pip install pytest
python -m pytest tests/ -v
```

32 tests, no network, no API usage. They verify: bid math to the penny, compliance verdicts (banned countries, TAA, BAA, 52.219-14, specialty metals), SAM.gov response parsing (using a real captured API response), deadline filtering, and the GO / VERIFY_COST / NO-GO gating.

## Layer 2 — Live smoke test (free APIs, uses SAM daily quota, $0)

```bash
python smoke_test.py "nitrile gloves"
```

Hits real SAM.gov + USASpending. No LLM. Prints top 5 leads with pricing and compliance verdicts; saves full report to `smoke_test_result.json`. Results cache in `.cache/` so same-day re-runs don't consume your SAM quota.

## Layer 3 — Full app (still $0 with USE_LLM=false)

```bash
streamlit run app.py
```

## Turning the LLM back on (optional, costs per run)

Set `USE_LLM=true` in `.env`. This ONLY adds LLM-written strategy sentences to bid notes — prices, margins, and verdicts stay deterministic.

## Reading results

| go_no_go | Meaning |
|---|---|
| `GO` | Real supplier quote found, margin ≥ 25% — bid-ready pending compliance |
| `VERIFY_COST` | Margin looks good but cost is an ESTIMATE — check supplier links first |
| `NO-GO` | Margin below floor or unpriceable — skip |

| compliance verdict | Meaning |
|---|---|
| `PASS` | Full text scanned, no fatal clauses, origin verified |
| `REVIEW` | Unknown origin, partial text, or 52.219-14 present — human check required |
| `FAIL` | Banned country / BAA-TAA violation — discarded, audit trail kept |

A lead is only truly bid-ready at **GO + PASS**. Expect mostly REVIEW early on — that's the system being honest, not broken.
