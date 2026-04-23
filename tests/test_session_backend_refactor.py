from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.models import EvaluationResult
from src.agent.orchestrator import AgentOrchestrator
from src.services.session_backend import SessionBackend


def test_backend_opens_explore_window_when_true_mastery(tmp_path: Path) -> None:
    backend = SessionBackend()
    backend.state_file = tmp_path / "state.json"
    backend.log_file = tmp_path / "decision_trace.jsonl"

    state = backend.load_app_state()
    state.learning.current_topic_id = "topic_dino"
    backend.save_app_state(state)

    backend.llm_skill.evaluate_answer = lambda **_: EvaluationResult(
        is_correct=True,
        feedback_text="回答不错",
    )
    backend.synthesize_reply_audio = lambda _: b""

    backend.evaluate_student_answer("因为能应用到新情境，所以我的答案是...")
    backend.evaluate_student_answer("因为能结合已学知识应用，所以我的答案是...")

    updated = backend.load_app_state()
    assert updated.learning.explore_window_until is not None
    assert "topic_dino" in updated.learning.mastery_map


def test_backend_closes_expired_explore_window_with_gentle_reply(tmp_path: Path) -> None:
    backend = SessionBackend()
    backend.state_file = tmp_path / "state.json"
    backend.log_file = tmp_path / "decision_trace.jsonl"
    backend.agent_orchestrator = AgentOrchestrator()
    backend.synthesize_reply_audio = lambda _: b""
    backend.evaluate_student_answer = lambda _text: ("主线继续", 5)

    state = backend.load_app_state()
    state.learning.current_topic_id = "demo_01"
    state.learning.explore_window_until = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    backend.save_app_state(state)

    reply, pts, _audio = backend._evaluate_and_speak_agent("恐龙为什么会灭绝？")
    assert "探索时间结束啦" in reply
    assert isinstance(pts, int)

    updated = backend.load_app_state()
    assert updated.learning.explore_window_until is None


def test_backend_promotes_shadow_topic_after_mastery(tmp_path: Path) -> None:
    backend = SessionBackend()
    backend.state_file = tmp_path / "state.json"
    backend.log_file = tmp_path / "decision_trace.jsonl"
    backend.agent_orchestrator = AgentOrchestrator()
    backend.synthesize_reply_audio = lambda _: b""
    backend.llm_skill.evaluate_answer = lambda **_: EvaluationResult(
        is_correct=True,
        feedback_text="回答不错",
    )

    state = backend.load_app_state()
    state.learning.current_topic_id = "shadow_node"
    state.curriculum.topics.append(
        state.curriculum.topics[0].model_copy(
            update={
                "topic_id": "shadow_node",
                "title": "黑洞形成机制",
                "tags": ["auto-proposed", "shadow"],
            }
        )
    )
    backend.save_app_state(state)

    backend.evaluate_student_answer("因为可以结合已学知识并应用到新情境，所以我这样判断")
    backend.evaluate_student_answer("因为可以结合已学知识并应用到新情境，所以我这样判断")

    updated = backend.load_app_state()
    promoted = next(t for t in updated.curriculum.topics if t.topic_id == "shadow_node")
    assert "shadow" not in promoted.tags
    assert "active" in promoted.tags
