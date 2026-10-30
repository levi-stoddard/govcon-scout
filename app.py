"""
app.py — GovCon Scout UI v3.0
One search drives everything: live opportunities, market intel, and
competitor analysis all load from a single action. No dead controls,
no fake progress — every element on screen does something real.
"""

from __future__ import annotations
import json
import os
import time
from datetime import datetime
from typing import Any

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import (
    SAM_API_KEY, GOOGLE_CSE_API_KEY, USE_LLM,
    MINIMUM_MARGIN_PCT, MICRO_PURCHASE_THRESHOLD,
)
from crew_runner import GovConScoutCrew
from sourcing_calculator import (
    estimate_shipping, calculate_bid, get_market_data,
    build_supplier_links, FSC_CATEGORIES, WEIGHT_ESTIMATES,
)
from analytics import (
    fetch_historical_awards,
    compute_competitor_stats,
    compute_price_trend,
    compute_regional_stats,
    beat_this_price,
)
import db
from db import STAGES, STAGE_LABELS
from quote_generator import build_quote_sheet
import assistant

db.init_db()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE SETUP + THEME
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="GovCon Scout",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

  html, body, [class*="css"], .stMarkdown, p, li { font-family: 'Inter', sans-serif; }
  h1, h2, h3, h4, h5 { font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -0.3px; }

  .block-container { padding-top: 1.2rem; max-width: 1250px; }

  /* ── Hero ─────────────────────────────────────────────────────────── */
  .hero-wrap { background: linear-gradient(135deg, #0f1a30 0%, #16233f 60%, #1a2947 100%);
               border: 1px solid #2a3a5f; border-radius: 16px;
               padding: 22px 28px 18px; margin-bottom: 14px;
               position: relative; overflow: hidden; }
  .hero-wrap::after { content: "🦅"; position: absolute; right: 18px; top: 50%;
               transform: translateY(-50%); font-size: 5.5rem; opacity: 0.08; }
  .hero-title { font-family: 'Space Grotesk', sans-serif; font-size: 2.1rem; font-weight: 700;
                letter-spacing: -0.5px; margin-bottom: 0;
                background: linear-gradient(90deg, #e8b93b, #f7e19b);
                -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .hero-sub   { color: #93a0b8; margin-top: 4px; margin-bottom: 0; font-size: 0.95rem; }

  /* ── Tabs → pill navigation ───────────────────────────────────────── */
  .stTabs [data-baseweb="tab-list"] { gap: 6px; background: #101a2e;
                border: 1px solid #24304d; border-radius: 12px; padding: 6px; }
  .stTabs [data-baseweb="tab"] { border-radius: 8px; padding: 8px 16px;
                font-family: 'Space Grotesk', sans-serif; font-weight: 600;
                background: transparent; color: #93a0b8; }
  .stTabs [aria-selected="true"] { background: linear-gradient(135deg, #e8b93b, #d4a017) !important;
                color: #0b1220 !important; }
  .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }

  /* ── Buttons ──────────────────────────────────────────────────────── */
  .stButton button, .stDownloadButton button, .stLinkButton a {
                border-radius: 9px; font-weight: 600;
                transition: transform .08s ease, box-shadow .12s ease; }
  .stButton button:hover, .stDownloadButton button:hover, .stLinkButton a:hover {
                transform: translateY(-1px); box-shadow: 0 4px 14px #00000055; }
  button[kind="primary"], .stLinkButton a[kind="primary"] {
                background: linear-gradient(135deg, #e8b93b, #d4a017) !important;
                color: #0b1220 !important; border: none !important; }

  /* ── Cards, metrics, expanders ───────────────────────────────────── */
  div[data-testid="stMetric"] { background: linear-gradient(180deg, #141e33, #101a2e);
                border: 1px solid #24304d; border-radius: 12px; padding: 12px 16px; }
  div[data-testid="stMetric"] label { color: #93a0b8 !important;
                font-size: 0.72rem !important; text-transform: uppercase; letter-spacing: 0.8px; }
  div[data-testid="stMetricValue"] { font-family: 'Space Grotesk', sans-serif; }
  div[data-testid="stExpander"] { border: 1px solid #24304d; border-radius: 12px;
                background: #101a2e; margin-bottom: 6px; }
  div[data-testid="stExpander"]:hover { border-color: #e8b93b66; }
  div[data-testid="stVerticalBlockBorderWrapper"] > div > div[data-testid="stVerticalBlock"] {
                border-radius: 14px; }

  /* ── Sidebar ──────────────────────────────────────────────────────── */
  section[data-testid="stSidebar"] { background: #0a101f;
                border-right: 1px solid #1c2740; }
  section[data-testid="stSidebar"] .stMarkdown h4 { color: #e8b93b;
                font-size: 0.82rem; text-transform: uppercase; letter-spacing: 1.2px; }

  /* ── Inputs ───────────────────────────────────────────────────────── */
  .stTextInput input, .stNumberInput input, .stTextArea textarea {
                border-radius: 9px !important; border-color: #24304d !important; }
  .stTextInput input:focus, .stTextArea textarea:focus { border-color: #e8b93b !important;
                box-shadow: 0 0 0 1px #e8b93b55 !important; }

  /* ── Badges ───────────────────────────────────────────────────────── */
  .badge      { display: inline-block; padding: 3px 12px; border-radius: 12px;
                font-size: 0.78rem; font-weight: 700; margin-right: 6px;
                font-family: 'Space Grotesk', sans-serif; }
  .badge-go     { background: #123d26; color: #4ade80; border: 1px solid #22c55e55; }
  .badge-verify { background: #3d3012; color: #fbbf24; border: 1px solid #f59e0b55; }
  .badge-nogo   { background: #3d1212; color: #f87171; border: 1px solid #ef444455; }
  .badge-pass   { background: #123d26; color: #4ade80; border: 1px solid #22c55e55; }
  .badge-review { background: #3d3012; color: #fbbf24; border: 1px solid #f59e0b55; }
  .badge-fail   { background: #3d1212; color: #f87171; border: 1px solid #ef444455; }
  .badge-info   { background: #12233d; color: #60a5fa; border: 1px solid #3b82f655; }

  .step-num   { display: inline-flex; width: 26px; height: 26px; border-radius: 50%;
                background: linear-gradient(135deg, #e8b93b, #d4a017); color: #0b1220;
                font-weight: 800; align-items: center; justify-content: center; margin-right: 8px; }

  /* ── Advisor chat ─────────────────────────────────────────────────── */
  .chat-user  { background: #1a2947; border: 1px solid #2a3a5f; border-radius: 14px 14px 4px 14px;
                padding: 10px 16px; margin: 6px 0 6px 15%; }
  .chat-agent { background: #14231c; border: 1px solid #1f5c3855; border-radius: 14px 14px 14px 4px;
                padding: 10px 16px; margin: 6px 15% 6px 0; }
  .chat-agent::before { content: "🦅 Advisor"; display: block; font-size: 0.72rem;
                color: #e8b93b; font-weight: 700; letter-spacing: 0.8px; margin-bottom: 4px; }

  /* ── Scrollbar ────────────────────────────────────────────────────── */
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: #0b1220; }
  ::-webkit-scrollbar-thumb { background: #24304d; border-radius: 5px; }
  ::-webkit-scrollbar-thumb:hover { background: #e8b93b88; }

  #MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".progress.json")

CHECKLIST = [
    ("sam", "Register entity on SAM.gov (free — never pay a 3rd party)", "https://sam.gov"),
    ("cage", "Receive CAGE code (assigned during SAM registration)", "https://cage.dla.mil"),
    ("dibbs", "Create DLA DIBBS vendor account (needs CAGE)", "https://www.dibbs.bsm.dla.mil"),
    ("bank", "Business bank account + PIEE/WAWF registration (to get paid)", "https://piee.eb.mil"),
    ("first", "Submit your first quote", None),
]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS (defined BEFORE use — fixes the v2 NameError crash)
# ══════════════════════════════════════════════════════════════════════════════
def money(val, default="—") -> str:
    if val is None:
        return default
    try:
        return f"${float(val):,.2f}"
    except (TypeError, ValueError):
        return default


def load_progress() -> dict:
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_progress(progress: dict) -> None:
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as fh:
            json.dump(progress, fh)
    except OSError:
        pass


def badge(text: str, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{text}</span>'


def status_badges(lead: dict) -> str:
    parts = []
    gng = str(lead.get("go_no_go") or "")
    if gng == "GO":
        parts.append(badge("GO — margin verified", "go"))
    elif gng == "VERIFY_COST":
        parts.append(badge("VERIFY COST", "verify"))
    elif gng == "BELOW_TARGET":
        parts.append(badge(f"Works at {lead.get('max_achievable_margin_pct', '?')}% (below target)", "verify"))
    elif gng:
        parts.append(badge("NO-GO", "nogo"))
    verdict = str((lead.get("compliance") or {}).get("verdict") or "")
    if verdict:
        parts.append(badge(f"Compliance: {verdict}", verdict.lower() if verdict.lower() in ("pass", "review", "fail") else "info"))
    dtd = lead.get("days_to_deadline")
    if dtd is not None:
        parts.append(badge(f"{dtd} days left", "info"))
    if lead.get("is_dibbs"):
        parts.append(badge("DLA / DIBBS", "info"))
    return " ".join(parts)


def render_lead_card(lead: dict, idx: int) -> None:
    st.markdown(status_badges(lead), unsafe_allow_html=True)

    bid_note = lead.get("bid_note")
    if bid_note:
        st.info(f"💡 {bid_note}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**📋 Solicitation**")
        st.write(f"Agency: {lead.get('agency', 'N/A')}")
        st.write(f"Type: {lead.get('notice_type', 'N/A')}")
        st.write(f"Set-aside: {lead.get('setaside_label', 'None')}")
        st.write(f"Deadline: {str(lead.get('response_deadline') or 'N/A')[:10]}")
        pop = ", ".join(p for p in [lead.get("pop_city"), lead.get("pop_state"), lead.get("pop_zip")] if p)
        if pop:
            st.write(f"Ship to: {pop}")
        if lead.get("solicitation_url"):
            st.link_button("Open on SAM.gov →", lead["solicitation_url"], type="primary",
                           key=f"sam_{idx}_{lead.get('notice_id')}")

    with col2:
        st.markdown("**💰 The Numbers**")
        rows = [
            ("Market floor", money(lead.get("floor_price_usd"))),
            ("Market ceiling", money(lead.get("ceiling_price_usd"))),
            ("Supplier cost", money(lead.get("supplier_unit_cost_usd"))),
            ("Shipping", money(lead.get("shipping_cost_usd"))),
            ("Total COGS", money(lead.get("total_cogs_usd"))),
        ]
        for label, val in rows:
            st.write(f"{label}: {val}")
        bid = lead.get("recommended_max_bid_usd")
        if bid:
            st.markdown(f"#### 🎯 Max bid: **{money(bid)}**")
        margin = lead.get("actual_margin_pct")
        if margin is not None:
            st.write(f"Margin: {margin}%")
        src = lead.get("supplier_cost_source")
        if src:
            st.caption(src)

    with col3:
        st.markdown("**🔗 Next Steps**")
        if str(lead.get("go_no_go")) == "VERIFY_COST":
            st.caption("1. Find the real price on a supplier site below")
            st.caption("2. Plug it into the Bid Calculator tab")
            st.caption("3. Bid only if margin holds")
        else:
            st.caption("Verify price + read full solicitation before bidding:")
        for link in (lead.get("supplier_links") or [])[:4]:
            url = link.get("url") or link.get("search_url") or "#"
            st.link_button(link.get("supplier", "Supplier"), url,
                           key=f"sup_{idx}_{lead.get('notice_id')}_{link.get('supplier')}")

    warnings = (lead.get("compliance") or {}).get("warning_flags") or []
    fatals = (lead.get("compliance") or {}).get("fatal_flags") or []
    if fatals or warnings:
        with st.expander(f"🛡️ Compliance details ({len(fatals)} fatal, {len(warnings)} warnings)"):
            for f in fatals:
                st.error(f)
            for w in warnings:
                st.warning(w)

    # ── Track / Quote actions (Tier 1 + 4) ────────────────────────────────────
    nid = lead.get("notice_id") or ""
    a1, a2, a3 = st.columns([1, 1, 2])
    with a1:
        if db.is_tracked(nid):
            st.success("📌 In your pipeline")
        elif st.button("📌 Track this lead", key=f"track_{idx}_{nid}", type="primary"):
            db.upsert_lead(lead, st.session_state.last_search)
            db.set_stage(nid, "tracking")
            db.log_event("tracked", f"Tracking: {lead.get('title', '')[:60]}", nid)
            st.rerun()
    with a2:
        st.download_button(
            "📄 Quote sheet",
            data=build_quote_sheet(lead),
            file_name=f"quote_{nid[:20]}.txt",
            mime="text/plain",
            key=f"quote_{idx}_{nid}",
        )


def run_search(keyword: str, naics: str, lookback: int, max_leads: int,
               include_dibbs: bool = False) -> None:
    """One search → pipeline + market data, all cached in session state."""
    with st.status(f"Searching for '{keyword}'…", expanded=True) as box:
        st.write("🔎 Live SAM.gov solicitations + historical pricing + compliance gate"
                 + (" + DIBBS feed (experimental)" if include_dibbs else ""))
        st.caption("Results are cached for today — re-running the same search is instant and free.")
        t0 = time.time()
        try:
            report = GovConScoutCrew().run(keyword=keyword, naics_code=naics or None,
                                           include_dibbs=include_dibbs, max_leads=max_leads,
                                           target_margin_pct=target_margin_ui / 100,
                                           hard_floor_pct=hard_floor_ui / 100)
        except Exception as exc:
            box.update(label="Search failed", state="error")
            st.error(f"Pipeline error: {exc}")
            st.stop()

        st.write("📊 Loading market intelligence from USASpending…")
        try:
            market_df = fetch_historical_awards(keyword, naics or None, lookback, 200)
        except Exception:
            market_df = pd.DataFrame()

        n = report.get("pipeline_summary", {}).get("total_leads_evaluated", 0)
        box.update(label=f"Done in {time.time()-t0:.0f}s — {n} live leads found", state="complete")

    st.session_state.report = report
    st.session_state.market_df = market_df
    st.session_state.last_search = keyword
    st.session_state.last_naics = naics


def trigger_example(kw: str) -> None:
    st.session_state.kw_input = kw
    st.session_state.pending_search = True


def render_advisor(context: str = "main") -> None:
    """Conversational agent: finds contracts, scans niches, reads your pipeline."""
    from config import GOOGLE_API_KEY as _GK
    if not _GK:
        st.warning("The Advisor needs a (free) Gemini key: add `GOOGLE_API_KEY` to your `.env` "
                   "— get one at [aistudio.google.com](https://aistudio.google.com) — then relaunch.")
        return

    for msg in st.session_state.chat_display:
        css = "chat-user" if msg["role"] == "user" else "chat-agent"
        st.markdown(f'<div class="{css}">{msg["text"]}</div>', unsafe_allow_html=True)

    if not st.session_state.chat_display:
        st.caption("Try: *“What niche should I go after?”* · *“Find me nitrile glove contracts”* · "
                   "*“What's the market for traffic signs?”* · *“How's my pipeline doing?”*")
        q1, q2, q3 = st.columns(3)
        prompts = ["What niche should I go after?",
                   "Find me nitrile glove contracts",
                   "How's my pipeline doing?"]
        for col, p in zip((q1, q2, q3), prompts):
            with col:
                if st.button(p, key=f"qp_{context}_{p[:12]}", use_container_width=True):
                    st.session_state.advisor_pending = p
                    st.rerun()

    with st.form(key=f"advisor_form_{context}", clear_on_submit=True):
        fc1, fc2 = st.columns([6, 1])
        with fc1:
            user_msg = st.text_input("Ask the Advisor", placeholder="Ask me to find contracts, rank niches, or explain a verdict…",
                                     label_visibility="collapsed")
        with fc2:
            sent = st.form_submit_button("Send", type="primary", use_container_width=True)

    pending = st.session_state.pop("advisor_pending", None)
    if pending or (sent and user_msg.strip()):
        message = pending or user_msg.strip()
        st.session_state.chat_display.append({"role": "user", "text": message})
        with st.spinner("Advisor is working — live searches can take 20–60s…"):
            reply, new_history, fx = assistant.chat(message, st.session_state.chat_history)
        st.session_state.chat_history = new_history
        st.session_state.chat_display.append({"role": "agent", "text": reply})
        if fx.get("report"):
            # The agent ran a live search — light up the whole app with it
            st.session_state.report = fx["report"]
            st.session_state.last_search = fx.get("keyword", "")
            st.session_state.last_naics = ""
            try:
                st.session_state.market_df = fetch_historical_awards(
                    fx.get("keyword", ""), None, 180, 200)
            except Exception:
                st.session_state.market_df = pd.DataFrame()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════
for key, default in (
    ("report", None), ("market_df", None), ("last_search", ""),
    ("last_naics", ""), ("pending_search", False),
    ("chat_history", []), ("chat_display", []),
):
    if key not in st.session_state:
        st.session_state[key] = default


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — settings + system status + registration checklist
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🦅 GovCon Scout")
    st.caption("Federal micro-contract intelligence")

    st.markdown("#### System status")
    st.markdown(
        ("✅" if SAM_API_KEY else "❌") + " SAM.gov API (live leads)  \n"
        + ("✅" if GOOGLE_CSE_API_KEY else "⚠️") + " Supplier pricing (Google CSE)  \n"
        + ("🤖 LLM notes: ON" if USE_LLM else "⚡ Deterministic mode ($0 per search)")
    )
    if not SAM_API_KEY:
        st.error("Add SAM_API_KEY to .env — no live leads without it.")

    st.divider()
    st.markdown("#### Search settings")
    max_leads = st.slider("Max leads", 5, 50, 10,
                          help="More leads = more SAM description fetches = more of your daily API quota.")
    lookback = st.slider("Market intel lookback (days)", 30, 365, 180,
                         help="How far back to pull historical award data for the Market Intel tab.")
    include_dibbs = st.toggle("Include DIBBS feed (experimental)", value=False,
                              help="Also scan DLA DIBBS daily RFQ files — thousands of small DoD buys. Experimental: verify every lead on dibbs.bsm.dla.mil.")

    st.divider()
    st.markdown("#### 💰 Margin controls")
    target_margin_ui = st.slider("🎯 Target margin %", 10, 50, int(MINIMUM_MARGIN_PCT * 100),
                                 help="Moving this instantly reprices every lead — no new API calls. "
                                      "Bids are calculated to hit this margin.")
    hard_floor_ui = st.slider("🛑 Hard floor %", 5, 30, 12,
                              help="Leads that can't reach even this margin are NO-GO, always. "
                                   "Between floor and target = BELOW_TARGET (shown with best achievable %).")
    hard_floor_ui = min(hard_floor_ui, target_margin_ui)
    st.caption(f"Micro threshold: **${MICRO_PURCHASE_THRESHOLD:,.0f}**")

    st.divider()
    st.markdown("#### 🔁 Saved searches")
    saved = db.list_searches()
    if saved:
        st.caption("Scanned automatically every morning (see Getting Started → automation).")
        for s in saved:
            sc1, sc2 = st.columns([4, 1])
            icon = "🤖" if s.get("source") == "hunter" else "🔎"
            with sc1:
                st.button(f"{icon} {s['keyword']}", key=f"run_saved_{s['keyword']}",
                          on_click=trigger_example, args=(s["keyword"],),
                          use_container_width=True,
                          help="Added by the hunter agent" if s.get("source") == "hunter" else None)
            with sc2:
                if st.button("✕", key=f"rm_saved_{s['keyword']}", help="Remove"):
                    db.remove_search(s["keyword"])
                    st.rerun()
    else:
        st.caption("None yet. Run a search, then click '💾 Save this search' to add it to the daily auto-scan.")

    st.divider()
    st.markdown("#### 📝 Registration checklist")
    progress = load_progress()
    done_count = 0
    for key_, label, url in CHECKLIST:
        checked = st.checkbox(label, value=bool(progress.get(key_)), key=f"chk_{key_}")
        if checked != bool(progress.get(key_)):
            progress[key_] = checked
            save_progress(progress)
        if checked:
            done_count += 1
        elif url:
            st.caption(f"↳ [{url.replace('https://', '')}]({url})")
    st.progress(done_count / len(CHECKLIST),
                text=f"{done_count}/{len(CHECKLIST)} complete")
    if done_count < 2:
        st.caption("⚠️ You can research now, but you can't be AWARDED anything until SAM registration is done. Start it today — it takes weeks.")


# ══════════════════════════════════════════════════════════════════════════════
# HERO — one search box drives the whole app
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="hero-wrap">
  <p class="hero-title">GovCon Scout</p>
  <p class="hero-sub">Search live SAM.gov solicitations · price against 3 years of awards · compliance-gated — or just ask the Advisor.</p>
</div>
""", unsafe_allow_html=True)

c_kw, c_naics, c_btn = st.columns([5, 2, 2])
with c_kw:
    keyword = st.text_input("What commodity?", key="kw_input",
                            placeholder="e.g. nitrile gloves, safety boots, hand tools",
                            label_visibility="collapsed")
with c_naics:
    naics_code = st.text_input("NAICS (optional)", key="naics_input",
                               placeholder="NAICS (optional)", max_chars=6,
                               label_visibility="collapsed")
with c_btn:
    search_clicked = st.button("🔎 Find Opportunities", type="primary", use_container_width=True,
                               disabled=not (keyword or "").strip())

if (search_clicked or st.session_state.pending_search) and (keyword or "").strip():
    st.session_state.pending_search = False
    run_search(keyword.strip(), (naics_code or "").strip(), lookback, max_leads, include_dibbs)

report = st.session_state.report
market_df = st.session_state.market_df

# ── Live repricing: slider moved → pure math, instant, zero API calls ─────────
if report is not None:
    _sum = report.get("pipeline_summary", {})
    if (_sum.get("target_margin_pct") != float(target_margin_ui)
            or _sum.get("hard_floor_pct") != float(hard_floor_ui)):
        from pipeline import reprice_report
        report = reprice_report(report, target_margin_ui / 100, hard_floor_ui / 100)
        st.session_state.report = report

# ── First-visit welcome ────────────────────────────────────────────────────────
if report is None:
    st.markdown("")
    w1, w2, w3 = st.columns(3)
    with w1:
        with st.container(border=True):
            st.markdown('<span class="step-num">1</span> **Search a commodity**', unsafe_allow_html=True)
            st.caption("Boring products win: fasteners, gloves, tools, signs. Try an example:")
            st.button("🧤 nitrile gloves", on_click=trigger_example, args=("nitrile gloves",), use_container_width=True)
            st.button("🥾 safety boots", on_click=trigger_example, args=("safety boots",), use_container_width=True)
            st.button("🔧 hand tools", on_click=trigger_example, args=("hand tools",), use_container_width=True)
    with w2:
        with st.container(border=True):
            st.markdown('<span class="step-num">2</span> **Read the verdicts**', unsafe_allow_html=True)
            st.caption(
                "Every lead gets two independent gates: a pricing verdict "
                "(GO / VERIFY COST / NO-GO) and a compliance verdict (PASS / REVIEW / FAIL). "
                "Only GO + PASS is bid-ready. Most leads start as VERIFY or REVIEW — "
                "that's the system being honest, not broken."
            )
    with w3:
        with st.container(border=True):
            st.markdown('<span class="step-num">3</span> **Verify, then bid**', unsafe_allow_html=True)
            st.caption(
                "Click the supplier links to confirm your real cost, read the full "
                "solicitation on SAM.gov, then use the Bid Calculator to lock your number. "
                "You sign every bid — the system preps, you decide."
            )

    st.markdown("---")
    st.markdown("#### 🦅 Or just ask the Advisor")
    render_advisor(context="welcome")
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# RESULTS — tabs all fed by the one search
# ══════════════════════════════════════════════════════════════════════════════
summary = report.get("pipeline_summary", {})
rec_bids = report.get("recommended_bids", [])
review_leads = report.get("requires_review", [])
discarded = report.get("discarded_leads", [])
all_leads = rec_bids + review_leads

hdr1, hdr2 = st.columns([4, 1])
with hdr1:
    st.markdown(f"### Results for “{st.session_state.last_search}”")
with hdr2:
    already_saved = st.session_state.last_search.lower() in {s["keyword"] for s in db.list_searches()}
    if already_saved:
        st.caption("✅ In daily auto-scan")
    elif st.button("💾 Save this search", use_container_width=True,
                   help="Adds to the daily auto-scan — new leads land in What's New + email digest."):
        db.save_search(st.session_state.last_search, st.session_state.last_naics)
        st.rerun()

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Live leads", summary.get("total_leads_evaluated", 0))
m2.metric("✅ Cleared", summary.get("cleared_count", len(rec_bids)))
m3.metric("⚠️ Review", summary.get("review_count", len(review_leads)))
m4.metric("🎯 Bid-ready (GO)", summary.get("bid_ready_count", 0))
m5.metric("🔍 Verify cost", summary.get("verify_cost_count", 0))
m6.metric(f"📉 Below {target_margin_ui}%", summary.get("below_target_count", 0),
          help="Leads that can't hit your target but clear the hard floor — best achievable margin shown on each.")

unseen = db.unseen_count()
tab_advisor, tab_opps, tab_pipe, tab_new, tab_market, tab_calc, tab_guide = st.tabs([
    "🦅 Advisor",
    f"🎯 Opportunities ({len(all_leads)})",
    f"📌 My Pipeline ({db.pipeline_stats()['total_tracked']})",
    f"🔔 What's New{f' ({unseen})' if unseen else ''}",
    "📊 Market Intel",
    "🧮 Bid Calculator",
    "🚀 Getting Started",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB — ADVISOR (conversational agent with real tools)
# ══════════════════════════════════════════════════════════════════════════════
with tab_advisor:
    st.caption("Your GovCon mentor with live tools: it can search contracts, rank niches, "
               "pull market stats, and read your pipeline. Every number comes from real data.")
    render_advisor(context="tab")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OPPORTUNITIES
# ══════════════════════════════════════════════════════════════════════════════
with tab_opps:
    if not all_leads and not discarded:
        st.warning(summary.get("note", "No live opportunities found. Try a broader keyword."))

    if all_leads:
        show_nogo = st.toggle("Show NO-GO leads (below your hard floor)", value=False)
        rank = {"GO": 3, "VERIFY_COST": 2, "BELOW_TARGET": 1}

        def visible(leads):
            return [l for l in leads if show_nogo or l.get("go_no_go") != "NO-GO"]

        disp_rec = visible(rec_bids)
        disp_review = visible(review_leads)
        disp_all = disp_rec + disp_review

        if not disp_all:
            st.warning(f"All {len(all_leads)} leads fall below your {hard_floor_ui}% hard floor "
                       "at current cost estimates. Lower the margin sliders or toggle NO-GO leads on.")

        # Best lead first — the one action to take today
        pool = disp_all or all_leads
        best = max(pool, key=lambda l: (
            rank.get(str(l.get("go_no_go")), 0),
            l.get("priority_score") or 0,
        ))
        st.markdown("#### 🏆 Best lead right now")
        with st.container(border=True):
            st.markdown(f"##### {best.get('title', 'Untitled')}")
            render_lead_card(best, 999)

        st.markdown("---")
        b1, b2, b3 = st.tabs([
            f"✅ Cleared ({len(disp_rec)})",
            f"⚠️ Needs review ({len(disp_review)})",
            f"❌ Discarded ({len(discarded)})",
        ])
        with b1:
            if not disp_rec:
                st.info("Nothing fully cleared yet. Check the review tab — most leads need a human look at the full solicitation (that's normal).")
            for i, lead in enumerate(sorted(disp_rec, key=lambda l: rank.get(str(l.get("go_no_go")), 0), reverse=True)):
                with st.expander(f"{lead.get('title', 'Untitled')} — {lead.get('agency', '')}", expanded=False):
                    render_lead_card(lead, i)
        with b2:
            if not disp_review:
                st.success("No leads waiting on review.")
            st.caption("REVIEW = the compliance gate wants human eyes: unknown country of origin, partial text, or a set-aside clause. Read the full solicitation before bidding.")
            for i, lead in enumerate(sorted(disp_review, key=lambda l: rank.get(str(l.get("go_no_go")), 0), reverse=True)):
                with st.expander(f"{lead.get('title', 'Untitled')} — {lead.get('agency', '')}"):
                    render_lead_card(lead, 100 + i)
        with b3:
            if not discarded:
                st.success("Nothing discarded — no fatal compliance violations found.")
            for lead in discarded:
                with st.expander(f"❌ {lead.get('title', 'Untitled')}"):
                    for f in (lead.get("compliance") or {}).get("fatal_flags", []):
                        st.error(f)
                    st.caption(f"Notice ID: {lead.get('notice_id')}")

        st.markdown("---")
        e1, e2, _ = st.columns([1, 1, 2])
        with e1:
            st.download_button(
                "📥 Full report (JSON)",
                data=json.dumps(report, indent=2, default=str),
                file_name=f"govcon_{st.session_state.last_search.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}.json",
                mime="application/json",
                use_container_width=True,
            )
        with e2:
            if all_leads:
                df_export = pd.DataFrame([{
                    "Title": l.get("title"), "Agency": l.get("agency"),
                    "Deadline": l.get("response_deadline"),
                    "Set-aside": l.get("setaside_label"),
                    "Max Bid": l.get("recommended_max_bid_usd"),
                    "Margin %": l.get("actual_margin_pct"),
                    "Pricing": l.get("go_no_go"),
                    "Compliance": (l.get("compliance") or {}).get("verdict"),
                    "URL": l.get("solicitation_url"),
                } for l in all_leads])
                st.download_button(
                    "📊 Lead sheet (CSV)",
                    data=df_export.to_csv(index=False),
                    file_name=f"leads_{datetime.now():%Y%m%d_%H%M}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

# ══════════════════════════════════════════════════════════════════════════════
# TAB — MY PIPELINE (Tier 1: the business system)
# ══════════════════════════════════════════════════════════════════════════════
with tab_pipe:
    stats = db.pipeline_stats()
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Tracked", stats["total_tracked"])
    p2.metric("🏆 Won", stats["won"])
    p3.metric("❌ Lost", stats["lost"])
    p4.metric("Win rate", f"{stats['win_rate_pct']}%" if stats["win_rate_pct"] is not None else "—")
    p5.metric("Revenue won", money(stats["revenue_won"], "—") if stats["revenue_won"] else "—")

    stage_filter = st.multiselect(
        "Show stages", options=STAGES,
        default=["new", "tracking", "cost_verified", "quoted"],
        format_func=lambda s: STAGE_LABELS.get(s, s),
    )
    tracked = db.get_leads(stages=stage_filter or None)

    if not tracked:
        st.info("Nothing here yet. Track leads from the Opportunities tab, or save a search — "
                "the daily auto-scan drops new finds here as 🆕 New.")
    for lead in tracked:
        data = lead["data"]
        label = STAGE_LABELS.get(lead["stage"], lead["stage"])
        deadline = str(lead.get("deadline") or "no deadline")[:10]
        with st.expander(f"{label} — {lead.get('title') or 'Untitled'} · due {deadline}"):
            lc1, lc2 = st.columns([2, 1])
            with lc1:
                st.caption(f"{lead.get('agency', '')} · found via '{lead.get('keyword', '')}' "
                           f"· max bid {money(data.get('recommended_max_bid_usd'))}")
                if data.get("solicitation_url"):
                    st.link_button("Open solicitation →", data["solicitation_url"],
                                   key=f"pipe_url_{lead['notice_id']}")
                notes = st.text_area("Notes", value=lead.get("notes") or "",
                                     key=f"notes_{lead['notice_id']}", height=80,
                                     placeholder="Supplier contacted? Real cost? Anything you'd forget…")
                if notes != (lead.get("notes") or ""):
                    db.set_notes(lead["notice_id"], notes)
            with lc2:
                new_stage = st.selectbox(
                    "Stage", options=STAGES, index=STAGES.index(lead["stage"]),
                    format_func=lambda s: STAGE_LABELS.get(s, s),
                    key=f"stage_{lead['notice_id']}",
                )
                price_val = None
                if new_stage == "quoted":
                    price_val = st.number_input("Your quoted price ($)", min_value=0.0,
                                                value=float(lead.get("quoted_price") or
                                                            data.get("recommended_max_bid_usd") or 0.0),
                                                key=f"qp_{lead['notice_id']}", format="%.2f")
                if new_stage == "won":
                    price_val = st.number_input("Award amount ($)", min_value=0.0,
                                                value=float(lead.get("outcome_price") or
                                                            lead.get("quoted_price") or 0.0),
                                                key=f"op_{lead['notice_id']}", format="%.2f")
                if new_stage != lead["stage"]:
                    if st.button("Apply", key=f"apply_{lead['notice_id']}", type="primary"):
                        db.set_stage(lead["notice_id"], new_stage,
                                     quoted_price=price_val if new_stage == "quoted" else None,
                                     outcome_price=price_val if new_stage == "won" else None)
                        db.log_event("stage", f"{lead.get('title', '')[:50]} → {STAGE_LABELS.get(new_stage)}",
                                     lead["notice_id"])
                        st.rerun()
                st.download_button("📄 Quote sheet", data=build_quote_sheet(lead, lead.get("quoted_price")),
                                   file_name=f"quote_{lead['notice_id'][:20]}.txt", mime="text/plain",
                                   key=f"pipe_quote_{lead['notice_id']}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB — WHAT'S NEW (Tier 2: feed from the daily auto-scan)
# ══════════════════════════════════════════════════════════════════════════════
with tab_new:
    ev_col1, ev_col2, ev_col3 = st.columns([3, 1, 1])
    with ev_col1:
        st.caption("The hunter's feed: new leads, auto-added niches, prepped quotes, deadline alerts. "
                   "Runs daily at 7 AM (Setup Daily Scan.bat) — or on demand →")
    with ev_col2:
        if st.button("🏹 Run hunter now", type="primary", use_container_width=True):
            from scan_daily import scan_all
            with st.spinner("Hunter running: discovering niches, scanning searches, "
                            "qualifying leads… (1–5 min)"):
                try:
                    result = scan_all(send_email=False)
                    st.success(f"Done: {result['new_leads']} new leads, {result['prepped']} prepped, "
                               f"{result['new_niches']} niches added.")
                except Exception as exc:
                    st.error(f"Hunter failed: {exc}")
            st.rerun()
    with ev_col3:
        if unseen and st.button("Mark all read", use_container_width=True):
            db.mark_events_seen()
            st.rerun()

    events = db.get_events(limit=50)
    if not events:
        st.info("No activity yet. Save a search (💾 button above) and run **Setup Daily Scan.bat** "
                "once — every morning at 7 AM new leads and deadline alerts will appear here"
                + (" and in your email." if True else "."))
    icons = {"new_lead": "🆕", "deadline": "⏰", "scan": "🔄", "tracked": "📌",
             "stage": "🔀", "error": "⚠️", "niche": "🎯", "prepped": "🤖"}
    for ev in events:
        marker = "" if ev["seen"] else " :orange[●]"
        st.markdown(f"{icons.get(ev['type'], 'ℹ️')} {ev['message']}  \n"
                    f":gray[{str(ev['ts'])[:16].replace('T', ' ')}]{marker}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MARKET INTEL (loads automatically with the search)
# ══════════════════════════════════════════════════════════════════════════════
with tab_market:
    df = market_df if market_df is not None else pd.DataFrame()
    if df.empty:
        st.info("No historical award data found for this keyword. Try a broader term or longer lookback (sidebar).")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Awards found", len(df))
        c2.metric("Total gov spend", f"${df['amount'].sum():,.0f}")
        c3.metric("Average award", f"${df['amount'].mean():,.0f}")
        c4.metric("Lowest", f"${df['amount'].min():,.0f}")
        c5.metric("Highest", f"${df['amount'].max():,.0f}")

        micro = df[df["amount"] <= MICRO_PURCHASE_THRESHOLD]
        st.caption(f"🎯 **{len(micro)} of {len(df)} awards are micro-purchases (≤${MICRO_PURCHASE_THRESHOLD:,.0f})** — your hunting ground.")
        st.markdown("---")

        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("#### 📉 Price trend")
            trend = compute_price_trend(df)
            if not trend.empty and len(trend) > 1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=trend["month"], y=trend["avg_price"],
                                         mode="lines+markers", name="Avg",
                                         line=dict(color="#e8b93b", width=3)))
                fig.add_trace(go.Scatter(x=trend["month"], y=trend["max_price"], mode="lines",
                                         name="Max", line=dict(color="#ef4444", width=1, dash="dash")))
                fig.add_trace(go.Scatter(x=trend["month"], y=trend["min_price"], mode="lines",
                                         name="Min", line=dict(color="#22c55e", width=1, dash="dash"),
                                         fill="tonexty", fillcolor="rgba(232,185,59,0.05)"))
                fig.update_layout(height=330, margin=dict(t=10, b=10, l=10, r=10),
                                  legend=dict(orientation="h", y=-0.25), hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Not enough data for a trend line — extend the lookback in the sidebar.")

        with col_r:
            st.markdown("#### 🎯 Where awards cluster")
            fig_h = px.histogram(df, x="amount", nbins=30, color_discrete_sequence=["#e8b93b"])
            fig_h.add_vline(x=df["amount"].mean(), line_dash="dash", line_color="#60a5fa",
                            annotation_text=f"Avg {money(df['amount'].mean())}")
            fig_h.update_layout(height=330, margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
                                xaxis_title="Award amount ($)", yaxis_title="Count")
            st.plotly_chart(fig_h, use_container_width=True)

        col_l2, col_r2 = st.columns(2)
        with col_l2:
            st.markdown("#### 🗺️ Top states by spend")
            regional = compute_regional_stats(df)
            if not regional.empty:
                top_states = regional[regional["state"] != "Unknown"].head(12)
                fig_r = px.bar(top_states, x="state", y="total_spend", color="avg_price",
                               color_continuous_scale="YlOrBr", text="num_awards")
                fig_r.update_traces(texttemplate="%{text}", textposition="outside")
                fig_r.update_layout(height=330, margin=dict(t=10, b=10, l=10, r=10),
                                    coloraxis_showscale=False,
                                    xaxis_title="", yaxis_title="Total spend ($)")
                st.plotly_chart(fig_r, use_container_width=True)

        with col_r2:
            st.markdown("#### 🥊 Who's winning (competitors)")
            stats = compute_competitor_stats(df)
            if not stats.empty:
                top10 = stats.head(10)
                fig_c = px.bar(top10.sort_values("total_wins"), x="total_wins", y="recipient",
                               orientation="h", color_discrete_sequence=["#e8b93b"],
                               labels={"total_wins": "Wins", "recipient": ""})
                fig_c.update_layout(height=330, margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig_c, use_container_width=True)
                few = len(stats)
                if few <= 5:
                    st.success(f"Only **{few} companies** won awards here recently — soft competition.")

        # ── Beat-this-price ────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🧮 Beat their price")
        stats = compute_competitor_stats(df)
        bc1, bc2 = st.columns(2)
        with bc1:
            default_price = float(stats.iloc[0]["avg_price"]) if not stats.empty else 1000.0
            comp_price = st.number_input("Competitor's winning price ($)", min_value=0.01,
                                         value=default_price, step=10.0, format="%.2f")
            your_cogs = st.number_input("Your product cost ($)", min_value=0.01,
                                        value=round(default_price * 0.55, 2), step=5.0, format="%.2f")
            ship_cost = st.number_input("Shipping ($)", min_value=0.0, value=14.0, step=1.0, format="%.2f")
            if st.button("Calculate undercut", type="primary"):
                st.session_state.btp = beat_this_price(
                    competitor_price=comp_price, your_cogs=your_cogs,
                    shipping_cost=ship_cost, minimum_margin_pct=MINIMUM_MARGIN_PCT,
                )
        with bc2:
            btp = st.session_state.get("btp")
            if btp:
                (st.success if btp["can_profitably_undercut"] else st.error)(btp["verdict"])
                st.metric("Target bid (5% undercut)", money(btp["target_undercut_bid"]))
                st.metric("Margin at target", f"{btp['margin_at_target_pct']}%")
                st.metric("Your absolute floor", money(btp["minimum_viable_bid"]))
            else:
                st.info("Enter a competitor price and your costs, then calculate.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — BID CALCULATOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_calc:
    st.caption("Found your real supplier price? Lock in your final bid number here.")
    sc1, sc2 = st.columns(2)
    with sc1:
        product_name = st.text_input("Product", value=st.session_state.last_search,
                                     placeholder="e.g. waterproof steel toe safety boot")
        fsc_choice = st.selectbox("Category (FSC)", options=list(FSC_CATEGORIES.keys()))
        quantity = st.number_input("Quantity", min_value=1, value=1, step=1)
        supplier_cost = st.number_input("Your verified supplier cost ($/unit)", min_value=0.01,
                                        value=50.00, step=1.0, format="%.2f")
        dest_state = st.text_input("Destination state", value="VA", max_chars=2).upper()
        weight_lbs = st.number_input("Weight (lbs/unit)", min_value=0.1,
                                     value=WEIGHT_ESTIMATES.get(fsc_choice, 2.0), step=0.5, format="%.1f")
        target_margin = st.slider("Target margin %", 10, 50, int(MINIMUM_MARGIN_PCT * 100))
        fetch_market = st.checkbox("Check against live market ceiling", value=True)
        calc_btn = st.button("🧮 Calculate my bid", type="primary", use_container_width=True)

    with sc2:
        if calc_btn and product_name:
            shipping = estimate_shipping(weight_lbs * quantity, dest_state)
            market_ceiling, market_info = None, {}
            if fetch_market:
                with st.spinner("Fetching market data…"):
                    market_info = get_market_data(product_name)
                    market_ceiling = market_info.get("market_ceiling") if market_info else None

            result = calculate_bid(supplier_cost=supplier_cost, quantity=quantity,
                                   shipping_cost=shipping["estimated_shipping_usd"],
                                   target_margin_pct=target_margin, market_ceiling=market_ceiling)

            (st.success if result["go_no_go"] else st.error)(result["verdict"])
            r1, r2 = st.columns(2)
            r1.metric("Your bid", money(result["recommended_bid"]))
            r2.metric("Per unit", money(result["price_per_unit"]))
            r3, r4 = st.columns(2)
            r3.metric("Gross profit", money(result["gross_profit"]))
            r4.metric("Margin", f"{result['actual_margin_pct']}%",
                      delta=f"{result['actual_margin_pct'] - target_margin:.1f}% vs target")

            st.dataframe(pd.DataFrame({
                "Item": ["Product cost", "Shipping", "Total COGS", "Bid", "Profit"],
                "Amount": [money(result["total_product_cost"]), money(result["shipping_cost"]),
                           money(result["total_cogs"]), money(result["recommended_bid"]),
                           money(result["gross_profit"])],
            }), use_container_width=True, hide_index=True)

            if market_info:
                st.caption(f"Market: avg {money(market_info['market_avg'])} · "
                           f"low {money(market_info['market_min'])} · "
                           f"high {money(market_info['market_max'])} "
                           f"({market_info['sample_size']} recent awards)")
                if result["recommended_bid"] <= market_info["market_avg"]:
                    st.success("Your bid is BELOW market average — competitive position.")
                else:
                    st.warning("Your bid is ABOVE market average — you may not win.")

            st.markdown("**Double-check your cost:**")
            for link in build_supplier_links(product_name)[:4]:
                st.markdown(f"- [{link['supplier']}]({link['search_url']})")
        else:
            st.info("Enter your verified supplier cost on the left, then calculate. "
                    "The calculator enforces your margin floor and caps at the market ceiling.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — GETTING STARTED (registrations + DIBBS guide)
# ══════════════════════════════════════════════════════════════════════════════
with tab_guide:
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("#### 🚦 Your path to the first contract")
        st.markdown("""
1. **SAM.gov entity registration** — free at [sam.gov](https://sam.gov). Takes 2–4+ weeks of government processing. **This is the bottleneck — start today.** Never pay a third-party "registration service."
2. **CAGE code** — assigned automatically during SAM registration.
3. **DIBBS vendor account** — free at [dibbs.bsm.dla.mil](https://www.dibbs.bsm.dla.mil) once you have a CAGE. This is where the small DoD commodity buys live.
4. **PIEE / WAWF** — [piee.eb.mil](https://piee.eb.mil), required to invoice and get paid.
5. **Small-business self-certification** happens inside SAM. Other set-asides (WOSB, 8(a), HUBZone, SDVOSB) need separate SBA certification — only pursue ones you're eligible for.

Track your progress with the checklist in the sidebar.
        """)
        st.warning("**52.219-14 heads-up:** on set-aside supply contracts you must be the manufacturer "
                   "or a *regular dealer* — pure dropshipping can violate the nonmanufacturer rule. "
                   "The compliance gate flags this clause on every lead that carries it.")
    with g2:
        st.markdown("#### 🪖 DLA DIBBS in 60 seconds")
        st.markdown("""
DIBBS is DLA's own bidding portal — thousands of small NSN-based RFQs, many under $10K,
often awarded automatically to the lowest compliant bidder. **Solicitation numbers starting
with `SPE` in your search results are DIBBS buys.**

1. Browse without an account: [dibbs.bsm.dla.mil](https://www.dibbs.bsm.dla.mil) → Solicitations
2. Search by NSN or description
3. Register with your CAGE code to submit quotes

**Good hunting FSCs:** 5305/5310 (fasteners), 5120 (hand tools), 4240 (safety gear), 9905 (signs), 7920 (cleaning).
**Avoid early on:** 6505 (regulated medical), anything with QPL or first-article testing.
        """)
        st.link_button("Open DLA DIBBS →", "https://www.dibbs.bsm.dla.mil", type="primary")
        st.link_button("Start SAM registration →", "https://sam.gov")

    st.markdown("---")
    st.markdown("#### 🤖 Automation: let it hunt while you sleep")
    a1, a2 = st.columns(2)
    with a1:
        st.markdown("""
**Daily auto-scan (one-time setup):**
1. Run a search, click **💾 Save this search** (repeat for every keyword you care about)
2. Double-click **Setup Daily Scan.bat** in the GovConScout folder — done
3. Every morning at 7 AM: saved searches run, new leads land in **🔔 What's New** and **📌 My Pipeline** as 🆕 New, deadline alerts fire for anything you're working
        """)
    with a2:
        st.markdown("""
**Email digest (optional):** add to your `.env`:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=<Gmail App Password>
DIGEST_TO=you@gmail.com
```
Gmail needs an *App Password* (Google Account → Security → 2-Step Verification → App passwords) — your normal password won't work.

**Quote sheets:** fill `COMPANY_NAME`, `COMPANY_CAGE`, etc. in `.env` and every 📄 Quote sheet comes pre-filled.
        """)
