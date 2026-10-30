# Architecture notes: pricing gate and compliance gate

This document covers the two pieces of GovCon Scout that decide whether a lead is worth bidding: the pricing gate (`_apply_margin` in `pipeline.py`) and the compliance verdict (`run_all_checks` in `tools/compliance_tool.py`). Both are pure functions with no network access and no LLM, and they don't depend on each other. A lead is bid-ready only at **GO + PASS**.

All numbers below come from running the actual code with the default settings: a 25% target margin (`MINIMUM_MARGIN_PCT`) and a 12% hard floor (`HARD_FLOOR_MARGIN_PCT`).

## 1. How a lead reaches the gates

`run_pipeline()` runs three stages in order:

1. **Scout.** SAM.gov search (plus optional DIBBS), deduplicated by `notice_id`.
2. **Analyst.** `price_lead()` attaches:
   - historical floor / ceiling / median (USASpending; NSN beats FSC beats keyword),
   - a supplier cost,
   - a shipping estimate.

   It then calls `_apply_margin()`. The supplier cost is one of three things, and the source is always recorded in `supplier_cost_source`:
   - a **real quote** from the supplier search, giving `supplier_cost_verified=True`;
   - an **estimate** of `0.55 x historical floor`, giving `supplier_cost_verified=False`;
   - **nothing**, giving `supplier_unit_cost_usd=None`.
3. **Compliance.** The top `SAM_DESC_FETCH_LIMIT` leads get their full SAM.gov description fetched. Every lead then goes through `run_compliance_check()`, and the verdict routes it to `recommended_bids` (PASS), `requires_review` (REVIEW) or `discarded_leads` (FAIL).

Each gate has its own field (`go_no_go` and `compliance.verdict`), so the UI and the scanner can explain exactly which one stopped a lead.

## 2. `_apply_margin`: the pricing gate

```
cogs           = supplier_unit_cost + shipping
bid_at_target  = cogs / (1 - target)                  # margin on price, not markup
if ceiling:    achievable = (ceiling - cogs) / ceiling
               bid        = min(ceiling, bid_at_target)
else:          achievable = target                     # no market data: assume reachable
               bid        = bid_at_target
margin         = (bid - cogs) / bid
```

The verdict, checked in this order:

| Condition | `go_no_go` |
|---|---|
| no supplier cost at all | `NO-GO` (returns early, every money field is `None`) |
| `cogs <= 0` | `NO-GO` |
| `margin >= target` and cost verified | `GO` |
| `margin >= target` and cost estimated | `VERIFY_COST` |
| `achievable >= floor` | `BELOW_TARGET` (shows the best achievable margin; my call) |
| otherwise | `NO-GO` |

The comparisons use a `1e-3` tolerance so that a bid rounded to the cent still counts as hitting the target. The function is pure on the lead's stored cost components, so `reprice_report()` can re-run it for every lead when the margin slider moves, with no API calls.

Worked examples (cost $40 + shipping $10 = COGS $50):

| Case | Ceiling | Verified | Bid | Margin | Achievable | Verdict |
|---|---|---|---|---|---|---|
| A: roomy ceiling | $100 | yes | $66.67 | 25.0% | 50.0% | `GO` |
| B: same, estimated cost | $100 | no | $66.67 | 25.0% | 50.0% | `VERIFY_COST` |
| C: tight ceiling | $60 | yes | $60.00 | 16.7% | 16.7% | `BELOW_TARGET` |
| D: ceiling below COGS | $45 | yes | $45.00 | -11.1% | -11.1% | `NO-GO` |
| E: no ceiling data | none | yes | $66.67 | 25.0% | 25.0% | `GO` |
| F: no cost data | - | - | - | - | - | `NO-GO` |

### Why estimated costs cap at VERIFY_COST

The estimate is a heuristic: 55% of the lowest historical award (`SUPPLIER_COST_ESTIMATE_RATIO`). It's useful for ranking and for deciding which leads deserve a manual price check. But it's a guess about my cost derived from the government's price, so the margin computed from it is circular. If the estimate could produce `GO`, the system would be recommending real bids on an invented margin. That's exactly the failure the original LLM Analyst had: it was told to "never say you need more information" and filled the gap with the same 55% guess. Here the estimate goes through the same math, but the verdict branch checks `supplier_cost_verified`, so the best it can reach is `VERIFY_COST`. The bid note tells the user to verify through the supplier links. Tests: `test_target_met_estimated_cost_is_verify`, `test_estimated_cost_never_go_only_verify`.

### What happens when the price ceiling is below COGS

The ceiling is the inflation-adjusted historical price. If it's below COGS (case D), `achievable` is negative. `bid = min(ceiling, bid_at_target)` clamps to the ceiling, so the computed margin is negative too. That fails both the target and the floor, and the verdict is `NO-GO`. The system never raises the bid above the ceiling to rescue the margin, because a bid above what the government has historically paid is very unlikely to win a micro-purchase.

One quirk to know about: the lead still carries `recommended_max_bid_usd = 45.00` (the ceiling) and `gross_profit_usd = -5.00`, and the bid note says "Recommended max bid: $45.00" before saying "skip". The verdict is right, but the field name is misleading for a `NO-GO`. A follow-up would be to null the bid fields when `achievable < floor`.

### Edge cases worth being ready for

- **No ceiling data (case E).** With no history, `achievable` is set to the target, so a verified quote can reach `GO` purely by bidding COGS / 0.75, with no evidence the government will pay that. This trade-off is deliberate: the alternative was making every unpriced niche unbiddable. The bid note says "No historical pricing found — price discovery required." But this is the weakest `GO` in the system, and the obvious next step is to cap it at `VERIFY_COST` too.
- **The floor never exceeds the target.** The callers pass `min(floor, target)`, so a slider set below 12% still produces a consistent verdict ladder.
- **Margin vs markup.** A 25% margin means a bid of COGS / 0.75 (a 33% markup). I use margin because the hard floor is a share of revenue.

## 3. The compliance verdict

`run_all_checks()` first parses the solicitation text against a clause catalog (FAR 52.225-1/-2/-3/-5/-6, DFARS 252.225-7001/-7009, FAR 52.219-14, and others). It then collects **fatal flags** and **warning flags**, and resolves them in this order:

1. any fatal flag -> **FAIL**;
2. any warning, or a BAA clause with unknown origin -> **REVIEW**;
3. only the title/synopsis was scanned (`full_text_analyzed=False`) -> **REVIEW**;
4. otherwise -> **PASS**.

Fatal flags:
- country of origin on the banned list (CN, RU, BY, IR, KP, CU, SY, VE);
- a TAA clause with a non-TAA country;
- a BAA clause with a non-US origin and no TAA exception;
- the specialty-metals clause plus a named metal in the text.

Warning flags:
- unknown origin while BAA/TAA clauses are present;
- 52.219-14 (Limitations on Subcontracting: I must be the manufacturer or a regular dealer);
- an estimated value above the TAA threshold with no TAA clause cited.

### Why unknown country of origin is REVIEW, not FAIL

Unknown isn't a violation. It means I haven't asked the supplier yet. Most commodity products have a certificate of origin a distributor can provide, so failing on unknown would discard a large share of legitimate leads before anyone asked one question. Treating unknown as US would be worse. The original pipeline hardcoded `country_of_origin="US"`, which meant the BAA/TAA checks could never fire: compliance theater. REVIEW is the honest middle: the lead stays visible, the flag says what to obtain ("supplier certificate before bidding"), and it can't be auto-recommended. FAIL is reserved for things that are known to be disqualifying. Tests: `test_unknown_coo_with_baa_clause_is_review_never_pass`, `test_unknown_coo_with_baa_clause_goes_to_review`.

### Why a title-only scan can't PASS

A clean scan of a 10-word title proves nothing; the BAA and TAA clauses live in the full solicitation. Description fetches cost SAM.gov quota, so only the top leads get full text. Everything else is marked `full_text_analyzed=False`, and a would-be PASS is downgraded to REVIEW with a note to read the full solicitation. Tests: `test_title_only_scan_never_passes`, `test_no_description_available_downgrades_to_review`.

### What PASS does and doesn't mean

The pipeline doesn't know which product I'll supply, so it always passes `country_of_origin=None`. A lead therefore reaches PASS only when the full text was analyzed and no BAA/TAA clause, 52.219-14, or other warning was found. PASS means "no blocking clause in the solicitation", not "my product is verified compliant". Choosing the product and checking its origin remain human steps. The scanner and quote generator prepare a quote but never submit one.

## 4. How the gates combine

| | `GO` | `VERIFY_COST` | `BELOW_TARGET` | `NO-GO` |
|---|---|---|---|---|
| **PASS** | bid-ready | check supplier price | my call on a thinner margin | skip |
| **REVIEW** | resolve compliance first | resolve both | resolve both | skip |
| **FAIL** | discarded (audit trail kept) | discarded | discarded | discarded |

`pipeline_summary.bid_ready_count` counts only PASS leads with `GO`. In `scan_daily.py`, the hunter auto-tracks leads that meet the margin target and aren't FAIL. Then it writes a quote sheet for human review.
