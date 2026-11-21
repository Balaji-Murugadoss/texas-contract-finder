"""Tool tests on a tiny fake database in a temp folder: no internet, no API key."""
from datetime import datetime, timedelta

import pytest

import app_state
import config
import db
import tools


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "contracts.duckdb")
    monkeypatch.setattr(config, "APP_DB_PATH", tmp_path / "app.sqlite")
    soon, later = datetime.now() + timedelta(days=1), datetime.now() + timedelta(days=10)
    con = db.connect()
    rows = [("sam:hvac", "sam", "HVAC repair", "238220", "Solicitation", "TX", later),
            ("sam:it", "sam", "Software build", "541511", "Solicitation", "TX", later),
            ("sam:too-soon", "sam", "HVAC due tomorrow", "238220", "Solicitation", "TX", soon),
            ("esbd:open", "esbd", "Chiller service", None, "Posted", "TX", later),
            ("esbd:closed", "esbd", "Old chiller job", None, "Closed", "TX", later)]
    for opp_id, source, title, naics, status, state, deadline in rows:
        con.execute("INSERT INTO opportunities (opp_id, source, title, naics, notice_type, state, "
                    "response_deadline, attachments_json) VALUES (?, ?, ?, ?, ?, ?, ?, '[]')",
                    [opp_id, source, title, naics, status, state, deadline])
    for opp_id in ["esbd:open", "esbd:closed"]:
        con.execute("INSERT INTO opportunity_codes VALUES (?, 'nigp', '91036', 'HVAC repair')", [opp_id])
    con.close()
    app = app_state.connect()
    for tid, naics in [("hvac", "238220"), ("data", "541511")]:
        app_state.upsert_tenant(app, tenant_id=tid, api_key=f"key-{tid}", name=tid, naics_codes=naics,
                                state="TX", certifications="", employees=5, notes="")
    app.close()


def test_search_matches_codes_status_and_lead_time(setup):
    ids = [r["opp_id"] for r in tools.search_opportunities("hvac")["results"]]
    assert sorted(ids) == ["esbd:open", "sam:hvac"]     # not other industries, closed Texas posts, or due tomorrow


def test_model_cannot_choose_the_tenant(setup):
    tools.run_tool("save_match", {"opp_id": "sam:hvac", "fit_score": 80, "reasons": "x", "tenant_id": "data"},
                   tenant_id="hvac")
    con = app_state.connect()
    assert [m["opp_id"] for m in app_state.list_matches(con, "hvac")] == ["sam:hvac"]
    assert app_state.list_matches(con, "data") == []    # the tenant_id the model sent was ignored


def test_bad_tool_calls_return_errors_not_crashes(setup):
    assert "error" in tools.run_tool("save_match", {"opp_id": "sam:made-up", "fit_score": 90, "reasons": "x"}, "hvac")
    assert "error" in tools.run_tool("delete_everything", {}, "hvac")
    assert "error" in tools.run_tool("search_opportunities", {"color": "blue"}, "hvac")


def test_model_cannot_loosen_the_lead_time_rule(setup):
    ids = [r["opp_id"] for r in tools.search_opportunities("hvac", min_days_left=0)["results"]]
    assert "sam:too-soon" not in ids                    # the model asked for 0 days; the floor of 3 still applies


def test_keywords_match_any_word_and_empty_results_come_with_a_hint(setup):
    assert [r["opp_id"] for r in tools.search_opportunities("hvac", keywords="chiller pumps")["results"]] == ["esbd:open"]
    out = tools.search_opportunities("hvac", keywords="IT software")
    assert out["results"] == [] and "Search again without keywords" in out["hint"]
