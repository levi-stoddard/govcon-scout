"""
tools/shipping_tool.py — Analyst Tool #3
Flat-rate shipping estimate + bid spread calculation.
Delegates all math to sourcing_calculator (single source of truth).
CrewAI wrapper optional.
"""

from __future__ import annotations
import json
import logging

from config import MINIMUM_MARGIN_PCT
from sourcing_calculator import estimate_shipping, calculate_bid

logger = logging.getLogger(__name__)


def calculate_shipping_and_spread(
    destination_zip: str,
    destination_state: str,
    weight_lbs: float = 5.0,
    ceiling_price_usd: float = 0.0,
    supplier_unit_cost_usd: float = 0.0,
    quantity: int = 1,
) -> dict:
    shipping = estimate_shipping(weight_lbs, destination_state or "VA")
    shipping_cost = shipping["estimated_shipping_usd"]
    bid = calculate_bid(
        supplier_cost=supplier_unit_cost_usd,
        quantity=quantity,
        shipping_cost=shipping_cost,
        target_margin_pct=MINIMUM_MARGIN_PCT * 100,
        market_ceiling=ceiling_price_usd if ceiling_price_usd > 0 else None,
    )
    return {
        "shipping_method": "Flat-Rate Estimate",
        "shipping_cost_usd": shipping_cost,
        "verified": False,
        "spread_analysis": {
            "supplier_unit_cost_usd": bid["supplier_unit_cost"],
            "quantity": quantity,
            "shipping_cost_usd": bid["shipping_cost"],
            "total_cogs_usd": bid["total_cogs"],
            "ceiling_price_usd": round(ceiling_price_usd, 2),
            "recommended_max_bid_usd": bid["recommended_bid"],
            "actual_margin_pct": bid["actual_margin_pct"],
            "go_no_go": "GO" if bid["go_no_go"] else "NO-GO",
        },
    }


# ── Optional CrewAI wrapper ───────────────────────────────────────────────────
try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    class ShippingCalcInput(BaseModel):
        destination_zip: str = Field(description="5-digit ZIP code")
        destination_state: str = Field(description="2-letter state code")
        destination_city: str = Field(default="")
        weight_lbs: float = Field(default=5.0)
        ceiling_price_usd: float = Field(default=0.0)
        supplier_unit_cost_usd: float = Field(default=0.0)
        quantity: int = Field(default=1)

    class CalculateShippingAndSpreadTool(BaseTool):
        name: str = "calculate_shipping_and_spread"
        description: str = f"Estimates shipping and computes Recommended Max Bid with {MINIMUM_MARGIN_PCT:.0%} margin."
        args_schema: type[BaseModel] = ShippingCalcInput

        def _run(self, destination_zip, destination_state, destination_city="",
                 weight_lbs=5.0, ceiling_price_usd=0.0, supplier_unit_cost_usd=0.0, quantity=1):
            return json.dumps(
                calculate_shipping_and_spread(
                    destination_zip, destination_state, weight_lbs,
                    ceiling_price_usd, supplier_unit_cost_usd, quantity,
                ),
                indent=2, default=str,
            )
except ImportError:
    CalculateShippingAndSpreadTool = None  # type: ignore
