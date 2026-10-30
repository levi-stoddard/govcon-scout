"""
crew_runner.py — Pipeline entry point (same interface app.py always used)

The pipeline is now 100% deterministic Python (see pipeline.py):
numbers and verdicts NEVER come from an LLM. When USE_LLM=true in .env,
an LLM pass rewrites the human-readable bid notes on top of the finished
deterministic results — it cannot change prices, margins, or verdicts.
"""

from __future__ import annotations
import json
import logging
from typing import Any

from config import USE_LLM, GOOGLE_API_KEY, MINIMUM_MARGIN_PCT
from pipeline import run_pipeline

logger = logging.getLogger(__name__)


class GovConScoutCrew:
    """Backward-compatible wrapper: app.py calls GovConScoutCrew().run(...)."""

    def run(self, keyword: str, naics_code: str | None = None,
            include_dibbs: bool = False, max_leads: int = 10,
            target_margin_pct: float | None = None,
            hard_floor_pct: float | None = None) -> dict[str, Any]:
        extra = None
        if include_dibbs:
            from tools.dibbs_tool import search_dibbs_rfqs
            extra = [search_dibbs_rfqs]
        report = run_pipeline(keyword, naics_code, max_leads=max_leads,
                              extra_scout_fetchers=extra,
                              target_margin_pct=target_margin_pct,
                              hard_floor_pct=hard_floor_pct)
        if USE_LLM and GOOGLE_API_KEY:
            try:
                report = self._enrich_notes(report, keyword)
            except Exception as exc:  # LLM failures must never break the pipeline
                logger.warning("LLM note enrichment failed (results unaffected): %s", exc)
        return report

    # ── Optional LLM layer: prose only, never numbers ────────────────────────
    @staticmethod
    def _enrich_notes(report: dict[str, Any], keyword: str) -> dict[str, Any]:
        from crewai import Agent, Task, Crew, Process, LLM

        leads = report.get("recommended_bids", []) + report.get("requires_review", [])
        if not leads:
            return report

        brief = [
            {
                "notice_id": l.get("notice_id"),
                "title": l.get("title"),
                "agency": l.get("agency"),
                "recommended_max_bid_usd": l.get("recommended_max_bid_usd"),
                "actual_margin_pct": l.get("actual_margin_pct"),
                "go_no_go": l.get("go_no_go"),
                "days_to_deadline": l.get("days_to_deadline"),
                "compliance_verdict": (l.get("compliance") or {}).get("verdict"),
            }
            for l in leads
        ]

        writer = Agent(
            role="Federal Bid Strategist",
            goal="Write one concise, actionable strategy sentence per lead.",
            backstory=(
                f"You advise a small federal reseller enforcing a {MINIMUM_MARGIN_PCT:.0%} "
                "minimum margin. You NEVER change numbers — you only explain them."
            ),
            llm=LLM(model="gemini/gemini-2.5-flash", api_key=GOOGLE_API_KEY, temperature=0.2),
            max_iter=2,
            allow_delegation=False,
        )
        task = Task(
            description=(
                f"For each lead below (commodity: '{keyword}'), write ONE sentence of bid "
                f"strategy. Return ONLY a JSON object mapping notice_id to sentence.\n\n"
                f"{json.dumps(brief, indent=2)}"
            ),
            expected_output="JSON object: {notice_id: strategy_sentence}",
            agent=writer,
        )
        result = Crew(agents=[writer], tasks=[task], process=Process.sequential).kickoff()
        raw = result.raw if isinstance(result.raw, str) else json.dumps(result.raw)
        if "```" in raw:
            raw = raw.split("```json")[-1].split("```")[0] if "```json" in raw else raw.split("```")[1]
        notes = json.loads(raw.strip())

        for l in leads:
            extra = notes.get(str(l.get("notice_id")))
            if extra and isinstance(extra, str):
                l["bid_note"] = f"{l.get('bid_note', '')} STRATEGY: {extra}".strip()
        return report
