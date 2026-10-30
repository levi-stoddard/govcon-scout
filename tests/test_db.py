"""Persistence layer tests — temp database, no side effects."""
import os

import pytest

import db


@pytest.fixture
def tmp_db(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


def make_lead(nid="L1", **over):
    lead = {"notice_id": nid, "title": "Nitrile Gloves", "agency": "DLA",
            "response_deadline": "2099-01-01", "recommended_max_bid_usd": 98.67}
    lead.update(over)
    return lead


def test_upsert_new_then_refresh(tmp_db):
    assert db.upsert_lead(make_lead(), "gloves", tmp_db) is True
    # second upsert = refresh, not new
    assert db.upsert_lead(make_lead(title="Updated"), "gloves", tmp_db) is False
    lead = db.get_lead("L1", tmp_db)
    assert lead["data"]["title"] == "Updated"
    assert lead["stage"] == "new"


def test_stage_progression_and_user_data_survives_refresh(tmp_db):
    db.upsert_lead(make_lead(), "gloves", tmp_db)
    db.set_stage("L1", "quoted", quoted_price=95.0, db_path=tmp_db)
    db.set_notes("L1", "called supplier, confirmed $60", tmp_db)
    # a daily rescan must NOT clobber stage/notes
    db.upsert_lead(make_lead(), "gloves", tmp_db)
    lead = db.get_lead("L1", tmp_db)
    assert lead["stage"] == "quoted"
    assert lead["quoted_price"] == 95.0
    assert "supplier" in lead["notes"]


def test_invalid_stage_rejected(tmp_db):
    db.upsert_lead(make_lead(), "gloves", tmp_db)
    with pytest.raises(ValueError):
        db.set_stage("L1", "bogus", db_path=tmp_db)


def test_win_loss_stats(tmp_db):
    for i, stage in enumerate(["won", "won", "lost", "tracking"]):
        db.upsert_lead(make_lead(nid=f"L{i}"), "gloves", tmp_db)
        db.set_stage(f"L{i}", stage,
                     outcome_price=1000.0 if stage == "won" else None, db_path=tmp_db)
    stats = db.pipeline_stats(tmp_db)
    assert stats["won"] == 2
    assert stats["lost"] == 1
    assert stats["win_rate_pct"] == 66.7
    assert stats["revenue_won"] == 2000.0


def test_saved_searches_roundtrip(tmp_db):
    db.save_search("Nitrile Gloves", "325612", tmp_db)
    db.save_search("hand tools", db_path=tmp_db)
    searches = db.list_searches(db_path=tmp_db)
    assert {s["keyword"] for s in searches} == {"nitrile gloves", "hand tools"}
    db.remove_search("hand tools", tmp_db)
    assert {s["keyword"] for s in db.list_searches(db_path=tmp_db)} == {"nitrile gloves"}


def test_events_feed_and_badge(tmp_db):
    db.log_event("new_lead", "Found: gloves RFQ", "L1", tmp_db)
    db.log_event("deadline", "3 days left on L1", "L1", tmp_db)
    assert db.unseen_count(tmp_db) == 2
    events = db.get_events(db_path=tmp_db)
    assert events[0]["type"] == "deadline"  # newest first
    db.mark_events_seen(tmp_db)
    assert db.unseen_count(tmp_db) == 0
