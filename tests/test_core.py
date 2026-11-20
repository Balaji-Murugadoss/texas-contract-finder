"""Tests that need no internet and no API keys. Run:  pytest -q"""
import pytest

import app_state
import db
import sam


def test_sam_normalize_handles_missing_fields():
    row = sam.normalize({"noticeId": "abc123", "title": "HVAC repair", "naicsCode": "238220",
                         "responseDeadLine": "2026-12-05T15:00:00-06:00"})
    assert row["opp_id"] == "sam:abc123"
    assert row["state"] is None                       # missing placeOfPerformance must not crash
    assert row["response_deadline"].day == 5


def test_deadline_converted_to_central_time():
    assert sam._parse_dt("2026-12-18T11:00:00-05:00").hour == 10   # 11 Eastern = 10 Central


def test_cache_key_never_contains_api_key():
    a = sam._cache_key({"ncode": "238220", "api_key": "secret-1"})
    b = sam._cache_key({"ncode": "238220", "api_key": "secret-2"})
    assert a == b


def test_budget_stops_calls(monkeypatch):
    monkeypatch.setattr(sam.config, "SAM_DAILY_BUDGET", 2)
    con = db.connect(path=":memory:")
    sam._use_budget(con)
    sam._use_budget(con)
    with pytest.raises(sam.BudgetExceeded):
        sam._use_budget(con)


def test_load_is_idempotent():
    con = db.connect(path=":memory:")
    data = {"opportunitiesData": [{"noticeId": "n1", "title": "A"}, {"noticeId": "n2", "title": "B"}]}
    sam.load(con, data)
    sam.load(con, data)                               # running twice must not duplicate
    assert con.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 2


def test_tenant_isolation():
    con = app_state.connect(path=":memory:")
    for tid in ["a", "b"]:
        app_state.upsert_tenant(con, tenant_id=tid, api_key=f"key-{tid}", name=tid, naics_codes="238220",
                                state="TX", certifications="", employees=1, notes="")
    app_state.save_match(con, "a", "sam:1", 80, "good fit")
    assert app_state.list_matches(con, "b") == []      # tenant b must never see tenant a's data
    assert app_state.tenant_for_api_key(con, "key-a")["tenant_id"] == "a"
