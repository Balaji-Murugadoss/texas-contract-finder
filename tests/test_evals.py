"""The eval rules themselves need tests: a broken checker gives you a fake pass rate."""
import evals


def test_rules_read_the_answer_and_the_steps():
    out = {"answer": "See https://sam.gov/a and https://www.txsmartbuy.gov/esbd/X. Verdict: weak.",
           "steps": [{"tool": "search_opportunities", "args": {}}, {"tool": "check_fit", "args": {"opp_id": "x"}}]}
    assert evals.check({"type": "min_links", "min": 2}, out)
    assert evals.check({"type": "searched_broadly"}, out)
    assert not evals.check({"type": "tool_count", "tool": "check_fit", "min": 2}, out)
    assert not evals.check({"type": "refuses"}, out)              # it used tools, so it did not refuse


def test_curly_apostrophes_count_as_straight_ones():
    out = {"answer": "Sorry, I can\u2019t help with that here.", "steps": []}
    assert evals.check({"type": "refuses"}, out)                  # the model writes ’ , the checker looked for '
