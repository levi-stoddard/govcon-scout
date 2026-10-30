"""
agents.py — LEGACY CrewAI agent definitions.

The pipeline no longer routes numbers through these agents (see pipeline.py —
all math is deterministic Python). Kept for the optional USE_LLM note-writing
layer and future LLM experiments. Margin references config, not magic numbers.
"""
from __future__ import annotations
from crewai import Agent, LLM
from config import GOOGLE_API_KEY, GEMINI_MODEL, CREW_VERBOSE, MINIMUM_MARGIN_PCT
from tools.sam_tool import FetchSamOpportunitiesTool
from tools.fpds_tool import FetchHistoricalPricingTool
from tools.shipping_tool import CalculateShippingAndSpreadTool
from tools.compliance_tool import ComplianceCheckTool

def _build_llm(temperature: float = 0.1):
    return LLM(
        model="gemini/gemini-2.5-flash",
        api_key=GOOGLE_API_KEY,
        temperature=temperature,
    )

def build_scout_agent() -> Agent:
    return Agent(
        role="Federal Contract Scout",
        goal="Identify and prioritize federal commodity contract opportunities from USASpending.gov that match WOSB and small business set-aside criteria.",
        backstory="""You are a senior federal procurement intelligence specialist.
Your job is to find commodity opportunities where the government has recently paid good prices.
Always extract: notice_id, title, agency, estimated_value_usd, pop_zip, pop_state, priority_score, flags.
Return ONLY a valid JSON array. No explanation text.""",
        tools=[FetchSamOpportunitiesTool()],
        llm=_build_llm(temperature=0.0),
        verbose=CREW_VERBOSE,
        max_iter=3,
        allow_delegation=False,
    )

def build_analyst_agent() -> Agent:
    return Agent(
        role="Federal Pricing and Profitability Analyst",
        goal=f"""For each lead, automatically calculate a complete bid recommendation using:
1. Historical market prices from FPDS as the ceiling
2. Estimated supplier cost = market_floor * 0.55 (industry standard markup assumption)
3. Flat-rate shipping based on weight and destination
4. {MINIMUM_MARGIN_PCT:.0%} minimum margin enforcement
Return a complete bid recommendation for every lead with no manual input required.""",
        backstory=f"""You are a former DCAA analyst who automates bid calculations for small-business federal resellers.
You never say you need more information. You always produce a complete bid recommendation.
When supplier cost is unknown, use 55% of the market floor price as a conservative estimate
and label it clearly as an ESTIMATE requiring verification.
Always calculate: total_cogs, recommended_bid, gross_profit, actual_margin_pct, go_no_go.
The recommended_bid formula is: min(market_ceiling, total_cogs / (1 - {MINIMUM_MARGIN_PCT}))
Return ONLY a valid JSON array with all pricing fields populated.""",
        tools=[FetchHistoricalPricingTool(), CalculateShippingAndSpreadTool()],
        llm=_build_llm(temperature=0.1),
        verbose=CREW_VERBOSE,
        max_iter=5,
        allow_delegation=False,
    )

def build_redteam_agent() -> Agent:
    return Agent(
        role="Federal Compliance and Red-Team Auditor",
        goal="Audit every lead for BAA/TAA compliance. Issue PASS, FAIL, or REVIEW verdicts.",
        backstory="""You are a former DOJ attorney specializing in False Claims Act cases.
When country of origin is unknown, default to REVIEW status — never FAIL on unknown alone.
Always return a complete JSON object with recommended_bids, requires_review, discarded_leads, pipeline_summary.
Never ask for more information. Always produce the complete report.""",
        tools=[ComplianceCheckTool()],
        llm=_build_llm(temperature=0.0),
        verbose=CREW_VERBOSE,
        max_iter=3,
        allow_delegation=False,
    )
