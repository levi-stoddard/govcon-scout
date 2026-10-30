"""Bid math tests — the numbers that decide real money. Pure Python, no network."""
from sourcing_calculator import calculate_bid, estimate_shipping


def test_margin_math_exact():
    # cogs = 100*1 + 14 = 114; bid at 25% margin = 114 / 0.75 = 152.00
    r = calculate_bid(supplier_cost=100.0, quantity=1, shipping_cost=14.0,
                      target_margin_pct=25.0, market_ceiling=None)
    assert r["total_cogs"] == 114.0
    assert r["recommended_bid"] == 152.0
    assert r["actual_margin_pct"] == 25.0
    assert r["go_no_go"] is True


def test_ceiling_caps_the_bid():
    r = calculate_bid(supplier_cost=100.0, quantity=1, shipping_cost=14.0,
                      target_margin_pct=25.0, market_ceiling=130.0)
    assert r["recommended_bid"] == 130.0
    # margin at ceiling: (130-114)/130 = 12.3% < 25% → NO-GO
    assert r["go_no_go"] is False


def test_quantity_scales_cogs():
    r = calculate_bid(supplier_cost=10.0, quantity=100, shipping_cost=50.0,
                      target_margin_pct=25.0, market_ceiling=None)
    assert r["total_cogs"] == 1050.0
    assert r["recommended_bid"] == 1400.0
    assert r["price_per_unit"] == 14.0


def test_zero_cost_is_never_go():
    r = calculate_bid(supplier_cost=0.0, quantity=1, shipping_cost=0.0,
                      target_margin_pct=25.0)
    assert r["go_no_go"] is False


def test_shipping_tiers_and_far_state_multiplier():
    light = estimate_shipping(0.5, "VA")["estimated_shipping_usd"]
    mid = estimate_shipping(5.0, "VA")["estimated_shipping_usd"]
    heavy = estimate_shipping(300.0, "VA")["estimated_shipping_usd"]
    alaska = estimate_shipping(5.0, "AK")["estimated_shipping_usd"]
    assert light == 8.50
    assert mid == 14.00
    assert heavy > mid
    assert alaska == round(14.00 * 2.5, 2)
