"""Scout tests — real captured SAM.gov v2 response as fixture. No network, no LLM."""
import json
import os

from tools.sam_tool import (
    search_sam_opportunities, normalize_opportunity, extract_nsn,
    extract_fsc, is_dibbs, days_until, score_opportunity,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sam_response.json")


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def fake_get(url, params=None, timeout=None):
    return FakeResponse(load_fixture())


def test_search_returns_normalized_ranked_leads():
    leads = search_sam_opportunities(
        "gloves", api_key="TEST", http_get=fake_get, use_cache=False,
    )
    # Second record's deadline has passed — it must be filtered out
    assert len(leads) == 1
    lead = leads[0]
    assert lead["notice_id"] == "168674dc9e2a462eabbd4edfb4545c7e"
    assert lead["notice_type"] == "Combined Synopsis/Solicitation"
    assert lead["setaside_code"] == "SBA"
    assert lead["fsc_code"] == "7920"
    assert lead["pop_zip"] == "66027"
    assert lead["solicitation_url"].startswith("https://sam.gov/")
    assert lead["description_url"].startswith("https://api.sam.gov/")
    assert 0 <= lead["priority_score"] <= 100


def test_expired_deadline_is_filtered():
    leads = search_sam_opportunities("gloves", api_key="TEST", http_get=fake_get, use_cache=False)
    assert all(l["days_to_deadline"] is None or l["days_to_deadline"] >= 0 for l in leads)


def test_no_api_key_returns_empty_never_crashes():
    assert search_sam_opportunities("gloves", api_key="", use_cache=False) == []


def test_dibbs_detection():
    records = load_fixture()["opportunitiesData"]
    dla = next(r for r in records if r["solicitationNumber"].startswith("SPE"))
    army = next(r for r in records if r["solicitationNumber"].startswith("W911"))
    assert is_dibbs(dla) is True
    assert is_dibbs(army) is False


def test_fsc_extraction_from_classification_and_title_prefix():
    records = load_fixture()["opportunitiesData"]
    assert extract_fsc(records[0]) == "7920"   # classificationCode
    assert extract_fsc(records[1]) == "84"     # DLA '84--GLOVES' title prefix fallback


def test_nsn_extraction():
    assert extract_nsn("GLOVES 8415-01-123-4567 COLD WEATHER") == "8415-01-123-4567"
    assert extract_nsn("GLOVES,FLYERS 8415011234567") == "8415-01-123-4567"
    assert extract_nsn("plain gloves") is None


def test_days_until_handles_bad_input():
    assert days_until(None) is None
    assert days_until("not-a-date") is None
    assert days_until("2099-01-01T00:00:00-05:00") > 0


def test_scoring_penalizes_avoid_fsc():
    opp = {"title": "x", "classificationCode": "6505", "typeOfSetAside": "",
           "responseDeadLine": "2099-01-01", "solicitationNumber": "X1"}
    score, flags = score_opportunity(opp)
    assert any("AVOID" in f for f in flags)


def test_scoring_rewards_eligible_setaside_and_unrestricted():
    base = {"title": "x", "classificationCode": "7920", "responseDeadLine": "2099-01-01",
            "solicitationNumber": "X1"}
    s_eligible, _ = score_opportunity({**base, "typeOfSetAside": "SBA"})
    s_open, _ = score_opportunity({**base, "typeOfSetAside": ""})
    s_ineligible, _ = score_opportunity({**base, "typeOfSetAside": "SDVOSBC"})
    assert s_eligible > s_open > s_ineligible
