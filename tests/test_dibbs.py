"""DIBBS parser tests — synthetic fixtures, no network. The parser must
extract what it can and NEVER crash on unexpected formats."""
from tools.dibbs_tool import parse_rfq_line, parse_rfq_text, to_lead

SAMPLE = """\
SPE1C1-26-T-1360 8415-01-234-5678 GLOVES,FLYERS SUMMER TYPE GS/FRP-2 QTY: 120 07/25/2099
SPE7L3-26-Q-0421 5310012345678 WASHER,FLAT STEEL ZINC 500 EA 08/01/2099
random header line with no useful content
SPE4A626U1877 6505-01-111-2222 BANDAGE,GAUZE STERILE 44 BX 07/30/2099
SPE1C1-26-T-1360 8415-01-234-5678 duplicate line should be deduped 07/25/2099
TOTALLY BROKEN LINE $$$ ???
"""


def test_parse_line_dashed_format():
    r = parse_rfq_line("SPE1C1-26-T-1360 8415-01-234-5678 GLOVES,FLYERS SUMMER QTY: 120 07/25/2099")
    assert r["solicitation_number"] == "SPE1C1-26-T-1360"
    assert r["nsn"] == "8415-01-234-5678"
    assert r["fsc_code"] == "8415"
    assert "GLOVES" in r["title"]
    assert r["response_deadline"] == "2099-07-25"
    assert r["quantity"] == 120


def test_parse_line_compact_format():
    r = parse_rfq_line("SPE4A626U1877 6505011112222 BANDAGE,GAUZE 44 BX 07/30/2099")
    assert r["solicitation_number"] == "SPE4A6-26-U-1877"
    assert r["nsn"] == "6505-01-111-2222"
    assert r["quantity"] == 44


def test_parse_line_garbage_returns_none_never_raises():
    assert parse_rfq_line("TOTALLY BROKEN LINE $$$ ???") is None
    assert parse_rfq_line("") is None
    assert parse_rfq_line("random header line") is None


def test_parse_text_dedupes_and_filters_keyword():
    all_rfqs = parse_rfq_text(SAMPLE)
    assert len(all_rfqs) == 3  # 4 valid lines, 1 duplicate
    gloves = parse_rfq_text(SAMPLE, keyword="gloves")
    assert len(gloves) == 1
    assert gloves[0]["solicitation_number"] == "SPE1C1-26-T-1360"


def test_to_lead_schema_matches_pipeline():
    rfq = parse_rfq_text(SAMPLE, keyword="washer")[0]
    lead = to_lead(rfq, "washers")
    # Must carry every field the pipeline's price_lead/compliance stages touch
    for field in ("notice_id", "title", "agency", "naics_code", "fsc_code", "nsn",
                  "response_deadline", "days_to_deadline", "pop_state", "pop_zip",
                  "is_dibbs", "solicitation_url", "priority_score", "flags",
                  "description_url", "estimated_value_usd", "active"):
        assert field in lead, f"missing {field}"
    assert lead["notice_id"].startswith("DIBBS-")
    assert lead["is_dibbs"] is True
    assert "dibbs.bsm.dla.mil" in lead["solicitation_url"]
