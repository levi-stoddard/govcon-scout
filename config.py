from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM (optional — pipeline is deterministic by default) ─────────────────────
# SECURITY: never hardcode keys in this file. Keys live in .env only.
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CREW_VERBOSE: bool = os.getenv("CREW_VERBOSE", "true").lower() == "true"

# When False (default) the pipeline runs 100% deterministic Python — no LLM
# calls, no cost, fully testable. Set USE_LLM=true in .env to enable LLM-written
# bid notes and lead relevance annotation on top of the deterministic results.
USE_LLM: bool = os.getenv("USE_LLM", "false").lower() == "true"

# ── SAM.gov (LIVE opportunities — the ones you can actually bid on) ──────────
SAM_API_KEY: str = os.getenv("SAM_API_KEY", "")
SAM_BASE_URL: str = "https://api.sam.gov/opportunities/v2/search"
SAM_DESC_URL: str = "https://api.sam.gov/opportunities/v1/noticedesc"
# ptype codes: k=Combined Synopsis/Solicitation, o=Solicitation,
#              r=Sources Sought, p=Presolicitation, s=Special Notice
SAM_PTYPES: list[str] = ["k", "o", "r", "p"]
SAM_DAYS_POSTED_DEFAULT: int = 30
# Personal SAM.gov API keys have LOW daily request quotas. Each description
# fetch is one extra request, so only fetch full text for the top N leads.
SAM_DESC_FETCH_LIMIT: int = int(os.getenv("SAM_DESC_FETCH_LIMIT", "5"))

SAM_SETASIDE_PRIORITY: dict[str, str] = {
    "WOSB": "Women-Owned Small Business",
    "EDWOSB": "Economically Disadvantaged WOSB",
    "SBA": "Total Small Business",
    "8A": "8(a) Program",
    "HZC": "HUBZone",
    "SDVOSBC": "Service-Disabled Veteran-Owned",
}
# Set-asides YOU are eligible for. Until registrations/certifications are done,
# unrestricted + Total Small Business are the realistic targets.
MY_ELIGIBLE_SETASIDES: set[str] = set(
    s.strip() for s in os.getenv("MY_ELIGIBLE_SETASIDES", "SBA,").split(",") if s.strip()
)

# ── USASpending / FPDS (HISTORICAL awards — pricing data, not leads) ─────────
FPDS_BASE_URL: str = "https://api.usaspending.gov/api/v2"
FPDS_LOOKBACK_YEARS: int = 3
INFLATION_RATE_ANNUAL: float = 0.035

# ── Supplier pricing ──────────────────────────────────────────────────────────
GRAINGER_API_KEY: str = os.getenv("GRAINGER_API_KEY", "")
GRAINGER_PRODUCT_URL: str = "https://api.grainger.com/v1/products/search"
ZORO_API_KEY: str = os.getenv("ZORO_API_KEY", "")
ZORO_PRODUCT_URL: str = "https://api.zoro.com/v1/search"
GOOGLE_CSE_API_KEY: str = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_ID: str = os.getenv("GOOGLE_CSE_ID", "")

# ── Shipping ──────────────────────────────────────────────────────────────────
USPS_USER_ID: str = os.getenv("USPS_USER_ID", "")
SHIPPER_ZIP: str = os.getenv("SHIPPER_ZIP", "83642")
SHIPPER_ADDRESS: dict = {
    "name": "GovCon Scout Warehouse",
    "street1": os.getenv("SHIPPER_STREET", "123 Commerce Blvd"),
    "city": os.getenv("SHIPPER_CITY", "Meridian"),
    "state": os.getenv("SHIPPER_STATE", "ID"),
    "zip": os.getenv("SHIPPER_ZIP", "83642"),
    "country": "US",
    "phone": os.getenv("SHIPPER_PHONE", "2085550100"),
}

# ── Business rules (SINGLE SOURCE OF TRUTH — nothing else defines these) ─────
MICRO_PURCHASE_THRESHOLD: float = 10_000.00
MINIMUM_MARGIN_PCT: float = 0.25      # default TARGET margin (app slider can change per-search)
HARD_FLOOR_MARGIN_PCT: float = float(os.getenv("HARD_FLOOR_MARGIN_PCT", "0.12"))
# ^ absolute floor: the system NEVER recommends a bid below this margin
PACKAGE_WEIGHT_LBS_DEFAULT: float = 5.0
SUPPLIER_COST_ESTIMATE_RATIO: float = 0.55  # used ONLY for VERIFY_COST estimates

# ── Hunter (autonomous agent) ────────────────────────────────────────────────
HUNTER_AUTO_TRACK: bool = os.getenv("HUNTER_AUTO_TRACK", "true").lower() == "true"
HUNTER_MAX_NEW_NICHES: int = 2        # max niches auto-added per run
NICHE_AUTO_ADD_MIN_SCORE: float = 15.0
QUOTES_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quotes")

# ── Compliance ────────────────────────────────────────────────────────────────
TAA_COMPLIANT_COUNTRIES: set[str] = {"US","AU","AT","BE","BG","CA","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IL","IT","JP","LV","LT","LU","MT","MX","NL","NZ","NO","PL","PT","RO","SK","SI","KR","ES","SE","CH","TW","GB","SG"}
BAA_BANNED_COUNTRIES: set[str] = {"CN","RU","BY","IR","KP","CU","SY","VE"}
FSC_COMMODITY_MAP: dict[str, str] = {"6505":"Drugs & Biologicals","7510":"Office Supplies","8010":"Paints","8415":"Clothing","8470":"Armor","9905":"Signs","6625":"Measuring Instruments","4240":"Safety Equipment","5120":"Hand Tools","3950":"Lumber","7920":"Cleaning Supplies","5305":"Screws","5310":"Nuts & Washers","8430":"Footwear"}

# FSC classes with landmines a new reseller should avoid (QPL, hazmat, regulated)
FSC_AVOID: set[str] = {"6505", "1377", "1305", "1310", "8140"}
