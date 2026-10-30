"""
assistant.py — The Advisor: a conversational agent inside the app.

Talks to the user in plain English and calls REAL tools to answer:
  find_contracts   → runs the live pipeline (SAM.gov + pricing + compliance)
  discover_niches  → scans candidate commodities, ranks by micro-purchase
                     density, buying volume, and competition softness
  market_stats     → historical spend, winners, price range for a keyword
  pipeline_status  → the user's own tracked bids, win rate, revenue

Design rules:
  * The LLM NEVER invents numbers — every figure comes from a tool result.
  * Tool failures return errors the model must relay honestly.
  * The Gemini transport is injectable, so the whole loop is testable offline.

Uses the Gemini REST API directly (no new dependencies — just requests).
"""

from __future__ import annotations
import logging
from typing import Any, Callable

import requests

from config import GOOGLE_API_KEY, MICRO_PURCHASE_THRESHOLD, MINIMUM_MARGIN_PCT

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_PROMPT = f"""You are the GovCon Scout Advisor — a pragmatic federal contracting mentor
for a brand-new small-business reseller hunting micro-purchases (under ${MICRO_PURCHASE_THRESHOLD:,.0f})
and simplified acquisitions. The user is pre-registration (SAM.gov entity registration in progress).

Rules:
- Ground EVERY number in tool results. If you didn't call a tool, don't cite figures.
- When the user asks to find contracts or explore a product, call find_contracts.
- When they ask "what should I sell" / "what niche", call discover_niches, then explain the
  top 2-3 picks: why the micro density, volume, and competition make them good.
- Be direct about verdicts: VERIFY_COST means the cost is estimated — they must check a real
  supplier price before bidding. REVIEW means read the full solicitation. Never soften a FAIL.
- Enforce discipline: minimum margin {MINIMUM_MARGIN_PCT:.0%}, no bid without verified cost,
  no assumption of US origin.
- Keep answers short and actionable. Bullet the leads, end with ONE next step.
- You cannot submit bids. The user reviews and signs everything.
"""

DEFAULT_NICHE_CANDIDATES = [
    "nitrile gloves", "safety glasses", "hand tools", "stainless fasteners",
    "cleaning supplies", "copy paper", "traffic signs", "safety boots",
    "first aid kits", "trash bags",
]

FUNCTION_DECLARATIONS = [
    {
        "name": "find_contracts",
        "description": "Search LIVE federal solicitations for a commodity, price them against "
                       "historical awards, and run the compliance gate. Returns top leads.",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Commodity, e.g. 'nitrile gloves'"},
                "naics_code": {"type": "string", "description": "Optional 6-digit NAICS filter"},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "discover_niches",
        "description": "Scan candidate commodity niches and rank them by micro-purchase density, "
                       "federal buying volume, and competition softness. Use when the user asks "
                       "what to sell or which niche to pursue.",
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Optional custom candidate list; omit to use the default 10",
                },
            },
        },
    },
    {
        "name": "market_stats",
        "description": "Historical federal market for a keyword: spend, award count, price range, "
                       "micro-purchase share, top winning companies.",
        "parameters": {
            "type": "object",
            "properties": {"keyword": {"type": "string"}},
            "required": ["keyword"],
        },
    },
    {
        "name": "pipeline_status",
        "description": "The user's own tracked bid pipeline: leads per stage, win rate, revenue won.",
        "parameters": {"type": "object", "properties": {}},
    },
]


# ── Tool implementations (return: result_for_model, side_effects_for_app) ────
def _tool_find_contracts(keyword: str, naics_code: str | None = None) -> tuple[dict, dict]:
    from pipeline import run_pipeline
    report = run_pipeline(keyword, naics_code or None, max_leads=8)
    leads = report.get("recommended_bids", []) + report.get("requires_review", [])
    compact = [{
        "title": l.get("title"),
        "agency": l.get("agency"),
        "deadline": str(l.get("response_deadline") or "")[:10],
        "set_aside": l.get("setaside_label"),
        "pricing_verdict": l.get("go_no_go"),
        "compliance_verdict": (l.get("compliance") or {}).get("verdict"),
        "recommended_max_bid_usd": l.get("recommended_max_bid_usd"),
        "margin_pct": l.get("actual_margin_pct"),
        "url": l.get("solicitation_url"),
    } for l in leads[:8]]
    return (
        {"summary": report.get("pipeline_summary", {}), "top_leads": compact},
        {"report": report, "keyword": keyword},
    )


def _tool_market_stats(keyword: str) -> tuple[dict, dict]:
    from analytics import fetch_historical_awards, compute_competitor_stats
    df = fetch_historical_awards(keyword, None, 365, 200)
    if df.empty:
        return {"error": f"No federal awards found for '{keyword}' in the last year."}, {}
    stats = compute_competitor_stats(df)
    micro = df[df["amount"] <= MICRO_PURCHASE_THRESHOLD]
    return ({
        "keyword": keyword,
        "awards_last_year": int(len(df)),
        "total_spend_usd": round(float(df["amount"].sum()), 2),
        "avg_award_usd": round(float(df["amount"].mean()), 2),
        "min_award_usd": round(float(df["amount"].min()), 2),
        "max_award_usd": round(float(df["amount"].max()), 2),
        "micro_purchase_awards": int(len(micro)),
        "micro_share_pct": round(len(micro) / len(df) * 100, 1),
        "unique_winners": int(stats["recipient"].nunique()) if not stats.empty else 0,
        "top_winners": stats.head(5)[["recipient", "total_wins"]].to_dict("records") if not stats.empty else [],
    }, {})


def _tool_discover_niches(keywords: list[str] | None = None) -> tuple[dict, dict]:
    from analytics import fetch_historical_awards
    candidates = [k for k in (keywords or DEFAULT_NICHE_CANDIDATES) if str(k).strip()][:12]
    results = []
    for kw in candidates:
        try:
            df = fetch_historical_awards(kw, None, 365, 150)
        except Exception as exc:  # a single bad keyword must not sink the scan
            logger.warning("niche scan '%s' failed: %s", kw, exc)
            continue
        if df.empty:
            results.append({"keyword": kw, "awards": 0, "note": "no federal buying found"})
            continue
        micro = df[df["amount"] <= MICRO_PURCHASE_THRESHOLD]
        winners = df["recipient"].nunique()
        micro_share = len(micro) / len(df)
        # Score: lots of micro buys, decent volume, few incumbent winners
        score = round(len(micro) * micro_share * (10 / max(winners, 1)), 1)
        results.append({
            "keyword": kw,
            "awards": int(len(df)),
            "micro_awards": int(len(micro)),
            "micro_share_pct": round(micro_share * 100, 1),
            "unique_winners": int(winners),
            "avg_award_usd": round(float(df["amount"].mean()), 2),
            "niche_score": score,
        })
    ranked = sorted(results, key=lambda r: r.get("niche_score", 0), reverse=True)
    return ({
        "how_to_read": "niche_score = micro-buy volume x micro density x competition softness. "
                       "Higher = better for a new micro-purchase reseller.",
        "ranked_niches": ranked,
    }, {})


def _tool_pipeline_status() -> tuple[dict, dict]:
    import db
    db.init_db()
    return db.pipeline_stats(), {}


TOOLS: dict[str, Callable[..., tuple[dict, dict]]] = {
    "find_contracts": _tool_find_contracts,
    "market_stats": _tool_market_stats,
    "discover_niches": _tool_discover_niches,
    "pipeline_status": _tool_pipeline_status,
}


# ── Chat loop ─────────────────────────────────────────────────────────────────
def _default_transport(payload: dict, api_key: str, model: str) -> dict:
    resp = requests.post(
        GEMINI_URL.format(model=model),
        params={"key": api_key},
        json=payload,
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def chat(
    user_message: str,
    history: list[dict] | None = None,
    api_key: str | None = None,
    model: str = GEMINI_MODEL,
    transport: Callable[[dict, str, str], dict] | None = None,
    max_rounds: int = 6,
) -> tuple[str, list[dict], dict]:
    """
    One conversational turn. Returns (reply_text, new_history, side_effects).
    side_effects may contain {"report": ..., "keyword": ...} when the agent
    ran a live contract search — the app uses it to refresh its tabs.
    """
    api_key = api_key or GOOGLE_API_KEY
    if not api_key:
        return ("The Advisor needs a Gemini key. Add GOOGLE_API_KEY to your .env "
                "(free at aistudio.google.com) and restart the app.", history or [], {})

    send = transport or _default_transport
    contents = list(history or []) + [{"role": "user", "parts": [{"text": user_message}]}]
    side_effects: dict = {}

    for _ in range(max_rounds):
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "tools": [{"function_declarations": FUNCTION_DECLARATIONS}],
            "generationConfig": {"temperature": 0.3},
        }
        try:
            data = send(payload, api_key, model)
        except requests.RequestException as exc:
            logger.error("Gemini API error: %s", exc)
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 403:
                msg = ("**Your GOOGLE_API_KEY isn't a Gemini key** (403 Forbidden — the "
                       "Generative Language API is disabled for it, or it was made for a "
                       "different Google service).\n\n"
                       "Fix: go to **aistudio.google.com/app/apikey** → *Create API key* (free) → "
                       "paste it as `GOOGLE_API_KEY` in your `.env` → relaunch the app.")
            elif status == 400:
                msg = ("**Your GOOGLE_API_KEY looks invalid** (400). Create a fresh one at "
                       "**aistudio.google.com/app/apikey** and update `.env`.")
            elif status == 429:
                msg = ("**Gemini rate limit hit** (429). The free tier allows limited requests "
                       "per minute — wait a moment and try again.")
            else:
                msg = (f"I couldn't reach the Gemini API ({exc}). Check your internet "
                       "connection and GOOGLE_API_KEY, then try again.")
            return msg, contents[:-1], {}

        try:
            content = data["candidates"][0]["content"]
        except (KeyError, IndexError):
            block = (data.get("promptFeedback") or {}).get("blockReason", "unknown response")
            return (f"The model returned nothing usable ({block}). Try rephrasing.", contents[:-1], {})

        parts = content.get("parts", [])
        calls = [p["functionCall"] for p in parts if "functionCall" in p]

        if not calls:
            text = " ".join(p.get("text", "") for p in parts).strip() or "…"
            contents.append(content)
            return text, contents[-24:], side_effects

        # Execute every requested tool, feed results back
        contents.append(content)
        response_parts = []
        for call in calls:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            fn = TOOLS.get(name)
            if fn is None:
                result: dict = {"error": f"unknown tool '{name}'"}
            else:
                try:
                    result, fx = fn(**args)
                    side_effects.update(fx)
                except Exception as exc:
                    logger.error("Tool %s failed: %s", name, exc)
                    result = {"error": f"{name} failed: {exc}"}
            response_parts.append(
                {"functionResponse": {"name": name, "response": {"result": result}}}
            )
        contents.append({"role": "user", "parts": response_parts})

    return ("I hit my tool-call limit for one message — ask me to continue.",
            contents[-24:], side_effects)
