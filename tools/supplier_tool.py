"""
tools/supplier_tool.py — Analyst Tool #2
Real supplier pricing via Google CSE (Shopping results). A lead can only be
marked GO when a REAL price is found here — estimates get VERIFY_COST.

Logic lives in a plain function (testable). CrewAI wrapper optional.
"""

from __future__ import annotations
import json
import logging
from typing import Callable

import requests

from config import GOOGLE_CSE_API_KEY, GOOGLE_CSE_ID

logger = logging.getLogger(__name__)


def get_supplier_pricing(
    commodity_description: str,
    nsn: str | None = None,
    target_quantity: int = 1,
    max_unit_price: float | None = None,
    http_get: Callable[..., requests.Response] | None = None,
) -> dict:
    """
    Returns {"status": "success", "best_quote": {...}, "all_quotes": [...]}
    or {"status": "no_quotes", "message": ...}.
    A "success" here is the ONLY thing that allows a GO verdict downstream.
    """
    query = nsn if nsn else commodity_description
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_ID:
        return {"status": "no_quotes", "message": "No supplier API configured."}

    get = http_get or requests.get
    params = {"key": GOOGLE_CSE_API_KEY, "cx": GOOGLE_CSE_ID, "q": f"{query} price buy", "num": 5}
    try:
        resp = get("https://www.googleapis.com/customsearch/v1", params=params, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        body = getattr(getattr(exc, "response", None), "text", "")[:200]
        if status == 403:
            msg = ("Google CSE key rejected (403): enable 'Custom Search API' for this key at "
                   "console.cloud.google.com, or the free 100/day quota is used up. "
                   "Leads will show VERIFY_COST until then — use the supplier links.")
        else:
            msg = f"Google CSE error {status}: {body}"
        logger.warning(msg)
        return {"status": "no_quotes", "message": msg}
    except requests.RequestException as exc:
        logger.warning("Google CSE network error: %s", exc)
        return {"status": "no_quotes", "message": str(exc)}

    quotes = []
    for item in items:
        offers = item.get("pagemap", {}).get("offer", [])
        for offer in offers[:1]:
            try:
                price_raw = str(offer.get("price", "0")).replace("$", "").replace(",", "").strip()
                price = float(price_raw)
            except (ValueError, TypeError):
                continue
            if price <= 0:
                continue
            if max_unit_price and price > max_unit_price:
                continue
            quotes.append({
                "supplier": "Google Shopping",
                "unit_price_usd": price,
                "description": item.get("title", commodity_description)[:80],
                "product_url": item.get("link"),
                "country_of_origin": None,  # CSE never provides COO — compliance stays REVIEW
                "in_stock": True,
            })

    if not quotes:
        return {"status": "no_quotes", "message": f"No pricing found for '{commodity_description}'"}

    quotes.sort(key=lambda x: x["unit_price_usd"])
    best = quotes[0]
    return {
        "status": "success",
        "best_quote": {
            "supplier": best["supplier"],
            "unit_price_usd": best["unit_price_usd"],
            "extended_price_usd": round(best["unit_price_usd"] * target_quantity, 2),
            "quantity": target_quantity,
            "description": best["description"],
            "product_url": best["product_url"],
            "country_of_origin": best["country_of_origin"],
            "in_stock": best["in_stock"],
        },
        "all_quotes": quotes[:3],
    }


# ── Optional CrewAI wrapper ───────────────────────────────────────────────────
try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    class SupplierQueryInput(BaseModel):
        commodity_description: str = Field(description="Commodity name to search")
        nsn: str | None = Field(default=None)
        target_quantity: int = Field(default=1)
        max_unit_price: float | None = Field(default=None)

    class FetchSupplierPricingTool(BaseTool):
        name: str = "fetch_supplier_pricing"
        description: str = "Fetches real-time pricing from suppliers via Google Shopping search."
        args_schema: type[BaseModel] = SupplierQueryInput

        def _run(self, commodity_description, nsn=None, target_quantity=1, max_unit_price=None):
            return json.dumps(
                get_supplier_pricing(commodity_description, nsn, target_quantity, max_unit_price),
                indent=2,
            )
except ImportError:
    FetchSupplierPricingTool = None  # type: ignore
