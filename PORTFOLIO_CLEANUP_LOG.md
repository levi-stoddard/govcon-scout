# Portfolio cleanup log

## Phase 1A — Safety and version control (2026-10-30)

| File | Change | Why |
|---|---|---|
| `../GovConScout_backup_2026-10-30/` | Full copy of the tree (190 files), excluding `venv/` and `.env` | Reversibility. `.env` left out so secret values are not duplicated; the original `.env` is untouched. |
| (whole tree) | Secret scan: API key patterns, assigned secret literals, `.env` values reappearing in other files, SMTP, CAGE/UEI, phones, street addresses, emails, `.cache` JSON, `files.zip` contents, `govcon.db` | Make sure nothing sensitive enters git. No hardcoded secrets found, so nothing needs rotating because of this scan. |
| `.env.example` | New. Every variable name from `.env`, plus `HARD_FLOOR_MARGIN_PCT` and `HUNTER_AUTO_TRACK` (read in `config.py`, commented out), each with a placeholder and a one-line comment | Quickstart without exposing values |
| `.gitignore` | Kept the original entries and added `.streamlit/secrets.toml`, `.venv/`, `*.db`, `*.db-*`, `files/`, `files.zip`, `*.bat`, `.claude/`, `.agents/`, `docs/private/` | Keep secrets, data, caches, launchers and tooling out of git |
| `.git/` | `git init -b main`; `git add -A` (38 files staged, not committed) | Version control; commit waits for review |

### Baseline tests

`python -m pytest tests/ -v` in the project venv (Python 3.13.12, pytest 9.1.1): **59 passed, 1 failed**.

- `tests/test_assistant.py::test_missing_api_key_gives_setup_help` fails because `assistant.chat(api_key="")` falls back to `config.GOOGLE_API_KEY` (`assistant.py:219`), which `load_dotenv()` fills from the real `.env`. The test then makes a live Gemini call and gets a normal reply. This failure was there before any change. It also means the suite is not fully offline when a `.env` is present.

### Scan findings (no values recorded)

- `config.py:62-67`: shipper street, city, state, ZIP and phone have hardcoded defaults. They are placeholder-style (a 555-01xx phone, a generic street) but name a real city/ZIP. Not secrets.
- `INSTALL.md:281, 422, 431`: example `sk-…` / `AIza…` keys. They look like placeholders, and none matches a value in `.env`.
- `INSTALL.md:438-444`: the same placeholder shipper block as `config.py`.
- `tests/fixtures/sam_response.json:1`: a captured SAM.gov response that includes a named contracting officer's government email address (public SAM data).
- `app.py:1022-1026`, `scan_daily.py:197-198`: SMTP variable names and setup help text only; values come from `os.getenv`.
- `tools/compliance_tool.py`, `tests/test_compliance.py`: the "phone" hits are DFARS clause numbers (e.g. 252.225-7001), not phone numbers.

### Not done yet (waiting on a decision)

- The `.bat` launchers were **not** moved to `docs/private/`. They `cd /d "%~dp0"`, so they would stop working there, and the desktop shortcut points at `Launch GovCon Scout.bat`. They contain no personal details and `*.bat` is gitignored.
- No other file outside `.env` holds company details, so nothing else was moved.
- No commit yet.

### Commit

- `c89f84f` (since rewritten as `6ac4941`, see below) Initial import of GovCon Scout (deterministic federal bid scout): the 39 files reviewed above.

## Phase 1B — Make the code tell the truth (2026-10-30)

| File | Change | Why |
|---|---|---|
| `tests/test_assistant.py` | `test_missing_api_key_gives_setup_help` now monkeypatches `assistant.GOOGLE_API_KEY` to `""` (assertion unchanged) | The test was reading the real key from `.env` and making a live Gemini call. Now it is offline and tests what its name says. |
| `tests/fixtures/sam_response.json` | Contracting officer's name, email and phone replaced with `Contracting Officer` / `contracting.officer@example.mil` / `5555550100`. The DLA `DibbsBSM` mailbox is kept because DIBBS detection reads it. | Keep a named individual's contact details out of a public repo. The first commit was later rewritten so the original details are not in history (see below). |
| `docs/private/README.legacy.md` | Copy of the old README (gitignored) | Kept before the rewrite |
| `README.md` | Rewritten: deterministic-pipeline story, accurate diagram, two gates, data sources, both LLM uses (note enrichment, Advisor), quickstart, known limitations, license TODO; no emoji | The old README described a multi-agent LLM system that is no longer the code |
| `agents.py` -> `legacy/agents.py` | `git mv`; module docstring now says it is history only | Nothing imports it (checked with grep), so no imports changed |
| (all files) | Searched for "APEX" (case-insensitive, whole word) across tracked files | No hits; nothing renamed |
| `analytics.py`, `config.py`, `tests/conftest.py`, `tools/__init__.py` | Added one- or two-sentence module docstrings | These were the only modules without one; no logic changed |
| `scan_daily.py` | The module docstring's "marked 🤖" now says "marked with a robot icon in the app" | The only emoji in any docstring. The runtime marker strings are unchanged. |
| `docs/ARCHITECTURE.md` | New: `_apply_margin` walk-through with worked examples computed by the real function, compliance verdict order, unknown-COO REVIEW, estimate cap, ceiling below COGS, edge cases | Interview prep and design record |
| `.gitignore` | Added `quotes/` and `smoke_test_result.json` | The scanner and smoke test write these; quote sheets include company details |

Tests after Phase 1B: **60 passed, 0 failed** (`python -m pytest tests/ -v`).

Search for "founder", ForgeX, Binnacle, Stoddard: no hits in tracked files. The only match was the substring "Found**Er**ror" in `INSTALL.md:572`, which is not a real hit.

Found and documented in the README (not fixed, because these are logic changes):

- `GRAINGER_API_KEY`, `ZORO_API_KEY`, `USPS_USER_ID` and the `SHIPPER_*` variables are defined but unused.
- `GEMINI_MODEL` is not honored by `assistant.py` or `crew_runner.py`.
- `analytics.beat_this_price` defaults to a 15% margin; the rest of the app uses 25%.
- A NO-GO lead still reports a `recommended_max_bid_usd`.
- With no ceiling data, a verified quote can reach GO.
- A SAM.gov 429 response looks the same as an empty result in the UI.

## History rewrite (2026-10-30, approved)

The contracting officer's contact details were in the initial commit, so I rebuilt both commits with `git commit-tree`. The original messages, authors and dates are kept.

| Old | New | Difference |
|---|---|---|
| `c89f84f` Initial import | `6ac4941` | `tests/fixtures/sam_response.json` contains the placeholder contact |
| `b2377ed` Docs | `8a1a6e1` | Identical tree; the fixture no longer shows as changed in this commit |

- Verified: `git log -p main` contains no reference to the officer, and the working tree is unchanged.
- Tests: 60 passed.
- The old commits remain only in the local reflog (they are never pushed). The folder backup still has the original fixture.
