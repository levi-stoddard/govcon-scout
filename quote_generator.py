"""
quote_generator.py — Tier 4: one-click quote sheet per lead.

Produces a plain-text quote worksheet with everything pre-filled from the
lead's data plus your company profile (.env). YOU review, complete, and
submit — the system preps, you sign. Never auto-submits anything.

Company profile (.env):
  COMPANY_NAME=            COMPANY_CAGE=
  COMPANY_UEI=             COMPANY_POC=
  COMPANY_EMAIL=           COMPANY_PHONE=
"""

from __future__ import annotations
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


def company_profile() -> dict:
    return {
        "name": os.getenv("COMPANY_NAME", "[YOUR COMPANY NAME]"),
        "cage": os.getenv("COMPANY_CAGE", "[CAGE CODE — pending SAM registration]"),
        "uei": os.getenv("COMPANY_UEI", "[UEI — assigned by SAM.gov]"),
        "poc": os.getenv("COMPANY_POC", "[POINT OF CONTACT]"),
        "email": os.getenv("COMPANY_EMAIL", "[EMAIL]"),
        "phone": os.getenv("COMPANY_PHONE", "[PHONE]"),
    }


def _fmt(val, prefix="$") -> str:
    if val is None:
        return "[VERIFY]"
    try:
        return f"{prefix}{float(val):,.2f}"
    except (TypeError, ValueError):
        return str(val)


def build_quote_sheet(lead: dict, quoted_price: float | None = None) -> str:
    """Render a quote worksheet as text. Works on any lead dict from the pipeline/db."""
    data = lead.get("data", lead)  # accepts either a db row or a raw pipeline lead
    co = company_profile()
    compliance = data.get("compliance") or {}
    price = quoted_price or data.get("recommended_max_bid_usd")

    lines = [
        "=" * 68,
        "QUOTE WORKSHEET — prepared by GovCon Scout",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
        "REVIEW EVERY LINE BEFORE SUBMITTING. This is a worksheet, not a bid.",
        "=" * 68,
        "",
        "── SOLICITATION ──────────────────────────────────────────────────",
        f"  Notice / RFQ #   : {data.get('solicitation_number') or data.get('notice_id', '')}",
        f"  Title            : {data.get('title', '')}",
        f"  Agency           : {data.get('agency', '')}",
        f"  Type             : {data.get('notice_type', '')}",
        f"  Set-aside        : {data.get('setaside_label', 'None')}",
        f"  Response deadline: {str(data.get('response_deadline') or '[CHECK]')[:16]}",
        f"  Link             : {data.get('solicitation_url', '')}",
        f"  NSN              : {data.get('nsn') or '[N/A]'}",
        f"  Ship to          : {', '.join(p for p in [data.get('pop_city'), data.get('pop_state'), data.get('pop_zip')] if p) or '[SEE SOLICITATION]'}",
        "",
        "── YOUR COMPANY ──────────────────────────────────────────────────",
        f"  Company          : {co['name']}",
        f"  CAGE             : {co['cage']}",
        f"  UEI              : {co['uei']}",
        f"  POC              : {co['poc']}  |  {co['email']}  |  {co['phone']}",
        "",
        "── PRICING ───────────────────────────────────────────────────────",
        f"  Supplier cost    : {_fmt(data.get('supplier_unit_cost_usd'))}"
        + ("   ⚠ ESTIMATE — VERIFY BEFORE QUOTING" if not data.get("supplier_cost_verified") else "   (verified quote)"),
        f"  Supplier source  : {data.get('supplier_cost_source', '[RECORD WHERE YOU GOT THE PRICE]')}",
        f"  Shipping         : {_fmt(data.get('shipping_cost_usd'))}",
        f"  Total COGS       : {_fmt(data.get('total_cogs_usd'))}",
        f"  Market floor     : {_fmt(data.get('floor_price_usd'))}",
        f"  Market ceiling   : {_fmt(data.get('ceiling_price_usd'))}",
        "",
        f"  >>> YOUR QUOTE PRICE : {_fmt(price)} <<<",
        f"  Margin at this price : {data.get('actual_margin_pct', '[CALC]')}%",
        "",
        "── COMPLIANCE CHECKLIST ──────────────────────────────────────────",
        f"  Pipeline verdict : {compliance.get('verdict', 'NOT CHECKED')}",
        "  [ ] Read the FULL solicitation document (not just the synopsis)",
        "  [ ] Country of origin confirmed with supplier certificate",
        "  [ ] BAA/TAA requirement satisfied for that country",
    ]
    for flag in compliance.get("fatal_flags", []):
        lines.append(f"  [!] FATAL: {flag}")
    for flag in compliance.get("warning_flags", []):
        lines.append(f"  [ ] RESOLVE: {flag}")
    lines += [
        "  [ ] 52.219-14 check: I am the manufacturer or a regular dealer",
        "  [ ] Packaging/labeling requirements read (MIL-STD-129 if DoD)",
        "  [ ] Delivery timeline is achievable with my supplier's stock",
        "",
        "── SUBMIT ────────────────────────────────────────────────────────",
        "  DIBBS RFQs : quote at https://www.dibbs.bsm.dla.mil (needs CAGE)",
        "  SAM.gov    : follow submission instructions in the solicitation",
        "",
        "=" * 68,
    ]
    return "\n".join(lines)
