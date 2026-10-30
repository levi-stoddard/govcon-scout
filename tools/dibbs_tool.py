"""
tools/dibbs_tool.py — Tier 3 (EXPERIMENTAL): DLA DIBBS RFQ feed

DIBBS (dibbs.bsm.dla.mil) posts daily batch files of every open RFQ —
thousands of small NSN-based buys, many under the micro-purchase threshold.
This module:

  1. Accepts the DoD consent banner (ASP.NET postback with cookies)
  2. Finds the newest RFQ index file in /Downloads/RFQ/
  3. Parses it with defensive regexes — format drift degrades results,
     never crashes the pipeline

Everything returns [] on any failure, with the reason logged. The main
pipeline treats DIBBS as a bonus source, never a dependency.

NOTE: leads from here carry minimal data (no pricing until the Analyst
stage runs on them). Always open the RFQ on DIBBS before quoting.
"""

from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import Callable

import requests

logger = logging.getLogger(__name__)

DIBBS_BASE = "https://www.dibbs.bsm.dla.mil"
RFQ_INDEX_URL = f"{DIBBS_BASE}/Downloads/RFQ/"

# Solicitation: SPE1C1-26-T-1360 or SPE1C126T1360
SOL_RE = re.compile(r"\b(SPE[A-Z0-9]{3})-?(\d{2})-?([QTRU])-?(\d{4})\b", re.IGNORECASE)
# NSN: 5310-01-234-5678 or 5310012345678
NSN_RE = re.compile(r"\b(\d{4})-?(\d{2})-?(\d{3})-?(\d{4})\b")
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
QTY_RE = re.compile(r"\bQTY[:\s]*(\d+)\b|\b(\d{1,6})\s*(?:EA|BX|PG|DZ|HD)\b", re.IGNORECASE)


# ── Pure parsing (unit-testable, no network) ─────────────────────────────────
def parse_rfq_line(line: str) -> dict | None:
    """Extract one RFQ from a batch-file line. None if no solicitation found."""
    sol_m = SOL_RE.search(line)
    if not sol_m:
        return None
    solicitation = "-".join(g.upper() for g in sol_m.groups())

    nsn_m = NSN_RE.search(line)
    nsn = "-".join(nsn_m.groups()) if nsn_m else None
    fsc = nsn_m.group(1) if nsn_m else None

    date_m = DATE_RE.search(line[sol_m.end():]) or DATE_RE.search(line)
    deadline = None
    days_left = None
    if date_m:
        try:
            mm, dd, yyyy = (int(g) for g in date_m.groups())
            dt = datetime(yyyy, mm, dd, tzinfo=timezone.utc)
            deadline = dt.strftime("%Y-%m-%d")
            days_left = (dt - datetime.now(timezone.utc)).days
        except ValueError:
            pass

    qty = None
    qty_m = QTY_RE.search(line)
    if qty_m:
        qty = int(next(g for g in qty_m.groups() if g))

    # Description: longest run of letters/spaces that isn't a keyword artifact
    cleaned = SOL_RE.sub(" ", line)
    cleaned = NSN_RE.sub(" ", cleaned)
    cleaned = DATE_RE.sub(" ", cleaned)
    words = re.findall(r"[A-Za-z][A-Za-z ,'/-]{4,}", cleaned)
    description = max(words, key=len).strip(" ,-/") if words else "See DIBBS for item details"

    return {
        "solicitation_number": solicitation,
        "nsn": nsn,
        "fsc_code": fsc,
        "title": description[:100],
        "response_deadline": deadline,
        "days_to_deadline": days_left,
        "quantity": qty,
    }


def parse_rfq_text(text: str, keyword: str = "") -> list[dict]:
    """Parse a whole batch file. Optional keyword filter (case-insensitive)."""
    kw = keyword.lower().strip()
    rfqs = []
    seen: set[str] = set()
    for line in text.splitlines():
        rfq = parse_rfq_line(line)
        if not rfq or rfq["solicitation_number"] in seen:
            continue
        if kw and kw not in line.lower():
            continue
        seen.add(rfq["solicitation_number"])
        rfqs.append(rfq)
    return rfqs


def to_lead(rfq: dict, keyword: str) -> dict:
    """Normalize a parsed RFQ to the pipeline's lead schema."""
    sol = rfq["solicitation_number"]
    sol_compact = sol.replace("-", "")
    return {
        "notice_id": f"DIBBS-{sol_compact}",
        "solicitation_number": sol,
        "title": rfq.get("title") or keyword,
        "agency": "Defense Logistics Agency (DIBBS)",
        "naics_code": "",
        "notice_type": "DIBBS RFQ",
        "setaside_code": "",
        "setaside_label": "Check RFQ on DIBBS",
        "estimated_value_usd": None,
        "posted_date": None,
        "response_deadline": rfq.get("response_deadline"),
        "days_to_deadline": rfq.get("days_to_deadline"),
        "pop_zip": "", "pop_city": "", "pop_state": "",
        "nsn": rfq.get("nsn"),
        "fsc_code": rfq.get("fsc_code"),
        "is_dibbs": True,
        "active": True,
        "description_url": None,
        "solicitation_url": f"{DIBBS_BASE}/Solicitations/Index?Cgv={sol_compact}",
        "priority_score": 65 if rfq.get("nsn") else 50,
        "flags": [
            "EXPERIMENTAL DIBBS feed — verify everything on dibbs.bsm.dla.mil",
            f"Quantity: {rfq['quantity']}" if rfq.get("quantity") else "Quantity: see RFQ",
        ],
    }


# ── Network layer ─────────────────────────────────────────────────────────────
HIDDEN_INPUT_RE = re.compile(
    r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', re.IGNORECASE)
FILE_LINK_RE = re.compile(r'href="([^"]*?(?:in|rfq)[^"]*?\.(?:txt|TXT))"')


def _accept_dod_banner(session: requests.Session) -> bool:
    """The consent page is a standard ASP.NET form — replay its postback."""
    try:
        resp = session.get(f"{DIBBS_BASE}/dodwarning.aspx?goto=%2Fdownloads%2Frfq", timeout=30)
        resp.raise_for_status()
        fields = dict(HIDDEN_INPUT_RE.findall(resp.text))
        # The OK button name varies by version; try known candidates
        for btn in ("butOK", "ctl00$butOK", "btnOk", "ctl00$MainContent$butOK"):
            payload = {**fields, btn: "Ok"}
            r2 = session.post(resp.url, data=payload, timeout=30, allow_redirects=True)
            if r2.ok and "Notice and Consent" not in r2.text[:4000]:
                return True
        return False
    except requests.RequestException as exc:
        logger.warning("DIBBS consent banner failed: %s", exc)
        return False


def search_dibbs_rfqs(
    keywords: str = "",
    naics_code: str | None = None,   # accepted for interface parity; DIBBS has no NAICS
    max_results: int = 25,
    http_session: requests.Session | None = None,
    **_: object,
) -> list[dict]:
    """
    Fetch + parse the newest DIBBS RFQ batch file. Returns normalized leads.
    EXPERIMENTAL: returns [] (with a logged reason) on any failure.
    """
    session = http_session or requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (GovConScout small-business research)"

    if not _accept_dod_banner(session):
        logger.warning("DIBBS: could not pass DoD consent banner — skipping (experimental source).")
        return []

    try:
        idx = session.get(RFQ_INDEX_URL, timeout=30)
        idx.raise_for_status()
        files = FILE_LINK_RE.findall(idx.text)
        if not files:
            logger.warning("DIBBS: no RFQ files found on index page (format change?).")
            return []
        latest = sorted(files)[-1]
        url = latest if latest.startswith("http") else RFQ_INDEX_URL + latest.lstrip("/")
        raw = session.get(url, timeout=60)
        raw.raise_for_status()
        text = raw.text
    except requests.RequestException as exc:
        logger.warning("DIBBS fetch failed: %s", exc)
        return []

    rfqs = parse_rfq_text(text, keyword=keywords)
    leads = [to_lead(r, keywords) for r in rfqs[:max_results]]
    logger.info("DIBBS: parsed %d RFQs matching '%s'", len(leads), keywords)
    return leads
