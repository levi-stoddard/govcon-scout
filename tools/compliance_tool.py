"""
tools/compliance_tool.py — Red-Team Fatal-Error Module
Parses solicitation text for FAR/DFARS clauses, enforces Buy American Act
(BAA) and Trade Agreements Act (TAA) compliance, and validates country of
origin for proposed products.

This module operates as a GATE: any lead that fails compliance is
automatically discarded from the pipeline with a documented reason.
"""

from __future__ import annotations
import json
import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from config import TAA_COMPLIANT_COUNTRIES, BAA_BANNED_COUNTRIES

logger = logging.getLogger(__name__)


# ── Result Types ──────────────────────────────────────────────────────────────
class ComplianceVerdict(str, Enum):
    PASS = "PASS"           # All checks clear — proceed to bidding
    FAIL = "FAIL"           # Fatal issue — discard lead immediately
    REVIEW = "REVIEW"       # Ambiguous — human review required before bidding


@dataclass
class ClauseMatch:
    far_number: str          # e.g. "52.225-1"
    title: str               # e.g. "Buy American — Supplies"
    risk_level: str          # "HIGH", "MEDIUM", "LOW"
    description: str
    recommended_action: str


@dataclass
class ComplianceReport:
    verdict: ComplianceVerdict
    notice_id: str
    fatal_flags: list[str]
    warning_flags: list[str]
    clauses_found: list[ClauseMatch]
    country_of_origin: str | None
    taa_compliant: bool | None
    baa_applies: bool
    requires_domestic_end_product: bool
    recommended_action: str


# ── Clause Catalog ────────────────────────────────────────────────────────────
# Maps FAR/DFARS clause number patterns → compliance metadata
CLAUSE_CATALOG: dict[str, dict[str, Any]] = {
    # ─── Buy American Act ────────────────────────────────────────────────────
    "52.225-1": {
        "title": "Buy American — Supplies",
        "risk": "HIGH",
        "description": (
            "Requires domestic end products. 50% domestic component threshold "
            "(or 75% for iron/steel/manufactured products in some contexts). "
            "TAA countries are generally excepted via 52.225-5 overlay."
        ),
        "action": "Verify product is manufactured in US or TAA-compliant country.",
    },
    "52.225-2": {
        "title": "Buy American Certificate",
        "risk": "HIGH",
        "description": "Offeror must certify end product is domestic or identify exceptions.",
        "action": "Prepare BAA certificate. Document country of origin in quote package.",
    },
    "52.225-3": {
        "title": "Buy American — Free Trade Agreements — Israeli Trade Act",
        "risk": "HIGH",
        "description": "Expands allowable countries to FTA partners.",
        "action": "Verify country of origin is US, FTA partner, or Israeli trade act eligible.",
    },
    # ─── Trade Agreements Act ────────────────────────────────────────────────
    "52.225-5": {
        "title": "Trade Agreements",
        "risk": "HIGH",
        "description": (
            "Applies when acquisition value exceeds TAA threshold (~$183k for supplies). "
            "Product must be from a TAA-designated country."
        ),
        "action": "Confirm country of origin is on TAA-compliant list.",
    },
    "52.225-6": {
        "title": "Trade Agreements Certificate",
        "risk": "HIGH",
        "description": "Offeror certifies end product is TAA-compliant.",
        "action": "Supplier must provide country-of-origin certificate.",
    },
    # ─── DFARS Country of Origin ─────────────────────────────────────────────
    "252.225-7001": {
        "title": "Buy American and Balance of Payments Program",
        "risk": "HIGH",
        "description": "DFARS analog to FAR 52.225-1 for defense contracts.",
        "action": "Requires domestic components. Do NOT source from China, Russia, or sanctioned countries.",
    },
    "252.225-7002": {
        "title": "Qualifying Country Sources as Subcontractors",
        "risk": "MEDIUM",
        "description": "Lists qualifying countries (different from TAA list).",
        "action": "Check DFARS 225.003 for current qualifying country list.",
    },
    "252.225-7009": {
        "title": "Restriction on Acquisition of Certain Articles Containing Specialty Metals",
        "risk": "HIGH",
        "description": "Specialty metals (steel alloys, titanium, tungsten, etc.) must be US-melted/refined.",
        "action": "Flag if commodity contains specialty metals. Source US-origin metals.",
    },
    "252.225-7048": {
        "title": "Export-Controlled Items",
        "risk": "MEDIUM",
        "description": "Contractor must comply with EAR/ITAR for controlled commodities.",
        "action": "Verify commodity ECCN. Obtain export license if required.",
    },
    # ─── Small Business ──────────────────────────────────────────────────────
    "52.219-14": {
        "title": "Limitations on Subcontracting",
        "risk": "MEDIUM",
        "description": (
            "For supplies: small business must perform ≥50% of the cost of manufacture "
            "with its own workforce OR be the manufacturer/regular dealer."
        ),
        "action": (
            "Verify you qualify as manufacturer or regular dealer. "
            "If reselling, you must be the 'regular dealer' in the item. "
            "Document your supply chain relationship."
        ),
    },
    "52.219-3": {
        "title": "Notice of Total HUBZone Small Business Set-Aside",
        "risk": "LOW",
        "description": "Requires offeror to be a certified HUBZone SB.",
        "action": "Confirm HUBZone certification is current if applicable.",
    },
}

# Patterns for clause detection in solicitation text
CLAUSE_PATTERNS: list[tuple[str, re.Pattern]] = [
    (clause_id, re.compile(
        rf"\b{re.escape(clause_id)}\b",
        re.IGNORECASE
    ))
    for clause_id in CLAUSE_CATALOG
]


# ── Main Check Orchestration (plain function — testable without CrewAI) ──────
def run_all_checks(
    notice_id: str,
    text: str,
    coo: str | None,
    est_value: float | None,
    full_text_analyzed: bool = True,
) -> ComplianceReport:
    """
    FATAL-ERROR MODULE. Parses solicitation text for BAA/TAA clauses,
    validates country of origin, returns a binding compliance verdict.

    `full_text_analyzed=False` means only the title/synopsis was available —
    a clean scan of a title proves nothing, so PASS is downgraded to REVIEW.
    """
    fatal_flags: list[str] = []
    warning_flags: list[str] = []
    clauses_found: list[ClauseMatch] = []

    # ── Step 1: Parse clauses from solicitation text ──────────────────
    for clause_id, pattern in CLAUSE_PATTERNS:
        if pattern.search(text):
            meta = CLAUSE_CATALOG[clause_id]
            clauses_found.append(ClauseMatch(
                far_number=clause_id,
                title=meta["title"],
                risk_level=meta["risk"],
                description=meta["description"],
                recommended_action=meta["action"],
            ))

    # ── Step 2: BAA applicability ─────────────────────────────────────
    baa_applies = any(
        c.far_number in ("52.225-1", "52.225-2", "252.225-7001")
        for c in clauses_found
    )
    requires_domestic = baa_applies  # Default: BAA = domestic required

    # ── Step 3: TAA overlay check ─────────────────────────────────────
    taa_clause_present = any(
        c.far_number in ("52.225-5", "52.225-6", "52.225-3")
        for c in clauses_found
    )
    taa_compliant: bool | None = None

    if coo:
        coo_upper = coo.upper()

        # Check hard-banned list first (sanctions / BAA ban)
        if coo_upper in BAA_BANNED_COUNTRIES:
            fatal_flags.append(
                f"🚨 FATAL: Country of origin '{coo_upper}' is on the BAA/sanctions "
                f"banned list. This solicitation CANNOT be fulfilled with this product."
            )
            taa_compliant = False

        # TAA clause overlay: expands allowable countries
        elif taa_clause_present:
            taa_compliant = coo_upper in TAA_COMPLIANT_COUNTRIES
            if not taa_compliant:
                fatal_flags.append(
                    f"🚨 FATAL: Country of origin '{coo_upper}' is NOT on the TAA "
                    f"compliant country list. TAA clause 52.225-5/6 present. "
                    f"Product is ineligible."
                )
            else:
                requires_domestic = False  # TAA exception granted

        # BAA without TAA: must be domestic
        elif baa_applies and coo_upper != "US":
            fatal_flags.append(
                f"🚨 FATAL: BAA clause present and product is from '{coo_upper}' "
                f"(non-domestic). No TAA exception detected. Product is ineligible "
                f"unless a BAA exception applies (see FAR 25.103)."
            )
            taa_compliant = False

    else:
        # No COO provided — this is a risk flag
        if baa_applies or taa_clause_present:
            warning_flags.append(
                "⚠️ Country of origin UNKNOWN. BAA/TAA clauses present. "
                "Must obtain supplier certificate before bidding. Set verdict to REVIEW."
            )

    # ── Step 4: Limitations on Subcontracting (52.219-14) ────────────
    sub_limit_clause = next(
        (c for c in clauses_found if c.far_number == "52.219-14"), None
    )
    if sub_limit_clause:
        warning_flags.append(
            "⚠️ 52.219-14 present: You must be the manufacturer OR a 'regular dealer' "
            "of this supply. Confirm your supply chain role with legal counsel."
        )

    # ── Step 5: Specialty Metals check ───────────────────────────────
    specialty_metals_clause = next(
        (c for c in clauses_found if c.far_number == "252.225-7009"), None
    )
    if specialty_metals_clause:
        metal_keywords = ["steel", "titanium", "tungsten", "chromite", "cobalt",
                          "nickel alloy", "zirconium", "niobium"]
        text_lower = text.lower()
        detected_metals = [m for m in metal_keywords if m in text_lower]
        if detected_metals:
            fatal_flags.append(
                f"🚨 HIGH RISK: Specialty metals clause 252.225-7009 present and "
                f"solicitation mentions: {', '.join(detected_metals)}. "
                f"Must use US-origin specialty metals. Verify with supplier certificate."
            )

    # ── Step 6: High-value TAA threshold ─────────────────────────────
    # TAA threshold for supplies: ~$183,000 (2024 — updates every 2 years)
    TAA_THRESHOLD = 183_000
    if est_value and est_value > TAA_THRESHOLD and not taa_clause_present:
        warning_flags.append(
            f"⚠️ Estimated value ${est_value:,.0f} exceeds TAA threshold "
            f"${TAA_THRESHOLD:,}. Verify whether TAA applies even if not explicitly "
            f"cited in the synopsis."
        )

    # ── Step 7: Final Verdict ─────────────────────────────────────────
    if fatal_flags:
        verdict = ComplianceVerdict.FAIL
        action = (
            "DISCARD THIS LEAD. Fatal compliance issues detected. "
            "Do NOT submit a bid without resolving all FATAL flags."
        )
    elif warning_flags or (baa_applies and not coo):
        verdict = ComplianceVerdict.REVIEW
        action = (
            "HOLD FOR REVIEW. Ambiguous compliance status. "
            "Obtain supplier certificate of origin and consult GovCon counsel."
        )
    elif not full_text_analyzed:
        # A clean scan of just the title proves nothing — never PASS on it.
        verdict = ComplianceVerdict.REVIEW
        warning_flags.append(
            "⚠️ Full solicitation text was NOT analyzed (title/synopsis only). "
            "Fetch and review the complete solicitation before bidding."
        )
        action = (
            "HOLD FOR REVIEW. Compliance scan ran on partial text only. "
            "Read the full solicitation document before bidding."
        )
    else:
        verdict = ComplianceVerdict.PASS
        action = (
            "Lead is cleared for bidding. Document all compliance evidence "
            "and include BAA/TAA certificates in the bid package."
        )

    return ComplianceReport(
        verdict=verdict,
        notice_id=notice_id,
        fatal_flags=fatal_flags,
        warning_flags=warning_flags,
        clauses_found=clauses_found,
        country_of_origin=coo,
        taa_compliant=taa_compliant,
        baa_applies=baa_applies,
        requires_domestic_end_product=requires_domestic,
        recommended_action=action,
    )

def serialize_report(report: ComplianceReport) -> str:
    return json.dumps({
        "verdict": report.verdict.value,
        "notice_id": report.notice_id,
        "summary": {
            "baa_applies": report.baa_applies,
            "taa_compliant": report.taa_compliant,
            "requires_domestic_end_product": report.requires_domestic_end_product,
            "country_of_origin_checked": report.country_of_origin,
        },
        "fatal_flags": report.fatal_flags,
        "warning_flags": report.warning_flags,
        "clauses_detected": [
            {
                "far_number": c.far_number,
                "title": c.title,
                "risk_level": c.risk_level,
                "recommended_action": c.recommended_action,
            }
            for c in sorted(
                report.clauses_found,
                key=lambda c: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(c.risk_level, 3)
            )
        ],
        "recommended_action": report.recommended_action,
    }, indent=2)


def run_compliance_check(
    notice_id: str,
    solicitation_text: str,
    country_of_origin: str | None = None,
    estimated_value_usd: float | None = None,
    full_text_analyzed: bool = True,
) -> dict:
    """Plain-function entry point. Returns the compliance report as a dict."""
    report = run_all_checks(
        notice_id, solicitation_text, country_of_origin,
        estimated_value_usd, full_text_analyzed,
    )
    return json.loads(serialize_report(report))


# ── Optional CrewAI wrapper (only needed when USE_LLM=true) ──────────────────
try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    class ComplianceCheckInput(BaseModel):
        notice_id: str = Field(description="SAM.gov notice ID")
        solicitation_text: str = Field(description="Full text of the solicitation to analyze")
        country_of_origin: str | None = Field(default=None, description="ISO country code, e.g. 'US'")
        estimated_value_usd: float | None = Field(default=None, description="Estimated contract value")

    class ComplianceCheckTool(BaseTool):
        name: str = "run_compliance_check"
        description: str = (
            "Parses FAR/DFARS clauses from solicitation text, validates BAA/TAA "
            "requirements, returns binding PASS/FAIL/REVIEW verdict."
        )
        args_schema: type[BaseModel] = ComplianceCheckInput

        def _run(self, notice_id, solicitation_text, country_of_origin=None, estimated_value_usd=None):
            return json.dumps(
                run_compliance_check(notice_id, solicitation_text, country_of_origin, estimated_value_usd),
                indent=2,
            )
except ImportError:
    ComplianceCheckTool = None  # type: ignore
