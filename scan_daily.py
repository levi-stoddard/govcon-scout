"""
scan_daily.py — The Hunter: your autonomous contract-finding agent (Tier 2+).

Every run it:
  1. DISCOVERS — scans candidate niches you're NOT watching; if one scores
     high (dense micro-buys, soft competition), it adds the search itself
     and tells you why (max 2 new niches per run, marked 🤖).
  2. SCANS — runs the full pipeline on every saved search (yours + its own).
  3. QUALIFIES — leads that clear your margin target and aren't compliance
     FAILs get auto-tracked into your pipeline with a note.
  4. PREPS — writes a ready-to-review quote sheet for each qualified lead
     into the quotes/ folder.
  5. REPORTS — everything lands in the What's New feed + optional email.

The hunter PREPARES — it never submits a bid. You review and sign everything.

Run manually:   python scan_daily.py            (or "Run Daily Scan.bat")
Skip email:     python scan_daily.py --no-email
Schedule:       double-click "Setup Daily Scan.bat" once (7 AM daily)

Tune in .env:   HUNTER_AUTO_TRACK=false   → report-only mode
                HARD_FLOOR_MARGIN_PCT=0.12
"""

from __future__ import annotations
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

import db
from config import (
    MINIMUM_MARGIN_PCT, HARD_FLOOR_MARGIN_PCT, HUNTER_AUTO_TRACK,
    HUNTER_MAX_NEW_NICHES, NICHE_AUTO_ADD_MIN_SCORE, QUOTES_DIR,
)
from pipeline import run_pipeline
from quote_generator import build_quote_sheet

DEADLINE_WARN_DAYS = 3
QUALIFY_STATUSES = {"GO", "VERIFY_COST"}


def qualifies(lead: dict) -> tuple[bool, str]:
    """Hunter auto-track rules. Returns (qualifies, reason)."""
    status = str(lead.get("go_no_go") or "")
    verdict = str((lead.get("compliance") or {}).get("verdict") or "")
    dtd = lead.get("days_to_deadline")
    if verdict == "FAIL":
        return False, "compliance FAIL"
    if status not in QUALIFY_STATUSES:
        return False, f"pricing status {status or 'unknown'}"
    if dtd is not None and dtd < 2:
        return False, f"deadline too tight ({dtd}d)"
    return True, (f"{status} at {lead.get('actual_margin_pct')}% margin, "
                  f"compliance {verdict or 'REVIEW'}, "
                  f"{dtd if dtd is not None else '?'} days to deadline")


def _safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text)[:60]


def discover_niches() -> list[str]:
    """Step 1: find promising niches the user isn't watching. Returns keywords added."""
    from assistant import _tool_discover_niches  # deterministic scan — no LLM call
    watched = {s["keyword"] for s in db.list_searches(active_only=False)}
    result, _ = _tool_discover_niches()
    added = []
    for niche in result.get("ranked_niches", []):
        if len(added) >= HUNTER_MAX_NEW_NICHES:
            break
        kw = niche.get("keyword", "")
        if not kw or kw.lower() in watched:
            continue
        if niche.get("niche_score", 0) < NICHE_AUTO_ADD_MIN_SCORE or niche.get("awards", 0) < 10:
            continue
        db.save_search(kw, source="hunter")
        added.append(kw)
        db.log_event(
            "niche",
            f"🤖 Hunter added niche '{kw}': {niche['micro_awards']} micro-buys "
            f"({niche['micro_share_pct']}% of {niche['awards']} awards), only "
            f"{niche['unique_winners']} competitors, avg award ${niche['avg_award_usd']:,.0f}. "
            f"Score {niche['niche_score']}. Remove it in the sidebar if you disagree.",
        )
        print(f"  🤖 New niche added: '{kw}' (score {niche['niche_score']})")
    return added


def scan_all(send_email: bool = True) -> dict:
    db.init_db()
    print("=== GovCon Scout Hunter ===")

    # ── Step 1: self-expand ───────────────────────────────────────────────────
    try:
        new_niches = discover_niches()
    except Exception as exc:
        print(f"Niche discovery failed (continuing): {exc}")
        db.log_event("error", f"Niche discovery failed: {exc}")
        new_niches = []

    searches = db.list_searches(active_only=True)
    if not searches:
        print("No saved searches. Open the app, run a search, click 'Save this search'.")
        return {"searches": 0, "new_leads": 0, "prepped": 0, "new_niches": len(new_niches)}

    # ── Step 2 + 3 + 4: scan, qualify, prep ──────────────────────────────────
    new_leads: list[dict] = []
    prepped: list[dict] = []
    os.makedirs(QUOTES_DIR, exist_ok=True)

    for s in searches:
        keyword = s["keyword"]
        print(f"Scanning '{keyword}'...")
        try:
            report = run_pipeline(keyword, s.get("naics") or None, max_leads=15,
                                  target_margin_pct=MINIMUM_MARGIN_PCT,
                                  hard_floor_pct=HARD_FLOOR_MARGIN_PCT)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            db.log_event("error", f"Scan failed for '{keyword}': {exc}")
            continue

        leads = report.get("recommended_bids", []) + report.get("requires_review", [])
        fresh = 0
        for lead in leads:
            if not db.upsert_lead(lead, keyword):
                continue
            fresh += 1
            new_leads.append(lead)
            nid = lead.get("notice_id")
            db.log_event(
                "new_lead",
                f"New lead for '{keyword}': {lead.get('title', '')[:60]} "
                f"({lead.get('go_no_go')}, deadline {str(lead.get('response_deadline'))[:10]})",
                nid,
            )
            ok, reason = qualifies(lead)
            if ok and HUNTER_AUTO_TRACK:
                db.set_stage(nid, "tracking")
                db.set_notes(nid, f"🤖 Auto-qualified by hunter: {reason}")
                quote_path = os.path.join(QUOTES_DIR, f"quote_{_safe_filename(nid)}.txt")
                try:
                    with open(quote_path, "w", encoding="utf-8") as fh:
                        fh.write(build_quote_sheet(lead))
                except OSError as exc:
                    quote_path = f"(quote write failed: {exc})"
                prepped.append(lead)
                db.log_event(
                    "prepped",
                    f"🤖 PREPPED for your review: {lead.get('title', '')[:55]} — {reason}. "
                    f"Quote sheet: {os.path.basename(str(quote_path))}",
                    nid,
                )
        db.touch_search(keyword)
        print(f"  {len(leads)} live leads, {fresh} new, {len(prepped)} prepped so far")

    # ── Deadline alerts on anything you're working ────────────────────────────
    deadline_alerts = []
    for lead in db.get_leads(stages=["tracking", "cost_verified", "quoted"]):
        deadline = str(lead.get("deadline") or "")[:10]
        days_left = lead.get("data", {}).get("days_to_deadline")
        if deadline:
            try:
                days_left = (datetime.fromisoformat(deadline).replace(tzinfo=timezone.utc)
                             - datetime.now(timezone.utc)).days
            except ValueError:
                pass
        if days_left is not None and 0 <= days_left <= DEADLINE_WARN_DAYS:
            deadline_alerts.append(lead)
            db.log_event("deadline",
                         f"⏰ {days_left} day(s) left: {lead.get('title', '')[:60]} "
                         f"(stage: {lead.get('stage')})", lead.get("notice_id"))

    summary = {"searches": len(searches), "new_leads": len(new_leads),
               "prepped": len(prepped), "new_niches": len(new_niches),
               "deadline_alerts": len(deadline_alerts)}
    db.log_event("scan", f"Hunter run done: {summary['searches']} searches, "
                         f"{summary['new_leads']} new leads, {summary['prepped']} prepped, "
                         f"{summary['new_niches']} niches added, "
                         f"{summary['deadline_alerts']} deadline alerts")
    print(f"\nDone. {summary}")

    if send_email and (new_leads or deadline_alerts or new_niches):
        _send_digest(new_leads, deadline_alerts, prepped, new_niches)
    return summary


def _send_digest(new_leads, deadline_alerts, prepped, new_niches) -> None:
    host = os.getenv("SMTP_HOST", "")
    user = os.getenv("SMTP_USER", "")
    pw = os.getenv("SMTP_PASS", "")
    to = os.getenv("DIGEST_TO", user)
    if not (host and user and pw and to):
        print("Email not configured (SMTP_* in .env) — skipping digest. "
              "Everything is in the app's What's New feed.")
        return

    lines = [f"GovCon Scout Hunter — {datetime.now():%Y-%m-%d}", ""]
    if prepped:
        lines.append(f"🤖 PREPPED FOR YOUR REVIEW ({len(prepped)}) — quote sheets in quotes/:")
        for l in prepped[:10]:
            lines.append(f"  • [{l.get('go_no_go')}] {l.get('title', '')[:70]}")
            lines.append(f"    bid {l.get('recommended_max_bid_usd')} | margin "
                         f"{l.get('actual_margin_pct')}% | due {str(l.get('response_deadline'))[:10]}")
        lines.append("")
    if deadline_alerts:
        lines.append(f"⏰ DEADLINES ({len(deadline_alerts)}):")
        for l in deadline_alerts:
            lines.append(f"  • {l.get('title', '')[:70]} — stage {l.get('stage')}, "
                         f"due {str(l.get('deadline'))[:10]}")
        lines.append("")
    if new_niches:
        lines.append(f"🎯 NEW NICHES the hunter is now watching: {', '.join(new_niches)}")
        lines.append("")
    if new_leads:
        lines.append(f"🆕 ALL NEW LEADS ({len(new_leads)}):")
        for l in new_leads[:15]:
            lines.append(f"  • [{l.get('go_no_go')}] {l.get('title', '')[:70]} | {l.get('solicitation_url')}")
    lines += ["", "Open GovCon Scout for details. The hunter preps — you decide."]

    msg = MIMEText("\n".join(lines))
    msg["Subject"] = (f"Hunter: {len(prepped)} prepped, {len(new_leads)} new lead(s), "
                      f"{len(deadline_alerts)} deadline(s)")
    msg["From"] = user
    msg["To"] = to
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as srv:
            srv.starttls()
            srv.login(user, pw)
            srv.send_message(msg)
        print(f"Digest emailed to {to}")
    except Exception as exc:
        print(f"Email failed: {exc}")
        db.log_event("error", f"Email digest failed: {exc}")


if __name__ == "__main__":
    scan_all(send_email="--no-email" not in sys.argv)
