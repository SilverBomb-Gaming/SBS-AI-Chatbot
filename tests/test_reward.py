from agent.reward import compute_reward, net_advantage


def test_reward_positive_when_enemy_takes_damage():
    reward, delta_enemy, delta_me = compute_reward(
        enemy_prev=1.0, enemy_now=0.9, me_prev=1.0, me_now=1.0, idle_penalty=0.0
    )
    assert delta_enemy > 0
    assert delta_me == 0
    assert reward > 0


def test_reward_negative_when_self_takes_damage():
    reward, delta_enemy, delta_me = compute_reward(
        enemy_prev=1.0, enemy_now=1.0, me_prev=1.0, me_now=0.9, idle_penalty=0.0
    )
    assert delta_enemy == 0
    assert delta_me > 0
    assert reward < 0


def test_net_advantage_sign():
    assert net_advantage(enemy_start=1.0, enemy_end=0.8, me_start=1.0, me_end=0.9) > 0
