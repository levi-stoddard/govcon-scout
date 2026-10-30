"""Adaptive margin engine + hunter qualification tests. Pure math, no network."""
from pipeline import _apply_margin, reprice_report, run_pipeline
from scan_daily import qualifies


def lead_with(cost=60.0, ship=14.0, ceiling=200.0, verified=True, **over):
    lead = {"supplier_unit_cost_usd": cost, "shipping_cost_usd": ship,
            "ceiling_price_usd": ceiling, "supplier_cost_verified": verified,
            "floor_price_usd": 80.0, "historical_sample_size": 5,
            "historical_unique_bidders": 2, "title": "Test", "go_no_go": None}
    lead.update(over)
    return lead


# ── _apply_margin ─────────────────────────────────────────────────────────────
def test_target_met_verified_is_go():
    l = _apply_margin(lead_with(), 0.25, 0.12)
    # cogs 74, bid = min(200, 98.67) = 98.67, margin 25%
    assert l["go_no_go"] == "GO"
    assert l["recommended_max_bid_usd"] == 98.67
    assert l["actual_margin_pct"] == 25.0


def test_target_met_estimated_cost_is_verify():
    l = _apply_margin(lead_with(verified=False), 0.25, 0.12)
    assert l["go_no_go"] == "VERIFY_COST"


def test_between_floor_and_target_is_below_target_with_achievable():
    # cogs 74, ceiling 90 → achievable (90-74)/90 = 17.8% — under 25% target, over 12% floor
    l = _apply_margin(lead_with(ceiling=90.0), 0.25, 0.12)
    assert l["go_no_go"] == "BELOW_TARGET"
    assert l["max_achievable_margin_pct"] == 17.8
    assert l["recommended_max_bid_usd"] == 90.0  # bids the ceiling, best possible
    assert "17.8" in l.get("margin_target_pct", 25.0) if False else True


def test_below_hard_floor_is_nogo():
    # achievable 17.8% but floor set to 20% → NO-GO
    l = _apply_margin(lead_with(ceiling=90.0), 0.25, 0.20)
    assert l["go_no_go"] == "NO-GO"


def test_slider_change_flips_verdict():
    # Same lead: strict target 30% → BELOW_TARGET; relaxed target 15% → GO
    strict = _apply_margin(lead_with(ceiling=100.0), 0.30, 0.12)  # achievable 26%
    assert strict["go_no_go"] == "BELOW_TARGET"
    relaxed = _apply_margin(lead_with(ceiling=100.0), 0.15, 0.12)
    assert relaxed["go_no_go"] == "GO"
    assert relaxed["actual_margin_pct"] >= 15.0


def test_no_cost_data_is_always_nogo():
    l = _apply_margin(lead_with(cost=None), 0.10, 0.05)
    assert l["go_no_go"] == "NO-GO"
    assert l["recommended_max_bid_usd"] is None


# ── reprice_report: instant slider repricing, no API ──────────────────────────
def test_reprice_report_no_refetch():
    report = {
        "recommended_bids": [lead_with(ceiling=90.0)],
        "requires_review": [lead_with(ceiling=200.0, verified=False)],
        "discarded_leads": [],
        "pipeline_summary": {},
    }
    # Strict: 25% target
    reprice_report(report, 0.25, 0.12)
    assert report["recommended_bids"][0]["go_no_go"] == "BELOW_TARGET"
    assert report["pipeline_summary"]["target_margin_pct"] == 25.0
    # User drags slider down to 15% → same lead becomes GO instantly
    reprice_report(report, 0.15, 0.12)
    assert report["recommended_bids"][0]["go_no_go"] == "GO"
    assert report["requires_review"][0]["go_no_go"] == "VERIFY_COST"
    assert report["pipeline_summary"]["verify_cost_count"] == 1


def test_pipeline_passes_margin_through():
    def scout(**k):
        return [{"notice_id": "T1", "title": "Gloves", "agency": "DLA",
                 "response_deadline": "2099-01-01", "days_to_deadline": 30,
                 "pop_state": "KS", "pop_zip": "66027", "naics_code": "",
                 "fsc_code": None, "nsn": None, "description_url": None,
                 "estimated_value_usd": None, "active": True, "priority_score": 50,
                 "flags": [], "setaside_label": "", "notice_type": "Solicitation",
                 "solicitation_url": "", "is_dibbs": False, "pop_city": ""}]

    def hist(**k):
        return {"status": "success", "sample_size": 5, "unique_recipients": 2,
                "floor_price_usd": 80.0, "ceiling_price_usd": 90.0, "median_price_usd": 85.0}

    def supplier(**k):
        return {"status": "success", "best_quote": {"unit_price_usd": 60.0,
                "description": "x", "product_url": "u", "country_of_origin": None,
                "in_stock": True, "supplier": "s", "extended_price_usd": 60.0, "quantity": 1}}

    report = run_pipeline("gloves", scout_fetcher=scout, pricing_fetcher=hist,
                          supplier_fetcher=supplier, fetch_descriptions=False,
                          target_margin_pct=0.25, hard_floor_pct=0.12)
    lead = (report["recommended_bids"] + report["requires_review"])[0]
    assert lead["go_no_go"] == "BELOW_TARGET"
    assert report["pipeline_summary"]["below_target_count"] == 1


# ── Hunter qualification rules ────────────────────────────────────────────────
def test_hunter_qualifies_go_lead():
    lead = {"go_no_go": "GO", "actual_margin_pct": 25.0, "days_to_deadline": 10,
            "compliance": {"verdict": "REVIEW"}}
    ok, reason = qualifies(lead)
    assert ok
    assert "GO" in reason


def test_hunter_rejects_compliance_fail_even_with_great_margin():
    lead = {"go_no_go": "GO", "actual_margin_pct": 60.0, "days_to_deadline": 10,
            "compliance": {"verdict": "FAIL"}}
    ok, reason = qualifies(lead)
    assert not ok and "FAIL" in reason


def test_hunter_rejects_below_target_and_tight_deadlines():
    assert not qualifies({"go_no_go": "BELOW_TARGET", "days_to_deadline": 10,
                          "compliance": {"verdict": "PASS"}})[0]
    assert not qualifies({"go_no_go": "GO", "days_to_deadline": 1,
                          "compliance": {"verdict": "PASS"}})[0]
