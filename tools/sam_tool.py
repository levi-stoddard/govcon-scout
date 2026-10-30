"""
tools/sam_tool.py — Scout Tool
Searches SAM.gov Get Opportunities API v2 for LIVE solicitations you can
actually bid on (Combined Synopsis, Solicitation, Sources Sought, Presol).

This replaces the old version that queried USASpending.gov — those were
already-awarded contracts, useless as bid leads. USASpending remains the
Analyst's historical-pricing source (see fpds_tool.py).

All logic lives in plain functions so it can be unit-tested without CrewAI
or an LLM. The CrewAI BaseTool wrapper at the bottom is optional.

NOTE ON RATE LIMITS: personal (non-federal) SAM.gov API keys have a low
daily request quota. Results are cached per (keyword, naics, day) so
repeated runs on the same day cost zero extra requests.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from config import (
    SAM_API_KEY, SAM_BASE_URL, SAM_DESC_URL, SAM_PTYPES,
    SAM_DAYS_POSTED_DEFAULT, SAM_SETASIDE_PRIORITY, MY_ELIGIBLE_SETASIDES,
    MICRO_PURCHASE_THRESHOLD, FSC_COMMODITY_MAP, FSC_AVOID,
)

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")

NSN_RE = re.compile(r"\b(\d{4})-?(\d{2})-?(\d{3})-?(\d{4})\b")
# DLA titles often lead with the FSC group/class, e.g. "84--GLOVES,FLYERS'"
TITLE_FSC_RE = re.compile(r"^(\d{2,4})\s*--")

_last_call = 0.0


def _throttle(min_interval: float = 1.5) -> None:
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_call = time.time()


def _cache_path(key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"sam_{digest}.json")


def _cache_get(key: str) -> Any | None:
    path = _cache_path(key)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _cache_put(key: str, value: Any) -> None:
    try:
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump(value, fh)
    except OSError:
        pass


# ── Parsing ───────────────────────────────────────────────────────────────────
def extract_nsn(text: str) -> str | None:
    m = NSN_RE.search(text or "")
    if not m:
        return None
    return "-".join(m.groups())


def extract_fsc(opp: dict) -> str | None:
    """classificationCode is the PSC/FSC; fall back to a title prefix like '84--'."""
    code = str(opp.get("classificationCode") or "").strip()
    if code and code[0].isdigit():
        return code[:4] if len(code) >= 4 else code
    m = TITLE_FSC_RE.match(str(opp.get("title") or ""))
    return m.group(1) if m else None


def days_until(deadline_iso: str | None) -> int | None:
    if not deadline_iso:
        return None
    try:
        raw = deadline_iso.split("T")[0]
        deadline = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (deadline - datetime.now(timezone.utc)).days
    except (ValueError, AttributeError):
        return None


def is_dibbs(opp: dict) -> bool:
    """DLA posts many small commodity buys; solicitation numbers start with SPE."""
    sol = str(opp.get("solicitationNumber") or "")
    contacts = json.dumps(opp.get("pointOfContact") or [])
    return sol.upper().startswith("SPE") or "dibbs" in contacts.lower()


def score_opportunity(opp: dict, now: datetime | None = None) -> tuple[int, list[str]]:
    """Deterministic priority score 0-100 with human-readable flags."""
    score = 40
    flags: list[str] = []

    setaside = str(opp.get("typeOfSetAside") or "").strip()
    if setaside in MY_ELIGIBLE_SETASIDES:
        score += 20
        flags.append(f"Set-aside you're eligible for: {SAM_SETASIDE_PRIORITY.get(setaside, setaside)}")
    elif setaside in SAM_SETASIDE_PRIORITY:
        score -= 10
        flags.append(f"Set-aside NOT in your eligibility list: {SAM_SETASIDE_PRIORITY.get(setaside, setaside)}")
    elif not setaside:
        score += 10
        flags.append("Unrestricted — anyone can bid")

    dtd = days_until(opp.get("responseDeadLine"))
    if dtd is not None:
        if dtd < 0:
            score -= 40
            flags.append("DEADLINE PASSED")
        elif dtd <= 2:
            score -= 15
            flags.append(f"Deadline very tight: {dtd} day(s)")
        elif dtd <= 14:
            score += 10
            flags.append(f"Deadline in {dtd} days — actionable window")
        else:
            score += 5
            flags.append(f"Deadline in {dtd} days")

    fsc = extract_fsc(opp)
    if fsc:
        if fsc in FSC_AVOID:
            score -= 30
            flags.append(f"FSC {fsc} on AVOID list (QPL/hazmat/regulated)")
        elif fsc[:4] in FSC_COMMODITY_MAP or fsc[:2] in {c[:2] for c in FSC_COMMODITY_MAP}:
            score += 10
            flags.append(f"FSC {fsc}: {FSC_COMMODITY_MAP.get(fsc[:4], 'commodity class')}")

    if is_dibbs(opp):
        score += 10
        flags.append("DLA/DIBBS solicitation — micro-buy territory")

    nsn = extract_nsn(str(opp.get("title") or ""))
    if nsn:
        score += 10
        flags.append(f"NSN identified: {nsn} — exact price matching possible")

    if str(opp.get("type") or "") == "Sources Sought":
        flags.append("Sources Sought — respond to shape the set-aside, no bid yet")

    return max(0, min(score, 100)), flags


def normalize_opportunity(opp: dict) -> dict:
    """Map a raw SAM.gov v2 record to the pipeline's lead schema."""
    pop = opp.get("placeOfPerformance") or {}
    pop_state = ""
    st = pop.get("state")
    if isinstance(st, dict):
        pop_state = st.get("code") or ""
    elif isinstance(st, str):
        pop_state = st
    pop_city = ""
    city = pop.get("city")
    if isinstance(city, dict):
        pop_city = city.get("name") or ""
    elif isinstance(city, str):
        pop_city = city

    office = opp.get("officeAddress") or {}
    score, flags = score_opportunity(opp)
    title = str(opp.get("title") or "")

    return {
        "notice_id": opp.get("noticeId"),
        "solicitation_number": opp.get("solicitationNumber"),
        "title": title,
        "agency": str(opp.get("fullParentPathName") or "").split(".")[-1].title() or "Unknown",
        "naics_code": str(opp.get("naicsCode") or ""),
        "notice_type": opp.get("type"),
        "setaside_code": opp.get("typeOfSetAside") or "",
        "setaside_label": opp.get("typeOfSetAsideDescription") or "None (unrestricted)",
        "estimated_value_usd": None,  # SAM rarely publishes value pre-award; FPDS fills this
        "posted_date": opp.get("postedDate"),
        "response_deadline": opp.get("responseDeadLine"),
        "days_to_deadline": days_until(opp.get("responseDeadLine")),
        "pop_zip": str(pop.get("zip") or office.get("zipcode") or "")[:5],
        "pop_city": pop_city or office.get("city") or "",
        "pop_state": pop_state or office.get("state") or "",
        "nsn": extract_nsn(title),
        "fsc_code": extract_fsc(opp),
        "is_dibbs": is_dibbs(opp),
        "active": str(opp.get("active") or "").lower() == "yes",
        "description_url": opp.get("description"),
        "solicitation_url": opp.get("uiLink"),
        "priority_score": score,
        "flags": flags,
    }


# ── API calls ─────────────────────────────────────────────────────────────────
def search_sam_opportunities(
    keywords: str,
    naics_code: str | None = None,
    days_posted: int = SAM_DAYS_POSTED_DEFAULT,
    max_results: int = 25,
    api_key: str | None = None,
    http_get: Callable[..., requests.Response] | None = None,
    use_cache: bool = True,
) -> list[dict]:
    """
    Search LIVE SAM.gov opportunities. Returns normalized, scored, ranked leads.
    `http_get` is injectable for testing (defaults to requests.get).
    """
    api_key = api_key or SAM_API_KEY
    if not api_key:
        logger.error("SAM_API_KEY is not set — cannot search live opportunities.")
        return []

    get = http_get or requests.get
    now = datetime.now(timezone.utc)
    cache_key = f"{keywords}|{naics_code}|{days_posted}|{max_results}|{now:%Y-%m-%d}"
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("SAM cache hit for '%s' (saves your daily API quota)", keywords)
            return cached

    params: dict[str, Any] = {
        "api_key": api_key,
        "title": keywords,
        "postedFrom": (now - timedelta(days=days_posted)).strftime("%m/%d/%Y"),
        "postedTo": now.strftime("%m/%d/%Y"),
        "ptype": ",".join(SAM_PTYPES),
        "limit": min(max_results, 100),
        "offset": 0,
    }
    if naics_code:
        params["ncode"] = naics_code

    _throttle()
    try:
        resp = get(SAM_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        raw = resp.json().get("opportunitiesData", []) or []
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            logger.error("SAM.gov daily API quota EXHAUSTED. Try again tomorrow or request a rate increase.")
        else:
            logger.error("SAM.gov API error: %s", exc)
        return []
    except (ValueError, KeyError) as exc:
        logger.error("SAM.gov response parse error: %s", exc)
        return []

    leads = [normalize_opportunity(o) for o in raw]
    leads = [l for l in leads if l["active"] and (l["days_to_deadline"] is None or l["days_to_deadline"] >= 0)]
    leads.sort(key=lambda x: x["priority_score"], reverse=True)
    leads = leads[:max_results]

    if use_cache:
        _cache_put(cache_key, leads)
    return leads


def fetch_notice_description(
    description_url: str,
    api_key: str | None = None,
    http_get: Callable[..., requests.Response] | None = None,
    use_cache: bool = True,
) -> str:
    """
    Fetch the full notice description text (needed for real FAR clause
    detection). Costs one API request — call sparingly, results are cached.
    """
    api_key = api_key or SAM_API_KEY
    if not description_url or not api_key:
        return ""
    if use_cache:
        cached = _cache_get(f"desc|{description_url}")
        if cached is not None:
            return cached

    get = http_get or requests.get
    _throttle()
    try:
        resp = get(description_url, params={"api_key": api_key}, timeout=30)
        resp.raise_for_status()
        try:
            body = resp.json()
            text = body.get("description", "") if isinstance(body, dict) else str(body)
        except ValueError:
            text = resp.text
    except requests.RequestException as exc:
        logger.warning("Description fetch failed: %s", exc)
        return ""

    # Strip HTML tags for clause parsing
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    if use_cache:
        _cache_put(f"desc|{description_url}", text)
    return text


# ── Optional CrewAI wrapper (only needed when USE_LLM=true) ──────────────────
try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    class SamSearchInput(BaseModel):
        keywords: str = Field(description="Keywords")
        naics_code: str | None = Field(default=None)
        days_posted: int = Field(default=SAM_DAYS_POSTED_DEFAULT)
        max_results: int = Field(default=25)

    class FetchSamOpportunitiesTool(BaseTool):
        name: str = "fetch_sam_opportunities"
        description: str = "Search SAM.gov for LIVE federal contract opportunities. Call ONCE only."
        args_schema: type[BaseModel] = SamSearchInput

        def _run(self, keywords, naics_code=None, days_posted=SAM_DAYS_POSTED_DEFAULT, max_results=25):
            return json.dumps(
                search_sam_opportunities(keywords, naics_code, days_posted, max_results),
                indent=2, default=str,
            )
except ImportError:  # crewai not installed — deterministic pipeline works fine without it
    FetchSamOpportunitiesTool = None  # type: ignore
