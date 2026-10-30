"""End-to-end pipeline tests with injected fetchers — no network, no LLM, $0."""
from pipeline import run_pipeline, price_lead


def make_lead(**overrides):
    lead = {
        "notice_id": "TEST-001",
        "title": "Nitrile Exam Gloves, Large, Box of 100",
        "agency": "Test Agency",
        "naics_code": "325612",
        "notice_type": "Combined Synopsis/Solicitation",
        "setaside_code": "SBA",
        "setaside_label": "Total Small Business",
        "estimated_value_usd": None,
        "response_deadline": "2099-01-01",
        "days_to_deadline": 30,
        "pop_zip": "66027",
        "pop_city": "Ft Leavenworth",
        "pop_state": "KS",
        "nsn": None,
        "fsc_code": "7920",
        "is_dibbs": False,
        "active": True,
        "description_url": "https://example.test/desc",
        "solicitation_url": "https://sam.gov/test",
        "priority_score": 80,
        "flags": [],
    }
    lead.update(overrides)
    return lead


def hist_ok(**kwargs):
    return {
        "status": "success", "sample_size": 12, "unique_recipients": 3,
        "floor_price_usd": 80.0, "ceiling_price_usd": 200.0, "median_price_usd": 120.0,
    }


def hist_empty(**kwargs):
    return {"status": "no_data", "sample_size": 0, "unique_recipients": 0,
            "floor_price_usd": None, "ceiling_price_usd": None, "median_price_usd": None}


def supplier_real(**kwargs):
    return {"status": "success", "best_quote": {
        "supplier": "Google Shopping", "unit_price_usd": 60.0, "extended_price_usd": 60.0,
        "quantity": 1, "description": "Gloves box 100", "product_url": "https://x.test/p",
        "country_of_origin": None, "in_stock": True}}


def supplier_none(**kwargs):
    return {"status": "no_quotes", "message": "nothing"}


def desc_with_baa(url, **kwargs):
    return "Includes FAR 52.225-1 Buy American — Supplies."


def desc_clean(url, **kwargs):
    return "Commercial item purchase. FOB destination. NET 30."


# ── price_lead ────────────────────────────────────────────────────────────────
def test_real_quote_and_margin_gives_go():
    lead = price_lead(make_lead(), "gloves", hist_ok, supplier_real, {})
    # cogs = 60 + 14 (5lb KS) = 74; bid = min(200, 74/.75=98.67) = 98.67; margin 25%
    assert lead["supplier_cost_verified"] is True
    assert lead["total_cogs_usd"] == 74.0
    assert lead["recommended_max_bid_usd"] == 98.67
    assert lead["go_no_go"] == "GO"


def test_estimated_cost_never_go_only_verify():
    lead = price_lead(make_lead(), "gloves", hist_ok, supplier_none, {})
    # estimate = 80 * 0.55 = 44.0 — margin fine, but NOT verified
    assert lead["supplier_unit_cost_usd"] == 44.0
    assert lead["supplier_cost_verified"] is False
    assert lead["go_no_go"] == "VERIFY_COST"
    assert "ESTIMATE" in lead["supplier_cost_source"]


def test_no_data_at_all_is_no_go():
    lead = price_lead(make_lead(), "gloves", hist_empty, supplier_none, {})
    assert lead["go_no_go"] == "NO-GO"
    assert lead["recommended_max_bid_usd"] is None


def test_bid_note_always_present_and_honest():
    lead = price_lead(make_lead(), "gloves", hist_ok, supplier_none, {})
    assert "ESTIMATE" in lead["supplier_cost_source"]
    assert "verify" in lead["bid_note"].lower()


# ── run_pipeline ──────────────────────────────────────────────────────────────
def scout_two(**kwargs):
    return [make_lead(), make_lead(notice_id="TEST-002", title="Gloves, Leather Work")]


def test_pipeline_report_structure_unchanged_for_app():
    report = run_pipeline(
        "gloves", scout_fetcher=scout_two, pricing_fetcher=hist_ok,
        supplier_fetcher=supplier_real, description_fetcher=desc_clean,
    )
    for key in ("recommended_bids", "requires_review", "discarded_leads", "pipeline_summary"):
        assert key in report
    assert report["pipeline_summary"]["total_leads_evaluated"] == 2


def test_unknown_coo_with_baa_clause_goes_to_review():
    report = run_pipeline(
        "gloves", scout_fetcher=scout_two, pricing_fetcher=hist_ok,
        supplier_fetcher=supplier_real, description_fetcher=desc_with_baa,
    )
    # BAA clause found + COO unknown → REVIEW, never PASS, never assumed US
    assert len(report["requires_review"]) == 2
    assert len(report["recommended_bids"]) == 0


def test_clean_full_text_passes_compliance():
    report = run_pipeline(
        "gloves", scout_fetcher=scout_two, pricing_fetcher=hist_ok,
        supplier_fetcher=supplier_real, description_fetcher=desc_clean,
        country_of_origin="US",
    )
    assert len(report["recommended_bids"]) == 2
    assert report["pipeline_summary"]["bid_ready_count"] == 2


def test_no_description_available_downgrades_to_review():
    report = run_pipeline(
        "gloves",
        scout_fetcher=lambda **k: [make_lead(description_url=None)],
        pricing_fetcher=hist_ok, supplier_fetcher=supplier_real,
        description_fetcher=desc_clean, country_of_origin="US",
    )
    # Title-only scan can never PASS
    assert len(report["requires_review"]) == 1
    assert len(report["recommended_bids"]) == 0


def test_empty_scout_returns_graceful_empty_report():
    report = run_pipeline("xyzzy", scout_fetcher=lambda **k: [])
    assert report["pipeline_summary"]["total_leads_evaluated"] == 0
    assert "No live opportunities" in report["pipeline_summary"]["note"]
