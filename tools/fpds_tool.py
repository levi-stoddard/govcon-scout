"""
tools/fpds_tool.py — Analyst Tool #1
Fetches historical contract award data from USASpending.gov (FPDS mirror)
and calculates Floor, inflation-adjusted Ceiling, and Median pricing.

This is the CORRECT use of USASpending: historical price intelligence.
(Live bid leads come from SAM.gov — see sam_tool.py.)

Logic lives in plain functions (testable, no LLM). CrewAI wrapper optional.
API docs: https://api.usaspending.gov/ — no key required.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from statistics import median, mean
from typing import Any, Callable

import requests

from config import (
    FPDS_BASE_URL, FPDS_LOOKBACK_YEARS,
    INFLATION_RATE_ANNUAL, FSC_COMMODITY_MAP,
)

logger = logging.getLogger(__name__)


def _build_time_period() -> list[dict]:
    end_year = datetime.now(timezone.utc).year
    start_year = end_year - FPDS_LOOKBACK_YEARS
    return [{"start_date": f"{start_year}-01-01", "end_date": f"{end_year}-12-31"}]


# Field names must match the API's documented list exactly — invalid names = 422
SAFE_FIELDS = [
    "Award ID", "Recipient Name", "Award Amount", "Description",
    "Start Date", "End Date", "Awarding Agency",
    "Place of Performance State Code", "Place of Performance Zip5",
]


def _post_awards(post: Callable, payload: dict) -> list[dict] | None:
    """POST to spending_by_award. Returns None on rejection (logs the API's reason)."""
    try:
        resp = post(f"{FPDS_BASE_URL}/search/spending_by_award/", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except requests.HTTPError as exc:
        body = getattr(getattr(exc, "response", None), "text", "")[:300]
        logger.error("USASpending rejected payload (%s): %s", exc, body)
        return None
    except requests.RequestException as exc:
        logger.error("USASpending network error: %s", exc)
        return None


def fetch_awards(
    description: str,
    naics_code: str | None = None,
    fsc_code: str | None = None,
    nsn: str | None = None,
    http_post: Callable[..., requests.Response] | None = None,
) -> list[dict]:
    """
    Query USASpending. Match precision: NSN > FSC > NAICS > keyword.
    If the precise query is rejected, falls back to a minimal keyword-only
    payload rather than returning nothing.
    """
    post = http_post or requests.post
    keyword = (nsn or description or "").strip()
    if len(keyword) < 3:
        logger.warning("USASpending keyword too short: %r", keyword)
        return []

    filters: dict[str, Any] = {
        "keywords": [keyword],
        "time_period": _build_time_period(),
        "award_type_codes": ["A", "B", "C", "D"],
    }
    # NSN searches via keywords ('description' is NOT a valid filter — causes 400)
    if fsc_code and not nsn:
        filters["psc_codes"] = [str(fsc_code)]
    elif naics_code and not nsn:
        filters["naics_codes"] = [str(naics_code)]

    payload = {
        "filters": filters,
        "fields": SAFE_FIELDS,
        "sort": "Start Date",
        "order": "desc",
        "limit": 100,
        "page": 1,
    }
    results = _post_awards(post, payload)
    if results is None:
        # Fallback: strip the optional filters, keep it minimal but valid
        minimal = {
            "filters": {
                "keywords": [keyword],
                "time_period": _build_time_period(),
                "award_type_codes": ["A", "B", "C", "D"],
            },
            "fields": SAFE_FIELDS,
            "sort": "Award Amount",
            "order": "desc",
            "limit": 100,
            "page": 1,
        }
        results = _post_awards(post, minimal)
        if results is not None:
            logger.info("USASpending minimal-payload fallback succeeded")
    return results or []


def compute_analytics(awards: list[dict], max_unit_price: float | None = None,
                      fsc_code: str | None = None) -> dict:
    """
    Floor   = lowest award (market minimum — don't expect to win below it).
    Ceiling = CPI-adjusted rolling average (never bid above it).
    Median  = sanity check.
    """
    amounts: list[float] = []
    award_metadata: list[dict] = []

    for award in awards:
        raw_amount = award.get("Award Amount")
        if raw_amount is None:
            continue
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        if max_unit_price and amount > max_unit_price:
            continue
        amounts.append(amount)
        award_metadata.append({
            "amount": amount,
            "date": award.get("Start Date"),
            "recipient": award.get("Recipient Name"),
            "agency": award.get("Awarding Agency"),
        })

    if not amounts:
        return {
            "status": "filtered_empty",
            "message": "Awards found but all filtered out by price constraints.",
            "floor_price_usd": None, "ceiling_price_usd": None, "median_price_usd": None,
            "sample_size": 0, "unique_recipients": 0,
        }

    floor_price = min(amounts)
    raw_average = mean(amounts)
    median_price = median(amounts)
    ceiling_price = raw_average * ((1 + INFLATION_RATE_ANNUAL) ** FPDS_LOOKBACK_YEARS)

    top_psc = str(fsc_code or "")
    fsc_label = FSC_COMMODITY_MAP.get(top_psc[:4], "Unknown") if top_psc else "Unknown"
    recipients = {a["recipient"] for a in award_metadata if a["recipient"]}

    return {
        "status": "success",
        "sample_size": len(amounts),
        "lookback_years": FPDS_LOOKBACK_YEARS,
        "floor_price_usd": round(floor_price, 2),
        "ceiling_price_usd": round(ceiling_price, 2),
        "median_price_usd": round(median_price, 2),
        "raw_average_usd": round(raw_average, 2),
        "inflation_adjustment_pct": round(INFLATION_RATE_ANNUAL * 100, 1),
        "dominant_psc_code": top_psc,
        "psc_label": fsc_label,
        # Competition signal: fewer unique winners = softer market
        "unique_recipients": len(recipients),
        "top_recipients": list(recipients)[:5],
        "note": (
            "Ceiling is the CPI-adjusted 3-year average — bid at or below this. "
            "Floor is your absolute minimum — do not expect to win below this."
        ),
    }


def get_historical_pricing(
    commodity_description: str,
    naics_code: str | None = None,
    fsc_code: str | None = None,
    nsn: str | None = None,
    max_unit_price: float | None = None,
    http_post: Callable[..., requests.Response] | None = None,
) -> dict:
    awards = fetch_awards(commodity_description, naics_code, fsc_code, nsn, http_post)
    if not awards:
        return {
            "status": "no_data",
            "message": f"No historical awards found for '{commodity_description}'.",
            "floor_price_usd": None, "ceiling_price_usd": None, "median_price_usd": None,
            "sample_size": 0, "unique_recipients": 0,
        }
    return compute_analytics(awards, max_unit_price, fsc_code)


# ── Optional CrewAI wrapper ───────────────────────────────────────────────────
try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    class FpdsQueryInput(BaseModel):
        commodity_description: str = Field(description="Plain-English commodity name, e.g. 'nitrile exam gloves'")
        naics_code: str | None = Field(default=None, description="6-digit NAICS code")
        fsc_code: str | None = Field(default=None, description="4-digit Federal Supply Class code")
        nsn: str | None = Field(default=None, description="13-digit National Stock Number")
        max_unit_price: float | None = Field(default=None, description="Filter out awards above this price")

    class FetchHistoricalPricingTool(BaseTool):
        name: str = "fetch_historical_pricing"
        description: str = (
            "Retrieves FPDS historical award prices for a commodity and calculates "
            "Floor, CPI-adjusted Ceiling, and Median price. Returns JSON analytics."
        )
        args_schema: type[BaseModel] = FpdsQueryInput

        def _run(self, commodity_description, naics_code=None, fsc_code=None, nsn=None, max_unit_price=None):
            return json.dumps(
                get_historical_pricing(commodity_description, naics_code, fsc_code, nsn, max_unit_price),
                indent=2, default=str,
            )
except ImportError:
    FetchHistoricalPricingTool = None  # type: ignore
