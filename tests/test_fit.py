"""Fit-check tests: no API calls."""
from datetime import date, datetime

import fit


def test_timestamps_always_carry_a_time_zone():
    out = fit.with_time_zones({"response_deadline": datetime(2026, 12, 18, 10, 0), "posted_date": date(2026, 11, 21)})
    assert out["response_deadline"] == "2026-12-18 10:00 US Central"


def test_public_profile_never_includes_the_api_key():
    assert "api_key" not in fit.public_profile({"tenant_id": "a", "api_key": "secret"})


def test_blockers_cap_the_score_and_verdict_follows_the_score():
    out = fit.apply_policy({"fit_score": 55, "verdict": "possible", "blockers": ["Texas-only, job is in PA"]})
    assert (out["fit_score"], out["verdict"]) == (49, "weak")
    assert fit.apply_policy({"fit_score": 80, "verdict": "possible", "blockers": []})["verdict"] == "strong"
