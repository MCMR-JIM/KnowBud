from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from src.core.enums import LearningPhase
from src.core.models import AppState, CurriculumConfig, LearningState, TopicNode, UserProfile

app_module = importlib.import_module("src.api.app")


class FakeBackend:
    def __init__(self) -> None:
        self.learning_arch_mode = "agent"
        self.state = AppState(
            profile=UserProfile(student_id="u1", display_name="demo", locale="zh-CN"),
            learning=LearningState(current_phase=LearningPhase.LEARNING, current_topic_id="demo_01", total_score=10),
            curriculum=CurriculumConfig(
                topics=[TopicNode(topic_id="demo_01", title="恐龙为什么会灭绝？", difficulty=1, prerequisite_ids=[], tags=[])]
            ),
        )

    def load_app_state(self):
        return self.state

    def evaluate_and_speak(self, user_text: str):
        self.state.learning.total_score += 5
        return "测试回复", 5, b"abc"

    def transcribe_audio(self, _audio_bytes: bytes):
        return "语音识别结果"

    def inject_review_topic(self, topic_id: str):
        if topic_id not in self.state.learning.review_queue:
            self.state.learning.review_queue.append(topic_id)


def test_health_and_state_endpoints(monkeypatch) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(app_module, "get_backend", lambda: backend)
    client = TestClient(app_module.app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    state = client.get("/v1/session/state")
    assert state.status_code == 200
    assert state.json()["learning"]["current_topic_id"] == "demo_01"


def test_text_and_audio_turn_endpoints(monkeypatch) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(app_module, "get_backend", lambda: backend)
    client = TestClient(app_module.app)

    text_resp = client.post("/v1/session/input/text", json={"text": "你好"})
    assert text_resp.status_code == 200
    body = text_resp.json()
    assert body["reply_text"] == "测试回复"
    assert body["earned_points"] == 5
    assert body["reply_audio_base64"] is not None

    audio_resp = client.post(
        "/v1/session/input/audio",
        files={"file": ("a.wav", b"123", "audio/wav")},
    )
    assert audio_resp.status_code == 200
    audio_body = audio_resp.json()
    assert audio_body["recognized_text"] == "语音识别结果"


def test_review_push_and_graph_endpoints(monkeypatch) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(app_module, "get_backend", lambda: backend)
    client = TestClient(app_module.app)

    push = client.post("/v1/session/review/push", json={"topic_id": "demo_01"})
    assert push.status_code == 200
    assert push.json()["queued"] is True

    graph = client.get("/v1/knowledge/graph")
    assert graph.status_code == 200
    assert len(graph.json()["topics"]) == 1
