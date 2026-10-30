# 🦅 GovCon Scout — Complete Windows Installation Guide

> **Who this is for:** Someone who may not have done Python development on Windows before.  
> Every single command is written out. Every API is explained. Nothing is assumed.  
> Read each section fully before running commands — the order matters.

---

## 📋 Table of Contents

1. [What You're Installing & Why](#1-what-youre-installing--why)
2. [Phase 1 — Windows Prerequisites](#2-phase-1--windows-prerequisites)
3. [Phase 2 — Project Setup](#3-phase-2--project-setup)
4. [Phase 3 — API Keys (All 6 Services)](#4-phase-3--api-keys-all-6-services)
5. [Phase 4 — Configure Your .env File](#5-phase-4--configure-your-env-file)
6. [Phase 5 — First Launch](#6-phase-5--first-launch)
7. [Phase 6 — Verify Everything Works](#7-phase-6--verify-everything-works)
8. [Troubleshooting](#8-troubleshooting)
9. [Daily Operating Procedure](#9-daily-operating-procedure)
10. [Cost Tracker](#10-cost-tracker)

---

## 1. What You're Installing & Why

Before touching the keyboard, understand what each piece does so nothing feels like magic.

```
YOUR COMPUTER
│
├── Python 3.11          ← The programming language the app runs on
├── pip                  ← Python's package installer (like an app store for code)
├── virtualenv           ← Keeps this project's packages isolated from everything else
│
└── govcon_scout/        ← The project folder
    ├── Streamlit        ← Builds the web UI you'll use in your browser
    ├── CrewAI           ← Runs the 3 AI agents (Scout, Analyst, Red-Team)
    ├── LangChain        ← Connects CrewAI to OpenAI's GPT-4o
    ├── EasyPost SDK     ← Python library for the shipping API
    ├── Requests         ← Makes HTTP calls to SAM.gov, FPDS, suppliers
    └── Pydantic         ← Validates data between agents
```

### The 6 External Services

| Service | What It Does | Cost | Required? |
|---|---|---|---|
| **OpenAI** | Powers GPT-4o — the brain of all 3 agents | ~$0.01–0.10 per run | ✅ YES |
| **SAM.gov** | Fetches federal contract opportunities | Free | ✅ YES |
| **USPS Web Tools** | Real shipping rate quotes — free, no credit card | Free (email registration only) | ⭐ Optional upgrade |
| **Grainger** | Wholesale supplier pricing (best accuracy) | Free w/ partner account | ⭐ Recommended |
| **Zoro** | Alternate wholesale supplier pricing | Free w/ partner account | ⭐ Recommended |
| **Google CSE** | Shopping price fallback | $5 per 1,000 searches | ⚠️ Fallback only |

> **Minimum to launch:** OpenAI + SAM.gov. Shipping uses a built-in flat-rate estimate table by default — no account or credit card needed. USPS Web Tools is a free optional upgrade for real rates.

---

## 2. Phase 1 — Windows Prerequisites

Open **PowerShell as Administrator** for this entire section.

> **How to open PowerShell as Administrator:**  
> Press `Windows key`, type `PowerShell`, right-click **Windows PowerShell**, click **Run as administrator**. Click Yes on the UAC prompt.

---

### Step 1.1 — Check if Python is already installed

```powershell
python --version
```

**If you see** `Python 3.11.x` or `Python 3.12.x` → skip to Step 1.3.  
**If you see** `Python 3.9.x` or older → you need to upgrade (Step 1.2).  
**If you see** an error or nothing → install Python (Step 1.2).

---

### Step 1.2 — Install Python 3.11

```powershell
# Download Python 3.11 installer
Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile "$env:TEMP\python-installer.exe"

# Run the installer (this opens a GUI window)
Start-Process -FilePath "$env:TEMP\python-installer.exe" -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait

# Verify installation
python --version
```

> ⚠️ **After installation:** Close this PowerShell window and open a **new** one as Administrator.  
> The PATH update won't take effect in the same session.

Expected output: `Python 3.11.9`

---

### Step 1.3 — Upgrade pip (Python's package installer)

```powershell
python -m pip install --upgrade pip
```

Expected output ends with: `Successfully installed pip-24.x.x`

---

### Step 1.4 — Install Git (needed to manage code)

```powershell
# Check if Git is already installed
git --version
```

**If you see** `git version 2.x.x` → skip to Step 1.5.  
**If not installed:**

```powershell
# Download and install Git silently
Invoke-WebRequest -Uri "https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe" -OutFile "$env:TEMP\git-installer.exe"

Start-Process -FilePath "$env:TEMP\git-installer.exe" -ArgumentList "/VERYSILENT /NORESTART" -Wait

# Restart PowerShell after this, then verify:
git --version
```

---

### Step 1.5 — Install virtualenv

```powershell
pip install virtualenv
```

> **What is virtualenv?**  
> Imagine it as a clean sandbox for this project. It keeps GovCon Scout's Python packages completely separate from anything else on your computer. This prevents version conflicts and makes the project reproducible.

---

## 3. Phase 2 — Project Setup

> **From here on, you do NOT need Administrator mode.**  
> Close the admin PowerShell and open a **regular** PowerShell window.

---

### Step 2.1 — Choose where to put the project

```powershell
# Go to your Documents folder (or wherever you want the project)
cd $env:USERPROFILE\Documents

# Create a dedicated folder for your GovCon projects
New-Item -ItemType Directory -Name "GovConScout" -Force
cd GovConScout
```

---

### Step 2.2 — Copy the project files into this folder

Take the `govcon_scout` folder you downloaded from Claude and move it into `GovConScout`. Your structure should look like this:

```
Documents\
  GovConScout\
    govcon_scout\
      app.py
      agents.py
      config.py
      crew_runner.py
      requirements.txt
      .env.example
      tools\
        sam_tool.py
        fpds_tool.py
        supplier_tool.py
        shipping_tool.py
        compliance_tool.py
```

Navigate into the project folder:

```powershell
cd govcon_scout
```

Verify you're in the right place:

```powershell
# This should list app.py, agents.py, config.py, etc.
Get-ChildItem
```

---

### Step 2.3 — Create the virtual environment

```powershell
# Create a virtual environment named "venv" inside the project folder
python -m venv venv
```

This creates a `venv\` folder — don't touch it manually.

---

### Step 2.4 — Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

> ⚠️ **If you get a red error about "execution policy"**, run this first:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Then try the activate command again.

**You'll know it worked** when your prompt changes to show `(venv)` at the start:
```
(venv) PS C:\Users\YourName\Documents\GovConScout\govcon_scout>
```

> 🔴 **Critical:** You must activate the venv EVERY time you open a new PowerShell to work on this project. If `(venv)` isn't showing, the app won't run correctly.

---

### Step 2.5 — Install all Python packages

```powershell
pip install -r requirements.txt
```

This installs everything: CrewAI, Streamlit, LangChain, EasyPost, and all dependencies.

Expected: lots of output, ends with `Successfully installed ...`

> ⏳ **This takes 3–8 minutes** on first run. It's downloading ~50 packages. Normal.

---

### Step 2.6 — Create your .env file

```powershell
# Copy the template to a real .env file
Copy-Item .env.example .env
```

> **What is a .env file?**  
> It's a private text file that holds your API keys. The app reads it on startup.  
> It stays on your computer only — never share it, never commit it to GitHub.

---

## 4. Phase 3 — API Keys (All 6 Services)

Work through these in order. Open each link in your browser.

---

### 🔑 API Key 1 — OpenAI (GPT-4o) ← Most Important

**What it does:** Provides the AI reasoning for all three agents. Without this, nothing works.

**Cost:** Pay-as-you-go. One full pipeline run (Scout + Analyst + Red-Team) costs roughly **$0.05–$0.15** using GPT-4o.

**How to get it:**

1. Go to [https://platform.openai.com/signup](https://platform.openai.com/signup)
2. Create an account (or sign in if you have one)
3. Go to [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
4. Click **"+ Create new secret key"**
5. Name it: `GovCon Scout POC`
6. Click **Create secret key**
7. **COPY IT NOW** — you will never see it again after closing this window

Your key looks like: `sk-proj-aBcDeFgHiJkLmNoPqRsTuVwXyZ...`

**Add billing:**
1. Go to [https://platform.openai.com/settings/organization/billing](https://platform.openai.com/settings/organization/billing)
2. Add a credit card
3. Set a **spending limit** of $10/month to start (Settings → Limits)

> 💡 **Recommended model:** `gpt-4o` is already set in `config.py`. If costs are a concern during testing, change it to `gpt-4o-mini` in your `.env` file — it's 10x cheaper but slightly less accurate on legal clause interpretation.

---

### 🔑 API Key 2 — SAM.gov (Free)

**What it does:** This is the live feed of all federal contract opportunities. The Scout agent queries this.

**How to get it:**

1. Go to [https://sam.gov/](https://sam.gov/)
2. Click **Sign In** (top right) → **Create Account**
3. You'll be redirected to **login.gov** — create an account there with your email
4. Return to SAM.gov and complete your profile (takes ~5 minutes)
5. Once logged in, go to: [https://open.gsa.gov/api/get-opportunities-public-api/](https://open.gsa.gov/api/get-opportunities-public-api/)
6. Scroll down to **"Getting Started"** and click **"Request API Key"**
7. Fill out the form — use your business email for faster approval
8. The key will be emailed to you within minutes (sometimes instant)

Your key looks like: `aB3dEf7GhIjK9lMnOpQrStUvWx1YzAb`

> ℹ️ **Rate Limit:** 1,000 requests/day on the free key. For the POC, each pipeline run uses ~1–3 requests. You won't hit this limit during development. If you scale up, email GSA to request a higher limit.

---

### 🚢 Shipping — Flat-Rate Table (Default, No Setup Required)

The app ships with a built-in flat-rate estimate table that runs automatically with zero configuration. No account, no credit card, nothing to sign up for.

| Package Weight | Estimated Shipping Cost |
|---|---|
| Up to 1 lb | $8.50 |
| 1–5 lbs | $14.00 |
| 5–20 lbs | $22.00 |
| Over 20 lbs | $35.00 + $0.80/lb |

These are conservative continental US averages. For the POC, they are completely sufficient — you are modeling profitability, not printing shipping labels. Any lead the app marks `✅ GO` will show `⚠️ SHIPPING ESTIMATE UNVERIFIED` as a reminder to confirm the real rate before submitting a live bid.

---

### 🔑 API Key 3 — USPS Web Tools (Free Upgrade — No Credit Card)

**What it does:** Replaces the flat-rate estimate with a real USPS Priority Mail quote for the exact destination ZIP code. Optional but recommended once you start looking at real bids.

**How to register (email only — no credit card):**

1. Go to [https://www.usps.com/business/web-tools-apis/](https://www.usps.com/business/web-tools-apis/)
2. Click **"Get Started"** under Web Tools API Portal
3. Fill out the registration form with your name, business name, and email
4. You will receive a **USPS User ID** by email within 24 hours
5. It looks like: `123YOURB4567`

Once you have it, add it to your `.env` file:
```dotenv
USPS_USER_ID=123YOURB4567
```

The app will automatically switch from the flat-rate table to live USPS rates on the next run. No other changes needed.

---

### 🔑 API Key 4 — Grainger (Partner API) ← Apply Early

**What it does:** Returns real wholesale pricing for industrial and commercial commodities. This is your primary COGS data source. It dramatically outperforms Google Shopping for accuracy.

**How to apply:**

1. Go to [https://www.grainger.com/content/supplierhub](https://www.grainger.com/content/supplierhub)
2. Click **"Apply for API Access"** or email `api@grainger.com`
3. In the application, mention:
   - You are a WOSB federal reseller
   - You need programmatic access for contract pricing lookups
   - You expect low-volume requests (< 500/day to start)
4. Approval typically takes **3–7 business days**

> ⏳ **Don't wait for this to proceed.** The app works without it — Grainger access just dramatically improves pricing accuracy. Move forward with OpenAI + SAM.gov + EasyPost and add Grainger when approved.

Your key will look like: `Bearer grngrApiKey_xxxxx...`

---

### 🔑 API Key 5 — Zoro (Alternate Supplier)

**What it does:** Industrial/commercial products supplier — fallback if Grainger doesn't have an item.

**How to apply:**

1. Go to [https://www.zoro.com/partner](https://www.zoro.com/partner) or [https://developer.zoro.com](https://developer.zoro.com)
2. Click **"Get Started"** / **"Apply"**
3. Similar application to Grainger — mention your WOSB reseller use case

> ℹ️ Apply to both Grainger and Zoro simultaneously. Whichever approves first gets used.

---

### 🔑 API Key 6 — Google Custom Search Engine (Fallback Only)

**What it does:** Last-resort fallback for commodity pricing when Grainger and Zoro don't have the item. Less accurate because it's scraping retail prices, not wholesale.

**How to set up (two parts):**

**Part A — Get a Google Cloud API Key:**
1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Create a new project: name it `GovCon Scout`
3. Go to **APIs & Services → Credentials**
4. Click **+ Create Credentials → API Key**
5. Copy the key (starts with `AIza...`)
6. Click **Edit API Key** and restrict it to **Custom Search API** only

**Part B — Create a Custom Search Engine:**
1. Go to [https://programmablesearchengine.google.com/](https://programmablesearchengine.google.com/)
2. Click **Get started** → **Add**
3. Under "Sites to search": enter `*.grainger.com, *.zoro.com, *.mcmaster.com, *.amazon.com`
4. Name it: `GovCon Supplier Search`
5. Click **Create**
6. On the next screen, copy the **Search engine ID** (looks like: `abc123def456:xyz789...`)
7. Go to **Edit search engine → Search features → Enable "Search the entire web"**

---

## 5. Phase 4 — Configure Your .env File

Now you'll put all those keys into the `.env` file.

### Open .env in Notepad

```powershell
notepad .env
```

Replace the placeholder values with your actual keys. Here's exactly what each line should look like after filling it in:

```dotenv
# ── LLM ─────────────────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-proj-YOUR_ACTUAL_KEY_HERE
OPENAI_MODEL=gpt-4o

# ── SAM.gov ──────────────────────────────────────────────────────────────────
SAM_API_KEY=YOUR_SAM_KEY_HERE

# ── Supplier APIs ─────────────────────────────────────────────────────────────
GRAINGER_API_KEY=                        ← Leave blank until approved
ZORO_API_KEY=                            ← Leave blank until approved
GOOGLE_CSE_API_KEY=AIzaYOUR_GOOGLE_KEY
GOOGLE_CSE_ID=abc123:xyz789

# ── Shipping ─────────────────────────────────────────────────────────────────
# Leave blank to use the built-in flat-rate table (no signup needed)
# Add your USPS User ID here once approved for real rates (free)
USPS_USER_ID=

# ── Your Warehouse / Ship-From Address ───────────────────────────────────────
SHIPPER_STREET=123 Your Street
SHIPPER_CITY=Meridian
SHIPPER_STATE=ID
SHIPPER_ZIP=83642
SHIPPER_PHONE=2085550100

# ── Pipeline Flags ────────────────────────────────────────────────────────────
CREW_VERBOSE=true
```

> ⚠️ **Rules for the .env file:**
> - No spaces around the `=` sign
> - No quotes around values
> - Never add the `.env` file to GitHub or share it in screenshots

Save and close Notepad.

---

### Verify your .env was saved correctly

```powershell
# Read the file back — confirm your keys are there
Get-Content .env
```

---

## 6. Phase 5 — First Launch

Make sure your virtual environment is active — you should see `(venv)` in your prompt. If not:

```powershell
cd $env:USERPROFILE\Documents\GovConScout\govcon_scout
.\venv\Scripts\Activate.ps1
```

### Launch the Streamlit app

```powershell
streamlit run app.py
```

You'll see output like:

```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.x.x:8501
```

Your browser should open automatically. If not, open it manually and go to:
```
http://localhost:8501
```

> 🎉 If you see the GovCon Scout interface with the search sidebar — **installation is complete.**

---

## 7. Phase 6 — Verify Everything Works

Run a test pipeline to confirm all services are connected.

### Test Run 1 — Minimum viable (OpenAI + SAM.gov only)

In the Streamlit UI:
1. **Commodity Keyword:** `nitrile gloves`
2. **NAICS Code:** `339113`
3. Click **Launch Scout Pipeline**

**What to watch for:**
- Status box shows all 5 steps turning green ✅
- Pipeline Summary shows numbers (even if all leads get flagged)
- No red "Pipeline error" message

### Test Run 2 — Verify shipping is calculating

Run the same search. In the results, look for any cleared lead and check if the **Shipping** field shows a dollar amount (e.g., `$14.00`). If it does, the flat-rate table is working. If you have added a USPS User ID, it will instead show `USPS Priority Mail (live rate)` and a real ZIP-based quote.

### Test the compliance engine specifically

Try this keyword to trigger BAA/TAA checks:
- **Keyword:** `steel brackets`
- **NAICS:** `332999`

The Red-Team should activate and you'll see FAR clause detection in the results.

---

### Quick API Health Check (PowerShell)

Run these to confirm each API is reachable before launching the full pipeline:

```powershell
# Test SAM.gov API (replace YOUR_SAM_KEY with your actual key)
$samKey = "YOUR_SAM_KEY"
Invoke-RestMethod -Uri "https://api.sam.gov/opportunities/v2/search?api_key=$samKey&q=gloves&limit=1&postedFrom=01/01/2025&postedTo=12/31/2025" -Method GET | ConvertTo-Json -Depth 2
```

Expected: JSON with `totalRecords` > 0 and an `opportunitiesData` array.

```powershell
# Test USASpending.gov (no key needed)
Invoke-RestMethod -Uri "https://api.usaspending.gov/api/v2/references/agency/list/?limit=1" -Method GET | ConvertTo-Json
```

Expected: JSON with `results` array containing agency names.

```powershell
# Test OpenAI API (replace YOUR_OPENAI_KEY with your actual key)
$headers = @{"Authorization" = "Bearer YOUR_OPENAI_KEY"; "Content-Type" = "application/json"}
$body = '{"model":"gpt-4o","messages":[{"role":"user","content":"Say: API connected."}],"max_tokens":10}'
Invoke-RestMethod -Uri "https://api.openai.com/v1/chat/completions" -Method POST -Headers $headers -Body $body | ConvertTo-Json
```

Expected: JSON with `choices[0].message.content` = `"API connected."`

---

## 8. Troubleshooting

### ❌ `.\venv\Scripts\Activate.ps1` — "cannot be loaded, running scripts is disabled"

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Then try activating again.

---

### ❌ `ModuleNotFoundError: No module named 'crewai'`

Your virtual environment isn't active. Run:
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

### ❌ `openai.AuthenticationError: No API key provided`

Your `.env` file isn't being read. Check:
```powershell
# Are you in the right directory?
pwd
# Should show: ...GovConScout\govcon_scout

# Does .env exist?
Test-Path .env
# Should show: True

# Does it have your key?
Get-Content .env | Select-String "OPENAI"
```

---

### ❌ SAM.gov returns 0 results

This is usually a date range issue. SAM.gov requires both `postedFrom` and `postedTo` within the last 365 days. The Scout is configured to handle this, but if you're getting zero results:
- Try a broader keyword (`gloves` instead of `nitrile powder-free gloves`)
- Increase the "Days Lookback" slider in the Streamlit sidebar to 90

---

### ❌ Shipping always shows "Flat-Rate Estimate" even after adding USPS_USER_ID

Check that your USPS User ID was saved correctly:
```powershell
Get-Content .env | Select-String "USPS"
```
Also confirm your USPS account is fully activated — USPS sends a second confirmation email after the initial registration that must be completed before the API works.

---

### ❌ Streamlit opens but immediately shows a Python traceback

Read the last few lines of the error. The most common causes:
1. Missing `.env` file → run `Copy-Item .env.example .env` and fill it in
2. Wrong Python version → run `python --version` (must be 3.11+)
3. Package not installed → run `pip install -r requirements.txt` again with `(venv)` active

---

### ❌ `CrewAI` completes but returns empty `recommended_bids`

This is normal behavior, not a bug. It means:
- No WOSB set-aside opportunities exist for that keyword right now (the government only posts what it posts), OR
- All leads failed the Red-Team compliance gate (usually means `country_of_origin` was unknown)

Try different keywords: `office supplies`, `safety gloves`, `hand tools`, `cleaning products`.

---

## 9. Daily Operating Procedure

Once installed, this is all you need to do every time you use the system.

```powershell
# 1. Open PowerShell (regular, not admin)
# 2. Navigate to project
cd $env:USERPROFILE\Documents\GovConScout\govcon_scout

# 3. Activate the virtual environment
.\venv\Scripts\Activate.ps1

# 4. Launch the app
streamlit run app.py

# 5. When done — stop the app
# Press Ctrl+C in the PowerShell window

# 6. Deactivate the environment (optional but clean)
deactivate
```

> 💡 **Pro tip:** Save steps 2–4 as a PowerShell script so you can double-click to launch.

```powershell
# Run this ONCE to create a launch shortcut:
@"
cd `$env:USERPROFILE\Documents\GovConScout\govcon_scout
.\venv\Scripts\Activate.ps1
streamlit run app.py
"@ | Out-File -FilePath "$env:USERPROFILE\Desktop\Launch GovCon Scout.ps1" -Encoding UTF8
```

Now you have a `Launch GovCon Scout.ps1` file on your desktop. Right-click → **Run with PowerShell** to start the app.

---

## 10. Cost Tracker

Keep track of what you're actually spending. Everything below is an estimate based on typical POC usage.

### Monthly Cost at Low Volume (50 pipeline runs/month)

| Service | Cost Basis | Est. Monthly |
|---|---|---|
| OpenAI GPT-4o | ~$0.10 per run × 50 | **$5.00** |
| SAM.gov | Free | **$0.00** |
| USPS Web Tools | Free | **$0.00** |
| Flat-rate shipping fallback | Free (built-in) | **$0.00** |
| Google CSE | $5/1000 queries | **~$1.00** |
| **Total** | | **~$6.00/month** |

### Switching to GPT-4o-mini (if costs are a concern during testing)

Edit `.env`:
```dotenv
OPENAI_MODEL=gpt-4o-mini
```

Cost drops to roughly **$0.005 per run** — 20× cheaper. Compliance clause detection is slightly less reliable, but acceptable for POC and learning.

### Set a Hard Spending Cap in OpenAI

1. Go to [https://platform.openai.com/settings/organization/limits](https://platform.openai.com/settings/organization/limits)
2. Set **Monthly budget** to `$25`
3. Set **Email notification** at `$10`

This prevents any surprise bills during development.

---

## ✅ Installation Complete Checklist

Run through this before your first real search:

```
□ Python 3.11+ installed  (python --version)
□ Virtual environment created  (venv\ folder exists)
□ Virtual environment activated  ((venv) in prompt)
□ All packages installed  (pip list | findstr crewai)
□ .env file created and filled in
□ OpenAI key added and billing set up
□ SAM.gov key added
□ Shipping runs automatically (flat-rate table requires no setup)
□ USPS_USER_ID added if you have it (optional — skip for now)
□ Shipper address updated to YOUR address in .env
□ Streamlit opens at http://localhost:8501
□ Test run completed with keyword "nitrile gloves"
```

---

## 📞 Quick Reference — Key URLs

| Resource | URL |
|---|---|
| OpenAI API Keys | https://platform.openai.com/api-keys |
| OpenAI Usage/Billing | https://platform.openai.com/settings/organization/billing |
| SAM.gov API Docs | https://open.gsa.gov/api/get-opportunities-public-api/ |
| SAM.gov (search manually) | https://sam.gov/search/?index=opp |
| USASpending.gov (FPDS) | https://api.usaspending.gov/ |
| USPS Web Tools Registration | https://www.usps.com/business/web-tools-apis/ |
| Grainger API Program | https://www.grainger.com/content/supplierhub |
| Google Cloud Console | https://console.cloud.google.com/ |
| Google CSE | https://programmablesearchengine.google.com/ |
| DLA NSN Search (manual) | https://www.dla.mil/LandandMaritime/Business/Selling/NSN-Management/ |
| FAR/DFARS Clause Index | https://www.acquisition.gov/browse/index/far |
| TAA Country List | https://ustr.gov/trade-agreements/free-trade-agreements |

---

*Last updated: May 2026 | GovCon Scout POC v1.0*
