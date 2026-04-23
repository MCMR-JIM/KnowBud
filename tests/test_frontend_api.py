from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from src.core.enums import LearningPhase
from src.core.models import AppState, CurriculumConfig, LearningState, TopicNode, UserProfile

app_module = importlib.import_module("src.api.app")


class FakeBackend:
    def __init__(self) -> None:
        self.learning_arch_mode = "agent"
        self.state_file = Path("./state.json")
        self.log_file = Path("./decision_trace.jsonl")
        self._states: dict[str, AppState] = {}

    def _default_state(self) -> AppState:
        return AppState(
            profile=UserProfile(student_id="u1", display_name="demo", locale="zh-CN"),
            learning=LearningState(current_phase=LearningPhase.LEARNING, current_topic_id="demo_01", total_score=10),
            curriculum=CurriculumConfig(
                topics=[TopicNode(topic_id="demo_01", title="恐龙为什么会灭绝？", difficulty=1, prerequisite_ids=[], tags=[])]
            ),
        )

    def _key(self) -> str:
        return str(self.state_file)

    def load_app_state(self):
        key = self._key()
        if key not in self._states:
            self._states[key] = self._default_state()
        return self._states[key].model_copy(deep=True)

    def save_app_state(self, state):
        self._states[self._key()] = state.model_copy(deep=True)

    def evaluate_and_speak(self, user_text: str):
        state = self.load_app_state()
        state.learning.total_score += 5
        self.save_app_state(state)
        return f"测试回复:{user_text}", 5, b"abc"

    def transcribe_audio(self, _audio_bytes: bytes):
        return "语音识别结果"

    def inject_review_topic(self, topic_id: str):
        state = self.load_app_state()
        if topic_id not in state.learning.review_queue:
            state.learning.review_queue.append(topic_id)
        self.save_app_state(state)


def make_client(monkeypatch, tmp_path: Path) -> TestClient:
    backend = FakeBackend()
    manager = app_module.SessionRuntimeManager(
        root_dir=tmp_path / "api_sessions",
        backend_factory=lambda: backend,
    )

    monkeypatch.setattr(app_module, "get_backend", lambda: backend)
    monkeypatch.setattr(app_module, "get_runtime_manager", lambda: manager)
    return TestClient(app_module.app)


def test_health_and_session_lifecycle(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "1.1.0"

    created = client.post(
        "/v1/sessions",
        json={"student_id": "kid_01", "display_name": "Kid", "locale": "zh-CN"},
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]

    state = client.get(f"/v1/sessions/{session_id}/state")
    assert state.status_code == 200
    assert state.json()["profile"]["student_id"] == "kid_01"

    listed = client.get("/v1/sessions")
    assert listed.status_code == 200
    assert any(item["session_id"] == session_id for item in listed.json()["sessions"])


def test_turns_events_and_graph(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    created = client.post("/v1/sessions", json={})
    session_id = created.json()["session"]["session_id"]

    text_turn = client.post(f"/v1/sessions/{session_id}/turns/text", json={"text": "你好"})
    assert text_turn.status_code == 200
    assert text_turn.json()["turn_id"].startswith("turn_")

    audio_turn = client.post(
        f"/v1/sessions/{session_id}/turns/audio",
        files={"file": ("a.wav", b"123", "audio/wav")},
    )
    assert audio_turn.status_code == 200
    assert audio_turn.json()["recognized_text"] == "语音识别结果"

    events = client.get(f"/v1/sessions/{session_id}/events", params={"after": 0, "limit": 20})
    assert events.status_code == 200
    kinds = [event["kind"] for event in events.json()["events"]]
    assert "api_turn_completed" in kinds

    graph = client.get(f"/v1/sessions/{session_id}/graph")
    assert graph.status_code == 200
    assert len(graph.json()["topics"]) == 1


def test_review_explore_and_legacy_endpoints(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    created = client.post("/v1/sessions", json={})
    session_id = created.json()["session"]["session_id"]

    pushed = client.post(f"/v1/sessions/{session_id}/review-queue", json={"topic_id": "demo_01"})
    assert pushed.status_code == 200
    assert pushed.json()["queued"] is True

    review_queue = client.get(f"/v1/sessions/{session_id}/review-queue")
    assert review_queue.status_code == 200
    assert review_queue.json()["size"] == 1

    opened = client.post(f"/v1/sessions/{session_id}/explore-window/open", json={"minutes": 3})
    assert opened.status_code == 200
    assert opened.json()["active"] is True

    closed = client.post(f"/v1/sessions/{session_id}/explore-window/close")
    assert closed.status_code == 200
    assert closed.json()["active"] is False

    legacy_turn = client.post("/v1/session/input/text", json={"text": "你好"})
    assert legacy_turn.status_code == 200
    assert legacy_turn.json()["session_id"] == "default"

    legacy_graph = client.get("/v1/knowledge/graph")
    assert legacy_graph.status_code == 200
    assert legacy_graph.json()["session_id"] == "default"
