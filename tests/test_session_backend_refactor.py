from pathlib import Path

from src.core.models import EvaluationResult
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
