# 🦅 GovCon Scout — Federal Commodity AI (POC)

A multi-agent AI system for autonomously scouting, evaluating, and recommending 
federal commodity contracts — with strict BAA/TAA compliance guardrails.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                    │
│  - Search input (keyword, NAICS, settings)                  │
│  - Live pipeline status display                             │
│  - Tabbed results: Cleared / Review / Discarded             │
│  - JSON + CSV export                                        │
└────────────────────┬────────────────────────────────────────┘
                     │  .run(keyword, naics_code)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              GovConScoutCrew (crew_runner.py)               │
│              CrewAI Sequential Process                      │
└──────┬──────────────────┬──────────────────┬───────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
┌─────────────┐  ┌─────────────────┐  ┌──────────────────┐
│  AGENT 1    │  │    AGENT 2      │  │    AGENT 3       │
│  Scout      │  │    Analyst      │  │    Red-Team      │
│             │  │                 │  │                  │
│ Tools:      │  │ Tools:          │  │ Tools:           │
│ • SAM.gov   │  │ • FPDS/USA-     │  │ • FAR/DFARS      │
│   API       │  │   Spending      │  │   clause parser  │
│             │  │ • Grainger/Zoro │  │ • BAA/TAA        │
│             │  │   /Google Shop  │  │   validator      │
│             │  │ • EasyPost      │  │ • Banned country │
└──────┬──────┘  └────────┬────────┘  └────────┬─────────┘
       │                  │                     │
       │ JSON leads        │ Priced leads        │ Final report
       └──────────────────┘─────────────────────┘
                  Sequential context handoff
```

### Data Flow

| Stage     | Input               | Output                              |
|-----------|---------------------|-------------------------------------|
| **Scout** | Keyword + NAICS     | Ranked SAM leads (JSON array)       |
| **Analyst** | SAM leads         | Leads + Floor/Ceiling/Bid/Margin    |
| **Red-Team** | Priced leads     | PASS / REVIEW / FAIL per lead       |

### Verdict System

| Verdict   | Meaning                          | Action                         |
|-----------|----------------------------------|--------------------------------|
| ✅ PASS   | All compliance checks clear      | Cleared for bidding            |
| ⚠️ REVIEW | Ambiguous (COO unknown, etc.)    | Attorney review required       |
| ❌ FAIL   | Fatal BAA/TAA violation          | Auto-discarded, audit trail    |

---

## Setup

### 1. Clone and install

```bash
git clone <your-repo>
cd govcon_scout
pip install -r requirements.txt
```

### 2. Configure secrets

```bash
cp .env.example .env
# Edit .env with your API keys
```

### API Keys Required

| Service | Purpose | Cost | Link |
|---------|---------|------|------|
| OpenAI | LLM (GPT-4o) | Pay-per-use | [platform.openai.com](https://platform.openai.com) |
| SAM.gov | Opportunity data | Free | [sam.gov/api](https://open.gsa.gov/api/get-opportunities-public-api/) |
| EasyPost | Shipping rates | Free tier | [easypost.com](https://www.easypost.com) |
| Grainger | Supplier pricing | Partner req. | [grainger.com/supplierhub](https://www.grainger.com/content/supplierhub) |
| Zoro | Supplier pricing (alt.) | Partner req. | [zoro.com/partner](https://www.zoro.com/partner) |
| Google CSE | Fallback pricing | $5/1000 queries | [programmablesearchengine.google.com](https://programmablesearchengine.google.com) |

> **Minimum viable config:** OpenAI + SAM.gov + EasyPost.  
> Grainger/Zoro improve pricing accuracy significantly — apply for API access early.

### 3. Run the app

```bash
streamlit run app.py
```

---

## File Structure

```
govcon_scout/
├── app.py                  # Streamlit UI
├── config.py               # All settings, keys, constants
├── crew_runner.py          # CrewAI crew & task assembly
├── agents.py               # Agent definitions + system prompts
├── tools/
│   ├── sam_tool.py         # SAM.gov API + NSN/FSC extraction
│   ├── fpds_tool.py        # USASpending.gov historical pricing
│   ├── supplier_tool.py    # Grainger / Zoro / Google Shopping
│   ├── shipping_tool.py    # EasyPost + spread calculation
│   └── compliance_tool.py  # FAR/DFARS + BAA/TAA gate
├── requirements.txt
└── .env.example
```

---

## Business Logic Constants

| Constant | Value | Location |
|----------|-------|----------|
| Minimum margin (hard floor) | 15% | `config.py` |
| Micro-purchase threshold | $10,000 | `config.py` |
| FPDS lookback window | 3 years | `config.py` |
| Annual inflation adjustment | 3.5% | `config.py` |
| TAA threshold (supplies) | $183,000 | `compliance_tool.py` |

---

## Key GovCon Concepts Implemented

- **NSN / FSC Mapping:** Extracted from solicitation description regex, used to 
  dramatically improve FPDS historical price matching accuracy vs. keyword search.
- **Floor / Ceiling Pricing:** Floor = lowest historical award; Ceiling = 
  CPI-adjusted 3-year average. Never bid above the Ceiling.
- **Recommended Max Bid:** `min(ceiling, cogs / (1 - 0.15))` — enforces margin.
- **BAA / TAA Compliance:** Automatic clause detection + country validation.
  FAIL verdicts are permanent — no override mechanism exists by design.
- **52.219-14 (Limitations on Subcontracting):** Flagged on all set-aside leads 
  for supplies — you must be the manufacturer or regular dealer.

---

## Upgrade Path (Post-POC)

1. **Parallel processing:** Switch from `Process.sequential` to `Process.hierarchical` 
   to price multiple leads simultaneously.
2. **Solicitation full-text fetch:** Integrate `requests` to pull the actual 
   solicitation PDF/HTML for more accurate clause detection.
3. **DLA NSN database:** Integrate the DLA's public NSN catalog API for precise 
   historical pricing by part number.
4. **Bid automation:** Add a fourth agent that generates the SF-1449 or SAM.gov 
   quote submission package.
5. **Alerts:** Add `schedule` + email/Slack alerts for high-priority new WOSB leads.
