from src.agent.policy import AgentPolicyConfig


def test_agent_policy_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TOPIC_INERTIA_BONUS", "0.2")
    monkeypatch.setenv("TOPIC_SWITCH_MARGIN", "0.33")
    monkeypatch.setenv("TOPIC_MIN_SCORE", "0.4")
    monkeypatch.setenv("PREREQ_UNLOCK_DEPTH", "2")
    monkeypatch.setenv("LOCKED_TOPIC_PENALTY", "0.5")
    monkeypatch.setenv("EXPLORE_WINDOW_MINUTES", "7")
    monkeypatch.setenv("SHADOW_PROMOTE_DEPTH", "3")
    monkeypatch.setenv("SHADOW_PROMOTE_SUCCESS_COUNT", "4")
    monkeypatch.setenv("SHADOW_PROMOTE_STABILITY", "2")
    monkeypatch.setenv("ALLOW_CROSS_SUBJECT_REQUIRES", "true")

    cfg = AgentPolicyConfig.from_env()
    assert cfg.inertia_bonus == 0.2
    assert cfg.switch_margin == 0.33
    assert cfg.min_score == 0.4
    assert cfg.unlock_depth_threshold == 2
    assert cfg.locked_topic_penalty == 0.5
    assert cfg.explore_window_minutes == 7
    assert cfg.shadow_promote_depth == 3
    assert cfg.shadow_promote_success_count == 4
    assert cfg.shadow_promote_stability == 2
    assert cfg.allow_cross_subject_requires is True
