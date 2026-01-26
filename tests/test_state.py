import json

from agent.state import make_state


def test_state_bucketing_stable_bounds():
    state = make_state(1.0, 0.0, 0.0, "NEUTRAL", 60.0)
    data = json.loads(state)
    assert data["my"] >= 0
    assert data["enemy"] >= 0
    assert data["time"] >= 0
