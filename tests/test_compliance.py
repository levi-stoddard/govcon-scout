"""Compliance gate tests — the legal firewall. Pure Python, no network."""
from tools.compliance_tool import run_compliance_check

BAA_TEXT = "This solicitation includes FAR 52.225-1 Buy American — Supplies and 52.225-2."
TAA_TEXT = "Clauses: 52.225-5 Trade Agreements applies to this acquisition."
CLEAN_TEXT = "Standard commercial item purchase, FOB destination, NET 30."


def test_banned_country_is_fatal():
    r = run_compliance_check("N1", BAA_TEXT, country_of_origin="CN")
    assert r["verdict"] == "FAIL"
    assert any("banned" in f.lower() for f in r["fatal_flags"])


def test_unknown_coo_with_baa_clause_is_review_never_pass():
    r = run_compliance_check("N2", BAA_TEXT, country_of_origin=None)
    assert r["verdict"] == "REVIEW"


def test_us_origin_clean_full_text_passes():
    r = run_compliance_check("N3", CLEAN_TEXT, country_of_origin="US", full_text_analyzed=True)
    assert r["verdict"] == "PASS"


def test_title_only_scan_never_passes():
    # THE FIX: a clean scan of just a title proves nothing
    r = run_compliance_check("N4", "Nitrile Gloves", country_of_origin="US",
                             full_text_analyzed=False)
    assert r["verdict"] == "REVIEW"
    assert any("NOT analyzed" in f for f in r["warning_flags"])


def test_taa_country_allowed_under_taa_clause():
    r = run_compliance_check("N5", TAA_TEXT, country_of_origin="DE", full_text_analyzed=True)
    assert r["verdict"] == "PASS"
    assert r["summary"]["taa_compliant"] is True
    assert r["summary"]["requires_domestic_end_product"] is False


def test_non_taa_country_fails_under_taa_clause():
    r = run_compliance_check("N6", TAA_TEXT, country_of_origin="IN", full_text_analyzed=True)
    assert r["verdict"] == "FAIL"


def test_baa_without_taa_requires_domestic():
    r = run_compliance_check("N7", BAA_TEXT, country_of_origin="DE", full_text_analyzed=True)
    assert r["verdict"] == "FAIL"


def test_subcontracting_limitation_flags_review():
    text = CLEAN_TEXT + " Set-aside subject to 52.219-14 Limitations on Subcontracting."
    r = run_compliance_check("N8", text, country_of_origin="US", full_text_analyzed=True)
    assert r["verdict"] == "REVIEW"
    assert any("52.219-14" in f for f in r["warning_flags"])


def test_specialty_metals_detection():
    text = "252.225-7009 applies. Item contains titanium fasteners."
    r = run_compliance_check("N9", text, country_of_origin="US", full_text_analyzed=True)
    assert r["verdict"] == "FAIL"
    assert any("titanium" in f for f in r["fatal_flags"])
