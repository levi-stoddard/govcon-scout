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
