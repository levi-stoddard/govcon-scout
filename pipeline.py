"""
pipeline.py — Deterministic GovCon Scout pipeline

Scout → Analyst → Red-Team as plain Python. Same math every run, fully
testable, zero LLM cost. The LLM (crew_runner USE_LLM=true) only ADDS
narrative bid notes on top — it never touches numbers or verdicts.

Verdict model (two independent gates):
  compliance verdict : PASS / REVIEW / FAIL      (can we legally bid?)
  pricing status     : GO / VERIFY_COST / NO-GO  (is the margin real?)

A lead is only bid-ready when compliance=PASS *and* pricing=GO.
GO requires a REAL supplier quote — estimated costs cap out at VERIFY_COST.
"""

from __future__ import annotations
import logging
from typing import Any, Callable

from config import (
    MINIMUM_MARGIN_PCT, HARD_FLOOR_MARGIN_PCT, MICRO_PURCHASE_THRESHOLD,
    SAM_DESC_FETCH_LIMIT, SUPPLIER_COST_ESTIMATE_RATIO, PACKAGE_WEIGHT_LBS_DEFAULT,
)
from tools.sam_tool import search_sam_opportunities, fetch_notice_description
from tools.fpds_tool import get_historical_pricing
from tools.supplier_tool import get_supplier_pricing
from tools.compliance_tool import run_compliance_check
from sourcing_calculator import estimate_shipping, calculate_bid, build_supplier_links

logger = logging.getLogger(__name__)


def _apply_margin(lead: dict, target_pct: float, floor_pct: float) -> dict:
    """
    Adaptive margin math (pure — reusable for instant repricing):
      margin >= target          → GO (verified cost) / VERIFY_COST (estimated)
      floor <= achievable < target → BELOW_TARGET ("works at X%") — your call
      achievable < hard floor   → NO-GO, never recommended
    """
    lead["margin_target_pct"] = round(target_pct * 100, 1)
    lead["margin_floor_pct"] = round(floor_pct * 100, 1)
    cost = lead.get("supplier_unit_cost_usd")
    if cost is None:
        lead.update(total_cogs_usd=None, recommended_max_bid_usd=None,
                    gross_profit_usd=None, actual_margin_pct=None,
                    max_achievable_margin_pct=None, go_no_go="NO-GO")
        return lead

    ship = lead.get("shipping_cost_usd") or 0.0
    cogs = round(cost + ship, 2)
    ceiling = lead.get("ceiling_price_usd")
    bid_at_target = cogs / (1 - target_pct) if target_pct < 1 else cogs

    if ceiling and ceiling > 0:
        achievable = (ceiling - cogs) / ceiling
        bid = min(ceiling, bid_at_target)
    else:
        achievable = target_pct  # no ceiling data: target is reachable, confidence lower
        bid = bid_at_target

    bid = round(bid, 2)
    margin = (bid - cogs) / bid if bid > 0 else 0.0
    lead["total_cogs_usd"] = cogs
    lead["recommended_max_bid_usd"] = bid
    lead["gross_profit_usd"] = round(bid - cogs, 2)
    lead["actual_margin_pct"] = round(margin * 100, 1)
    lead["max_achievable_margin_pct"] = round(achievable * 100, 1)

    if cogs <= 0:
        lead["go_no_go"] = "NO-GO"
    elif margin >= target_pct - 1e-3:
        lead["go_no_go"] = "GO" if lead.get("supplier_cost_verified") else "VERIFY_COST"
    elif achievable >= floor_pct - 1e-3:
        lead["go_no_go"] = "BELOW_TARGET"
    else:
        lead["go_no_go"] = "NO-GO"
    return lead


def price_lead(
    lead: dict,
    keyword: str,
    pricing_fetcher: Callable[..., dict] = get_historical_pricing,
    supplier_fetcher: Callable[..., dict] = get_supplier_pricing,
    _pricing_cache: dict | None = None,
    target_margin_pct: float | None = None,
    hard_floor_pct: float | None = None,
) -> dict:
    """Attach floor/ceiling, supplier cost, shipping, and bid math to a lead."""
    cache = _pricing_cache if _pricing_cache is not None else {}

    # 1. Historical pricing — NSN beats FSC beats keyword
    cache_key = (lead.get("nsn"), lead.get("fsc_code"), keyword)
    if cache_key not in cache:
        cache[cache_key] = pricing_fetcher(
            commodity_description=keyword,
            naics_code=lead.get("naics_code") or None,
            fsc_code=lead.get("fsc_code") or None,
            nsn=lead.get("nsn") or None,
        )
    hist = cache[cache_key]
    floor = hist.get("floor_price_usd")
    ceiling = hist.get("ceiling_price_usd")
    lead["floor_price_usd"] = floor
    lead["ceiling_price_usd"] = round(ceiling, 2) if ceiling else None
    lead["median_price_usd"] = hist.get("median_price_usd")
    lead["historical_sample_size"] = hist.get("sample_size", 0)
    lead["historical_unique_bidders"] = hist.get("unique_recipients", 0)

    # 2. Supplier cost — real quote or labeled estimate, never silent fiction
    supplier = supplier_fetcher(
        commodity_description=lead.get("title") or keyword,
        nsn=lead.get("nsn"),
    )
    if supplier.get("status") == "success":
        best = supplier["best_quote"]
        supplier_cost = best["unit_price_usd"]
        lead["supplier_unit_cost_usd"] = supplier_cost
        lead["supplier_cost_source"] = f"REAL QUOTE — {best.get('description', '')[:60]}"
        lead["supplier_product_url"] = best.get("product_url")
        cost_verified = True
    elif floor:
        supplier_cost = round(floor * SUPPLIER_COST_ESTIMATE_RATIO, 2)
        lead["supplier_unit_cost_usd"] = supplier_cost
        lead["supplier_cost_source"] = (
            f"ESTIMATE ({SUPPLIER_COST_ESTIMATE_RATIO:.0%} of historical floor) — "
            "verify a real price before bidding"
        )
        lead["supplier_product_url"] = None
        cost_verified = False
    else:
        supplier_cost = None
        lead["supplier_unit_cost_usd"] = None
        lead["supplier_cost_source"] = "NO DATA — cannot price this lead"
        lead["supplier_product_url"] = None
        cost_verified = False
    lead["supplier_cost_verified"] = cost_verified

    # 3. Shipping estimate
    if supplier_cost is not None:
        shipping = estimate_shipping(PACKAGE_WEIGHT_LBS_DEFAULT, lead.get("pop_state") or "VA")
        lead["shipping_cost_usd"] = shipping["estimated_shipping_usd"]
    else:
        lead["shipping_cost_usd"] = None

    # 4. Adaptive margin gate (GO / VERIFY_COST / BELOW_TARGET / NO-GO)
    target = target_margin_pct if target_margin_pct is not None else MINIMUM_MARGIN_PCT
    floor = hard_floor_pct if hard_floor_pct is not None else HARD_FLOOR_MARGIN_PCT
    _apply_margin(lead, target, min(floor, target))

    # 5. Human aids
    lead["supplier_links"] = build_supplier_links(lead.get("title") or keyword)
    lead["bid_note"] = _build_bid_note(lead)
    return lead


def reprice_report(report: dict, target_margin_pct: float, hard_floor_pct: float) -> dict:
    """
    Instantly re-run margin math on an existing report — no API calls, pure
    arithmetic on the stored cost components. Powers the live margin slider.
    """
    floor = min(hard_floor_pct, target_margin_pct)
    for bucket in ("recommended_bids", "requires_review", "discarded_leads"):
        for lead in report.get(bucket, []):
            if "supplier_unit_cost_usd" in lead:
                _apply_margin(lead, target_margin_pct, floor)
                lead["bid_note"] = _build_bid_note(lead)
    all_leads = report.get("recommended_bids", []) + report.get("requires_review", [])
    summary = report.setdefault("pipeline_summary", {})
    summary["target_margin_pct"] = round(target_margin_pct * 100, 1)
    summary["hard_floor_pct"] = round(floor * 100, 1)
    summary["bid_ready_count"] = sum(1 for l in report.get("recommended_bids", [])
                                     if l.get("go_no_go") == "GO")
    summary["verify_cost_count"] = sum(1 for l in all_leads if l.get("go_no_go") == "VERIFY_COST")
    summary["below_target_count"] = sum(1 for l in all_leads if l.get("go_no_go") == "BELOW_TARGET")
    return report


def _build_bid_note(lead: dict) -> str:
    parts = []
    ceiling = lead.get("ceiling_price_usd")
    floor = lead.get("floor_price_usd")
    bid = lead.get("recommended_max_bid_usd")
    n = lead.get("historical_sample_size", 0)
    bidders = lead.get("historical_unique_bidders", 0)

    if ceiling and floor:
        parts.append(
            f"Government paid ${floor:,.2f}–${ceiling:,.2f} historically "
            f"({n} awards, {bidders} unique winners)."
        )
    else:
        parts.append("No historical pricing found — price discovery required.")
    if bid:
        parts.append(f"Recommended max bid: ${bid:,.2f}.")
    status = lead.get("go_no_go")
    if status == "VERIFY_COST":
        parts.append("Cost is an ESTIMATE — verify supplier price via links before bidding.")
    elif status == "GO":
        parts.append("Real supplier quote found — margin math is solid.")
    elif status == "BELOW_TARGET":
        parts.append(
            f"Can't hit your {lead.get('margin_target_pct')}% target — best achievable is "
            f"{lead.get('max_achievable_margin_pct')}% at the market ceiling. Your call."
            + ("" if lead.get("supplier_cost_verified") else " (Cost is an estimate — verify first.)")
        )
    elif status == "NO-GO":
        parts.append(f"Below your {lead.get('margin_floor_pct', '')}% hard floor or unpriceable — skip.")
    if bidders and bidders < 4:
        parts.append(f"Only {bidders} historical winner(s) — soft competition.")
    return " ".join(parts)


def run_pipeline(
    keyword: str,
    naics_code: str | None = None,
    max_leads: int = 10,
    country_of_origin: str | None = None,
    fetch_descriptions: bool = True,
    target_margin_pct: float | None = None,
    hard_floor_pct: float | None = None,
    scout_fetcher: Callable[..., list] = search_sam_opportunities,
    pricing_fetcher: Callable[..., dict] = get_historical_pricing,
    supplier_fetcher: Callable[..., dict] = get_supplier_pricing,
    description_fetcher: Callable[..., str] = fetch_notice_description,
    extra_scout_fetchers: list[Callable[..., list]] | None = None,
) -> dict[str, Any]:
    """
    Full deterministic pipeline. All fetchers are injectable for testing.
    `extra_scout_fetchers` (e.g. the experimental DIBBS feed) add bonus lead
    sources — their failures are logged, never fatal.
    Returns the same report structure app.py has always consumed.
    """
    logger.info("Pipeline start: '%s' (NAICS %s)", keyword, naics_code)

    # ── SCOUT: live SAM.gov opportunities (+ optional bonus sources) ─────────
    leads = scout_fetcher(keywords=keyword, naics_code=naics_code, max_results=max_leads)
    logger.info("Scout: %d live leads", len(leads))

    for extra in extra_scout_fetchers or []:
        try:
            bonus = extra(keywords=keyword, naics_code=naics_code, max_results=max_leads)
            leads.extend(bonus)
            logger.info("Bonus source %s: %d leads", getattr(extra, "__name__", "?"), len(bonus))
        except Exception as exc:  # bonus sources must never break the pipeline
            logger.warning("Bonus scout source failed (ignored): %s", exc)

    # Dedup by notice_id, keep first (SAM wins over bonus duplicates)
    seen_ids: set = set()
    deduped = []
    for l in leads:
        nid = l.get("notice_id")
        if nid and nid in seen_ids:
            continue
        seen_ids.add(nid)
        deduped.append(l)
    leads = deduped[: max(max_leads * 2, max_leads)]

    if not leads:
        return _empty_report(f"No live opportunities found for '{keyword}'. Try a different keyword.")

    # ── ANALYST: deterministic pricing (adaptive margins) ────────────────────
    target = target_margin_pct if target_margin_pct is not None else MINIMUM_MARGIN_PCT
    floor = min(hard_floor_pct if hard_floor_pct is not None else HARD_FLOOR_MARGIN_PCT, target)
    pricing_cache: dict = {}
    for lead in leads:
        price_lead(lead, keyword, pricing_fetcher, supplier_fetcher, pricing_cache,
                   target_margin_pct=target, hard_floor_pct=floor)

    # ── RED-TEAM: compliance gate ────────────────────────────────────────────
    recommended, review, discarded = [], [], []
    for i, lead in enumerate(leads):
        text = lead.get("title") or ""
        full_text = False
        if fetch_descriptions and i < SAM_DESC_FETCH_LIMIT and lead.get("description_url"):
            desc = description_fetcher(lead["description_url"])
            if desc:
                text = f"{text}\n{desc}"
                full_text = True

        report = run_compliance_check(
            notice_id=lead.get("notice_id") or "",
            solicitation_text=text,
            country_of_origin=country_of_origin,  # None = UNKNOWN → REVIEW, never assumed US
            estimated_value_usd=lead.get("estimated_value_usd"),
            full_text_analyzed=full_text,
        )
        lead["compliance"] = report
        verdict = report.get("verdict")
        if verdict == "FAIL":
            discarded.append(lead)
        elif verdict == "PASS":
            recommended.append(lead)
        else:
            review.append(lead)

    summary = {
        "total_leads_evaluated": len(leads),
        "cleared_count": len(recommended),
        "review_count": len(review),
        "discarded_count": len(discarded),
        "bid_ready_count": sum(1 for l in recommended if l.get("go_no_go") == "GO"),
        "verify_cost_count": sum(1 for l in leads if l.get("go_no_go") == "VERIFY_COST"),
        "below_target_count": sum(1 for l in leads if l.get("go_no_go") == "BELOW_TARGET"),
        "target_margin_pct": round(target * 100, 1),
        "hard_floor_pct": round(floor * 100, 1),
        "note": (
            f"Target margin: {target:.0%} (hard floor {floor:.0%}). "
            f"Micro-purchase threshold: ${MICRO_PURCHASE_THRESHOLD:,.0f}. "
            "GO requires a verified supplier quote — VERIFY_COST needs a manual price check. "
            "BELOW_TARGET shows the best achievable margin so you can decide."
        ),
    }
    logger.info(
        "Pipeline done. Cleared: %d | Review: %d | Discarded: %d",
        len(recommended), len(review), len(discarded),
    )
    return {
        "recommended_bids": recommended,
        "requires_review": review,
        "discarded_leads": discarded,
        "pipeline_summary": summary,
    }


def _empty_report(note: str) -> dict[str, Any]:
    return {
        "recommended_bids": [],
        "requires_review": [],
        "discarded_leads": [],
        "pipeline_summary": {
            "total_leads_evaluated": 0,
            "cleared_count": 0,
            "review_count": 0,
            "discarded_count": 0,
            "bid_ready_count": 0,
            "verify_cost_count": 0,
            "note": note,
        },
    }
