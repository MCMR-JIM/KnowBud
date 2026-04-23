from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from src.core.enums import LearningPhase
from src.core.models import AppState, CurriculumConfig, LearningEvent, LearningState, TopicNode, UserProfile

app_module = importlib.import_module("src.api.app")


class FakeBackend:
    def __init__(self) -> None:
        self.learning_arch_mode = "agent"
        self.state_file = Path("./state.json")
        self.log_file = Path("./decision_trace.jsonl")
        self._state = AppState(
            profile=UserProfile(student_id="u1", display_name="demo", locale="zh-CN"),
            learning=LearningState(current_phase=LearningPhase.LEARNING, current_topic_id="demo_01", total_score=10),
            curriculum=CurriculumConfig(
                topics=[TopicNode(topic_id="demo_01", title="恐龙为什么会灭绝？", difficulty=1, prerequisite_ids=[], tags=[])]
            ),
        )
        self._events: list[LearningEvent] = []

    def load_app_state(self, *, include_history: bool = True, history_limit: int | None = None):
        state = self._state.model_copy(deep=True)
        if include_history:
            logs = self._events
            if history_limit is not None:
                logs = logs[-history_limit:]
            state.learning.history_logs = [event.model_copy(deep=True) for event in logs]
        else:
            state.learning.history_logs = []
        return state

    def save_app_state(self, state):
        state_copy = state.model_copy(deep=True)
        state_copy.learning.history_logs = []
        self._state = state_copy

    def evaluate_and_speak(self, user_text: str):
        self._state.learning.total_score += 5
        return f"测试回复:{user_text}", 5, b"abc"

    def evaluate_text_turn(self, user_text: str):
        self._state.learning.total_score += 5
        return f"测试回复:{user_text}", 5

    def transcribe_audio(self, _audio_bytes: bytes):
        return "语音识别结果"

    async def synthesize_reply_audio_stream(self, text: str, *, stop_signal):
        if stop_signal.is_set():
            return
        yield f"stream:{text}".encode("utf-8")

    def inject_review_topic(self, topic_id: str):
        if topic_id not in self._state.learning.review_queue:
            self._state.learning.review_queue.append(topic_id)

    def force_close_explore_window(self, *, source: str):
        self._state.learning.explore_window_until = None
        self._state.learning.explore_window_cooldown_until = "2026-01-01T00:10:00+00:00"
        return self.load_app_state(include_history=False)

    def append_learning_event(self, *, kind: str, payload: dict[str, object], audio_file_path: str | None = None) -> int:
        event = LearningEvent(ts="2026-01-01T00:00:00+00:00", kind=kind, payload=payload, audio_file_path=audio_file_path)
        self._events.append(event)
        return len(self._events)

    def get_learning_events(self, *, after: int, limit: int):
        start = max(0, after)
        capped = min(max(1, limit), 200)
        selected = self._events[start : start + capped]
        next_cursor = start + len(selected)
        return start, next_cursor, [event.model_copy(deep=True) for event in selected]

    def get_learning_event_count(self, *, kind: str | None = None) -> int:
        if kind is None:
            return len(self._events)
        return sum(1 for event in self._events if event.kind == kind)


def make_client(monkeypatch) -> TestClient:
    backend = FakeBackend()
    runtime = app_module.SingleSessionRuntime(backend_factory=lambda: backend)

    monkeypatch.setattr(app_module, "get_backend", lambda: backend)
    monkeypatch.setattr(app_module, "get_runtime", lambda: runtime)
    monkeypatch.setattr(app_module, "get_max_text_chars", lambda: 128)
    monkeypatch.setattr(app_module, "get_max_audio_bytes", lambda: 1024 * 1024)
    return TestClient(app_module.app)


def test_health_and_single_session_state(monkeypatch) -> None:
    client = make_client(monkeypatch)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "1.3.0"

    state = client.get("/v1/session/state")
    assert state.status_code == 200
    assert state.json()["session_id"] == "default"
    assert state.json()["learning"]["current_topic_id"] == "demo_01"


def test_turns_events_and_constraints(monkeypatch) -> None:
    client = make_client(monkeypatch)

    too_long = client.post("/v1/session/input/text", json={"text": "a" * 129})
    assert too_long.status_code == 400

    text_turn = client.post("/v1/session/input/text", json={"text": "你好"})
    assert text_turn.status_code == 200
    assert text_turn.json()["turn_id"].startswith("turn_")

    audio_turn = client.post(
        "/v1/session/input/audio",
        files={"file": ("a.wav", b"123", "audio/wav")},
    )
    assert audio_turn.status_code == 200
    assert audio_turn.json()["recognized_text"] == "语音识别结果"

    sentence_audio = client.post(
        "/v1/session/input/audio/sentence",
        files={"file": ("b.wav", b"456", "audio/wav")},
    )
    assert sentence_audio.status_code == 200

    events = client.get("/v1/session/events", params={"after": 0, "limit": 20})
    assert events.status_code == 200
    kinds = [event["kind"] for event in events.json()["events"]]
    assert "api_turn_completed" in kinds


def test_realtime_stream_and_review_explore(monkeypatch) -> None:
    client = make_client(monkeypatch)

    init_stream = client.post("/v1/session/input/text/realtime", json={"text": "讲一下黑洞"})
    assert init_stream.status_code == 200
    stream_id = init_stream.json()["stream_id"]

    stream_resp = client.get(f"/v1/session/output/audio/stream/{stream_id}")
    assert stream_resp.status_code == 200
    assert stream_resp.content.startswith(b"stream:")

    interrupt = client.post(f"/v1/session/output/audio/interrupt/{stream_id}")
    assert interrupt.status_code == 200
    assert interrupt.json()["interrupted"] in {True, False}

    pushed = client.post("/v1/session/review/push", json={"topic_id": "demo_01"})
    assert pushed.status_code == 200
    assert pushed.json()["queued"] is True

    opened = client.post("/v1/session/explore-window/open", json={"minutes": 3})
    assert opened.status_code == 200
    assert opened.json()["active"] is True

    closed = client.post("/v1/session/explore-window/close")
    assert closed.status_code == 200
    assert closed.json()["active"] is False
    assert closed.json()["cooldown_until"] is not None

    compat = client.get("/v1/sessions/default/state")
    assert compat.status_code == 200

    wrong_session = client.get("/v1/sessions/sess_x/state")
    assert wrong_session.status_code == 404
