from agent.q_learner import QLearner


def test_q_update_increases_for_positive_reward():
    learner = QLearner(alpha=0.5, gamma=0.9, epsilon=0.0)
    state = "s1"
    next_state = "s2"
    actions = ["A", "B"]
    learner.update(state, "A", reward=1.0, next_state=next_state, legal_actions=actions)
    assert learner.q_table[state]["A"] > 0.0


def test_epsilon_greedy_returns_valid_action():
    learner = QLearner(epsilon=0.0)
    state = "s1"
    actions = ["A", "B", "C"]
    action = learner.select_action(state, actions)
    assert action in actions
