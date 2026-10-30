"""
smoke_test.py — LIVE end-to-end check against the real (free) APIs.

Run this on YOUR machine (needs internet + your .env):
    python smoke_test.py [keyword]

Costs $0: SAM.gov and USASpending are free, no LLM is called.
NOTE: uses your SAM.gov daily API quota (a few requests). Results are
cached in .cache/ so re-runs on the same day are free.
"""

from __future__ import annotations
import json
import sys

from pipeline import run_pipeline


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "nitrile gloves"
    print(f"\n=== GovCon Scout LIVE smoke test: '{keyword}' ===\n")

    report = run_pipeline(keyword, max_leads=10, fetch_descriptions=True)
    summary = report["pipeline_summary"]

    print(f"Leads evaluated : {summary['total_leads_evaluated']}")
    print(f"Cleared (PASS)  : {summary['cleared_count']}")
    print(f"Needs review    : {summary['review_count']}")
    print(f"Discarded       : {summary['discarded_count']}")
    print(f"Bid-ready (GO)  : {summary.get('bid_ready_count', 0)}")
    print(f"Verify cost     : {summary.get('verify_cost_count', 0)}")
    print(f"\n{summary.get('note', '')}\n")

    shown = 0
    for bucket, label in (("recommended_bids", "CLEARED"), ("requires_review", "REVIEW")):
        for lead in report[bucket]:
            if shown >= 5:
                break
            shown += 1
            print(f"--- [{label}] {lead['title'][:70]}")
            print(f"    Agency   : {lead['agency']}")
            print(f"    Deadline : {lead.get('response_deadline')} ({lead.get('days_to_deadline')} days)")
            print(f"    Set-aside: {lead.get('setaside_label')}")
            print(f"    Pricing  : floor={lead.get('floor_price_usd')} ceiling={lead.get('ceiling_price_usd')}")
            print(f"    Cost     : {lead.get('supplier_cost_source')}")
            print(f"    Max bid  : {lead.get('recommended_max_bid_usd')}  margin={lead.get('actual_margin_pct')}%")
            print(f"    Status   : {lead.get('go_no_go')} | compliance={lead.get('compliance', {}).get('verdict')}")
            print(f"    Link     : {lead.get('solicitation_url')}")
            print(f"    Note     : {lead.get('bid_note', '')[:160]}")
            print()

    with open("smoke_test_result.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print("Full report saved to smoke_test_result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
