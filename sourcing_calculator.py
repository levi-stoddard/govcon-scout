"""
sourcing_calculator.py — Bid Sourcing & Margin Calculator
Helps calculate target bid prices from supplier costs,
market data, and shipping estimates.
"""

from __future__ import annotations
import requests
import logging

logger = logging.getLogger(__name__)

COMMON_SUPPLIERS = {
    "Grainger": "https://www.grainger.com/search?searchQuery=",
    "Zoro": "https://www.zoro.com/search?q=",
    "Amazon Business": "https://www.amazon.com/s?k=",
    "MSC Industrial": "https://www.mscdirect.com/browse/?searchterm=",
    "McMaster-Carr": "https://www.mcmaster.com/#",
}

FSC_CATEGORIES = {
    "8430 — Safety Footwear": {"naics": "316210", "avg_markup": 0.35},
    "4240 — Safety Equipment / Glasses": {"naics": "339113", "avg_markup": 0.40},
    "8415 — Protective Clothing / Gloves": {"naics": "339999", "avg_markup": 0.38},
    "5120 — Hand Tools": {"naics": "332212", "avg_markup": 0.32},
    "7510 — Office Supplies": {"naics": "453210", "avg_markup": 0.28},
    "7930 — Cleaning Supplies": {"naics": "325612", "avg_markup": 0.30},
    "6505 — Medical Supplies / Gloves": {"naics": "339113", "avg_markup": 0.42},
    "9905 — Signs & Labels": {"naics": "339950", "avg_markup": 0.35},
}

WEIGHT_ESTIMATES = {
    "8430 — Safety Footwear": 4.0,
    "4240 — Safety Equipment / Glasses": 0.5,
    "8415 — Protective Clothing / Gloves": 1.0,
    "5120 — Hand Tools": 3.0,
    "7510 — Office Supplies": 2.0,
    "7930 — Cleaning Supplies": 5.0,
    "6505 — Medical Supplies / Gloves": 1.5,
    "9905 — Signs & Labels": 1.0,
}


def estimate_shipping(weight_lbs: float, destination_state: str) -> dict:
    """
    Freight-aware shipping estimate.
    Under 50 lbs: parcel rates (USPS/UPS ground).
    Over 50 lbs: LTL freight rates (pallet shipment).
    weight_lbs is the TOTAL shipment weight, not per-unit.
    """
    far_states = {"AK", "HI", "PR", "GU"}
    far = destination_state.upper() in far_states

    if weight_lbs <= 1:
        base = 8.50
    elif weight_lbs <= 5:
        base = 14.00
    elif weight_lbs <= 20:
        base = 22.00
    elif weight_lbs <= 50:
        base = round(35.00 + (weight_lbs - 20) * 0.80, 2)
    elif weight_lbs <= 150:
        # UPS/FedEx ground heavy parcel
        base = round(55.00 + (weight_lbs - 50) * 0.35, 2)
    elif weight_lbs <= 500:
        # LTL freight estimate
        base = round(120.00 + (weight_lbs - 150) * 0.25, 2)
    else:
        # Full pallet freight
        base = round(250.00 + (weight_lbs - 500) * 0.15, 2)

    if far:
        base = round(base * 2.5, 2)

    return {
        "estimated_shipping_usd": base,
        "weight_lbs": weight_lbs,
        "note": "Flat-rate estimate — verify with USPS or carrier before bidding",
    }


def calculate_bid(
    supplier_cost: float,
    quantity: int,
    shipping_cost: float,
    target_margin_pct: float,
    market_ceiling: float | None = None,
) -> dict:
    """
    Full bid calculation with margin enforcement.
    Returns recommended bid, margin, and Go/No-Go.
    """
    total_cogs = (supplier_cost * quantity) + shipping_cost
    margin_decimal = target_margin_pct / 100
    min_bid = round(total_cogs / (1 - margin_decimal), 2)

    if market_ceiling and market_ceiling > 0:
        recommended_bid = min(min_bid, market_ceiling)
    else:
        recommended_bid = min_bid

    actual_margin = (
        (recommended_bid - total_cogs) / recommended_bid
        if recommended_bid > 0 else 0
    )

    go_no_go = actual_margin >= (margin_decimal - 0.001) and total_cogs > 0

    # Price per unit
    price_per_unit = round(recommended_bid / quantity, 2) if quantity > 0 else 0

    return {
        "supplier_unit_cost": round(supplier_cost, 2),
        "quantity": quantity,
        "total_product_cost": round(supplier_cost * quantity, 2),
        "shipping_cost": round(shipping_cost, 2),
        "total_cogs": round(total_cogs, 2),
        "market_ceiling": market_ceiling,
        "recommended_bid": round(recommended_bid, 2),
        "price_per_unit": price_per_unit,
        "gross_profit": round(recommended_bid - total_cogs, 2),
        "actual_margin_pct": round(actual_margin * 100, 1),
        "target_margin_pct": target_margin_pct,
        "go_no_go": go_no_go,
        "verdict": "✅ GO — Submit this bid" if go_no_go else "❌ NO-GO — Below margin floor",
    }


def get_market_data(keyword: str, days_back: int = 180) -> dict:
    """
    Pull quick market stats from USASpending for the keyword.
    Returns avg, min, max award prices.
    """
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    payload = {
        "filters": {
            "keywords": [keyword],
            "time_period": [{"start_date": start_date, "end_date": end_date}],
            "award_type_codes": ["A", "B", "C", "D"],
        },
        "fields": ["Award Amount", "Recipient Name"],
        "sort": "Award Amount",
        "order": "desc",
        "limit": 50,
        "page": 1,
    }

    try:
        resp = requests.post(
            "https://api.usaspending.gov/api/v2/search/spending_by_award/",
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception:
        return {}

    amounts = [
        float(r["Award Amount"])
        for r in results
        if r.get("Award Amount") and float(r["Award Amount"]) > 0
    ]

    if not amounts:
        return {}

    return {
        "sample_size": len(amounts),
        "market_avg": round(sum(amounts) / len(amounts), 2),
        "market_min": round(min(amounts), 2),
        "market_max": round(max(amounts), 2),
        "market_ceiling": round(sum(amounts) / len(amounts), 2),
    }


def build_supplier_links(product_name: str) -> list[dict]:
    """Build quick-search URLs for each supplier."""
    query = product_name.replace(" ", "+")
    links = []
    for supplier, base_url in COMMON_SUPPLIERS.items():
        links.append({
            "supplier": supplier,
            "search_url": f"{base_url}{query}",
        })
    return links
