from datetime import datetime, timedelta, timezone

from src.agent.mastery_engine import MasteryEngine
from src.core.enums import LearningPhase
from src.core.models import LearningState


def test_mastery_requires_depth_application() -> None:
    state = LearningState(current_phase=LearningPhase.LEARNING, current_topic_id="t1")
    engine = MasteryEngine(spaced_gap_hours=1)

    update = engine.update_from_answer(state=state, topic_id="t1", user_text="答案是5", is_correct=True)
    assert update.mastered_now is False

    update2 = engine.update_from_answer(state=state, topic_id="t1", user_text="因为可以应用到生活场景，所以答案是5", is_correct=True)
    assert update2.mastered_now is True


def test_true_mastery_opens_reward_window_once() -> None:
    state = LearningState(current_phase=LearningPhase.LEARNING, current_topic_id="t1")
    engine = MasteryEngine(spaced_gap_hours=1)

    engine.update_from_answer(state=state, topic_id="t1", user_text="因为能应用，所以答案是5", is_correct=True)
    first = engine.update_from_answer(state=state, topic_id="t1", user_text="因为能应用，所以答案是5", is_correct=True)
    assert first.true_mastered_now is True
    assert first.should_open_explore_window is True

    second = engine.update_from_answer(state=state, topic_id="t1", user_text="因为能应用，所以答案是5", is_correct=True)
    assert second.should_open_explore_window is False


def test_spaced_success_increases_stability() -> None:
    state = LearningState(current_phase=LearningPhase.LEARNING, current_topic_id="t1")
    engine = MasteryEngine(spaced_gap_hours=1)

    engine.update_from_answer(state=state, topic_id="t1", user_text="因为能应用，所以答案是5", is_correct=True)
    node = state.mastery_map["t1"]
    node.last_success_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    engine.update_from_answer(state=state, topic_id="t1", user_text="因为能应用，所以答案是5", is_correct=True)
    assert state.mastery_map["t1"].spaced_success_count >= 1
