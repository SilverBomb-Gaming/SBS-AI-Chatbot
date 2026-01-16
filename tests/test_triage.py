from core.triage import analyze_ticket


def test_triage_detects_outage():
    result = analyze_ticket("Login outage", "Users report outage in auth")
    assert result.category == "incident"
    assert result.priority in {"high", "critical"}
    assert "outage" in result.matched_keywords


def test_triage_handles_empty_input():
    result = analyze_ticket("", "")
    assert result.category == "general"
    assert result.priority == "low"
    assert result.confidence == 0.2
