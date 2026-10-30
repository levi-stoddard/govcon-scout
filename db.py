"""
db.py — SQLite persistence layer (Tier 1)

Turns GovCon Scout from a search tool into a business system:
  leads    — every tracked opportunity, moving through pipeline stages
  searches — saved keyword searches for the daily auto-scan
  events   — the What's New feed (new leads, deadlines, scan results)

Pure stdlib sqlite3, no ORM. Every function opens/closes its own
connection so Streamlit reruns and the CLI scanner can share the file.
"""

from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "govcon.db")

STAGES = ["new", "tracking", "cost_verified", "quoted", "won", "lost", "skipped"]
STAGE_LABELS = {
    "new": "🆕 New",
    "tracking": "📌 Tracking",
    "cost_verified": "✅ Cost Verified",
    "quoted": "📤 Quoted",
    "won": "🏆 Won",
    "lost": "❌ Lost",
    "skipped": "⏭️ Skipped",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DEFAULT_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str | None = None) -> None:
    with _conn(db_path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
            notice_id     TEXT PRIMARY KEY,
            keyword       TEXT,
            title         TEXT,
            agency        TEXT,
            deadline      TEXT,
            stage         TEXT DEFAULT 'new',
            notes         TEXT DEFAULT '',
            quoted_price  REAL,
            outcome_price REAL,
            data          TEXT,
            created_at    TEXT,
            updated_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS searches (
            keyword    TEXT PRIMARY KEY,
            naics      TEXT DEFAULT '',
            active     INTEGER DEFAULT 1,
            last_run   TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT,
            type      TEXT,
            message   TEXT,
            notice_id TEXT,
            seen      INTEGER DEFAULT 0
        );
        """)
        # Migration: track who added a search (user vs the hunter agent)
        try:
            c.execute("ALTER TABLE searches ADD COLUMN source TEXT DEFAULT 'user'")
        except sqlite3.OperationalError:
            pass  # column already exists


# ── Leads ─────────────────────────────────────────────────────────────────────
def upsert_lead(lead: dict, keyword: str, db_path: str | None = None) -> bool:
    """Insert or refresh a lead. Returns True if it was NEW."""
    notice_id = lead.get("notice_id")
    if not notice_id:
        return False
    now = _now()
    with _conn(db_path) as c:
        existing = c.execute("SELECT notice_id FROM leads WHERE notice_id=?", (notice_id,)).fetchone()
        if existing:
            # Refresh volatile data but never overwrite the user's stage/notes
            c.execute(
                "UPDATE leads SET data=?, deadline=?, updated_at=? WHERE notice_id=?",
                (json.dumps(lead, default=str), lead.get("response_deadline"), now, notice_id),
            )
            return False
        c.execute(
            """INSERT INTO leads (notice_id, keyword, title, agency, deadline, stage,
                                  data, created_at, updated_at)
               VALUES (?,?,?,?,?,'new',?,?,?)""",
            (notice_id, keyword, lead.get("title"), lead.get("agency"),
             lead.get("response_deadline"), json.dumps(lead, default=str), now, now),
        )
        return True


def set_stage(notice_id: str, stage: str, quoted_price: float | None = None,
              outcome_price: float | None = None, db_path: str | None = None) -> None:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage '{stage}'. Valid: {STAGES}")
    with _conn(db_path) as c:
        c.execute("UPDATE leads SET stage=?, updated_at=? WHERE notice_id=?",
                  (stage, _now(), notice_id))
        if quoted_price is not None:
            c.execute("UPDATE leads SET quoted_price=? WHERE notice_id=?", (quoted_price, notice_id))
        if outcome_price is not None:
            c.execute("UPDATE leads SET outcome_price=? WHERE notice_id=?", (outcome_price, notice_id))


def set_notes(notice_id: str, notes: str, db_path: str | None = None) -> None:
    with _conn(db_path) as c:
        c.execute("UPDATE leads SET notes=?, updated_at=? WHERE notice_id=?",
                  (notes, _now(), notice_id))


def get_lead(notice_id: str, db_path: str | None = None) -> dict | None:
    with _conn(db_path) as c:
        row = c.execute("SELECT * FROM leads WHERE notice_id=?", (notice_id,)).fetchone()
    return _row_to_lead(row) if row else None


def get_leads(stages: list[str] | None = None, db_path: str | None = None) -> list[dict]:
    q = "SELECT * FROM leads"
    params: tuple = ()
    if stages:
        q += f" WHERE stage IN ({','.join('?' * len(stages))})"
        params = tuple(stages)
    q += " ORDER BY updated_at DESC"
    with _conn(db_path) as c:
        rows = c.execute(q, params).fetchall()
    return [_row_to_lead(r) for r in rows]


def _row_to_lead(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["data"] = json.loads(d.get("data") or "{}")
    except json.JSONDecodeError:
        d["data"] = {}
    return d


def is_tracked(notice_id: str, db_path: str | None = None) -> bool:
    with _conn(db_path) as c:
        row = c.execute("SELECT stage FROM leads WHERE notice_id=?", (notice_id,)).fetchone()
    return bool(row) and row["stage"] not in ("skipped",)


# ── Saved searches ────────────────────────────────────────────────────────────
def save_search(keyword: str, naics: str = "", db_path: str | None = None,
                source: str = "user") -> None:
    with _conn(db_path) as c:
        c.execute(
            """INSERT INTO searches (keyword, naics, active, created_at, source) VALUES (?,?,1,?,?)
               ON CONFLICT(keyword) DO UPDATE SET naics=excluded.naics, active=1""",
            (keyword.strip().lower(), naics, _now(), source),
        )


def list_searches(active_only: bool = True, db_path: str | None = None) -> list[dict]:
    q = "SELECT * FROM searches" + (" WHERE active=1" if active_only else "") + " ORDER BY created_at"
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute(q).fetchall()]


def remove_search(keyword: str, db_path: str | None = None) -> None:
    with _conn(db_path) as c:
        c.execute("UPDATE searches SET active=0 WHERE keyword=?", (keyword.strip().lower(),))


def touch_search(keyword: str, db_path: str | None = None) -> None:
    with _conn(db_path) as c:
        c.execute("UPDATE searches SET last_run=? WHERE keyword=?", (_now(), keyword.strip().lower()))


# ── Events (What's New feed) ─────────────────────────────────────────────────
def log_event(event_type: str, message: str, notice_id: str | None = None,
              db_path: str | None = None) -> None:
    with _conn(db_path) as c:
        c.execute("INSERT INTO events (ts, type, message, notice_id) VALUES (?,?,?,?)",
                  (_now(), event_type, message, notice_id))


def get_events(limit: int = 50, unseen_only: bool = False,
               db_path: str | None = None) -> list[dict]:
    q = "SELECT * FROM events" + (" WHERE seen=0" if unseen_only else "") + " ORDER BY id DESC LIMIT ?"
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute(q, (limit,)).fetchall()]


def unseen_count(db_path: str | None = None) -> int:
    with _conn(db_path) as c:
        return c.execute("SELECT COUNT(*) FROM events WHERE seen=0").fetchone()[0]


def mark_events_seen(db_path: str | None = None) -> None:
    with _conn(db_path) as c:
        c.execute("UPDATE events SET seen=1 WHERE seen=0")


# ── Stats ─────────────────────────────────────────────────────────────────────
def pipeline_stats(db_path: str | None = None) -> dict[str, Any]:
    with _conn(db_path) as c:
        by_stage = {r["stage"]: r["n"] for r in
                    c.execute("SELECT stage, COUNT(*) n FROM leads GROUP BY stage").fetchall()}
        won = c.execute("SELECT COUNT(*) n, COALESCE(SUM(outcome_price),0) rev "
                        "FROM leads WHERE stage='won'").fetchone()
        lost = c.execute("SELECT COUNT(*) FROM leads WHERE stage='lost'").fetchone()[0]
    quoted_total = won["n"] + lost
    return {
        "by_stage": by_stage,
        "total_tracked": sum(v for k, v in by_stage.items() if k != "skipped"),
        "won": won["n"],
        "lost": lost,
        "win_rate_pct": round(won["n"] / quoted_total * 100, 1) if quoted_total else None,
        "revenue_won": round(won["rev"], 2),
    }
