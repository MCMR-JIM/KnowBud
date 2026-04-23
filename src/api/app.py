from __future__ import annotations

import base64
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from fastapi import FastAPI, File, HTTPException, UploadFile

from src.api.schemas import (
    AudioTurnResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    EventInfo,
    EventListResponse,
    ExploreWindowOpenRequest,
    ExploreWindowResponse,
    HealthResponse,
    KnowledgeGraphResponse,
    MasteryInfo,
    MasteryListResponse,
    ProposalInfo,
    PushReviewRequest,
    PushReviewResponse,
    ReviewQueueResponse,
    SessionLearningState,
    SessionListResponse,
    SessionProfile,
    SessionStateResponse,
    SessionSummary,
    TextTurnRequest,
    TopicInfo,
    TurnResponse,
)
from src.core.models import LearningEvent

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend

API_VERSION = "1.1.0"
DEFAULT_SESSION_ID = "default"
TURN_EVENT_KIND = "api_turn_completed"

app = FastAPI(
    title="LoopTutor Frontend API",
    version=API_VERSION,
    description="Frontend-facing session APIs for state, turns, mastery, events, and graph lifecycle.",
)


@dataclass
class SessionRuntime:
    session_id: str
    created_at: str
    updated_at: str
    turn_count: int = 0


class SessionRuntimeManager:
    def __init__(
        self,
        *,
        root_dir: Path | None = None,
        backend_factory: Callable[[], "SessionBackend"] | None = None,
    ) -> None:
        self.root_dir = root_dir or Path(os.getenv("API_SESSION_ROOT", "./data/api_sessions"))
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._backend_factory = backend_factory or get_backend
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionRuntime] = {}

    def has_session(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions or self._state_path(session_id).exists()

    def create_session(self, profile: CreateSessionRequest | None) -> tuple[SessionRuntime, object]:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        profile = profile or CreateSessionRequest()

        def _init(backend: SessionBackend, runtime: SessionRuntime):
            state = backend.load_app_state()
            if profile.student_id:
                state.profile.student_id = profile.student_id
            if profile.display_name:
                state.profile.display_name = profile.display_name
            if profile.locale:
                state.profile.locale = profile.locale
            backend.save_app_state(state)
            runtime.turn_count = self._infer_turn_count(state)
            return state

        state, runtime = self._run_with_session(session_id, _init, auto_create=True)
        return runtime, state

    def list_sessions(self) -> list[SessionRuntime]:
        session_ids = sorted(set(self._discover_session_ids()) | set(self._sessions.keys()))
        snapshots: list[SessionRuntime] = []
        for session_id in session_ids:
            try:
                self.get_state(session_id, auto_create=False)
            except KeyError:
                continue

        with self._lock:
            for session_id in session_ids:
                runtime = self._sessions.get(session_id)
                if runtime is None:
                    continue
                snapshots.append(
                    SessionRuntime(
                        session_id=runtime.session_id,
                        created_at=runtime.created_at,
                        updated_at=runtime.updated_at,
                        turn_count=runtime.turn_count,
                    )
                )
        return snapshots

    def get_runtime(self, session_id: str) -> SessionRuntime:
        with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is None:
                raise KeyError(session_id)
            return SessionRuntime(
                session_id=runtime.session_id,
                created_at=runtime.created_at,
                updated_at=runtime.updated_at,
                turn_count=runtime.turn_count,
            )

    def get_state(self, session_id: str, *, auto_create: bool) -> object:
        def _op(backend: SessionBackend, runtime: SessionRuntime):
            state = backend.load_app_state()
            self._sync_turn_count(runtime, state)
            return state

        state, _ = self._run_with_session(session_id, _op, auto_create=auto_create)
        return state

    def submit_text_turn(
        self,
        session_id: str,
        *,
        user_text: str,
        auto_create: bool,
    ) -> tuple[str, str, int, bytes, object, int]:
        def _op(backend: SessionBackend, runtime: SessionRuntime):
            reply_text, earned_points, reply_audio = backend.evaluate_and_speak(user_text)
            state = backend.load_app_state()
            runtime.turn_count += 1
            turn_id = f"turn_{runtime.turn_count:06d}"
            self._append_api_event(
                backend,
                state,
                kind=TURN_EVENT_KIND,
                payload={
                    "turn_id": turn_id,
                    "input_mode": "text",
                    "user_text": user_text,
                    "earned_points": earned_points,
                },
            )
            events_cursor = len(state.learning.history_logs)
            return turn_id, reply_text, earned_points, reply_audio, state, events_cursor

        result, _ = self._run_with_session(session_id, _op, auto_create=auto_create)
        return result

    def submit_audio_turn(
        self,
        session_id: str,
        *,
        audio_bytes: bytes,
        auto_create: bool,
    ) -> tuple[str, str, str, int, bytes, object, int]:
        def _op(backend: SessionBackend, runtime: SessionRuntime):
            recognized_text = backend.transcribe_audio(audio_bytes)
            reply_text, earned_points, reply_audio = backend.evaluate_and_speak(recognized_text)
            state = backend.load_app_state()
            runtime.turn_count += 1
            turn_id = f"turn_{runtime.turn_count:06d}"
            self._append_api_event(
                backend,
                state,
                kind=TURN_EVENT_KIND,
                payload={
                    "turn_id": turn_id,
                    "input_mode": "audio",
                    "recognized_text": recognized_text,
                    "earned_points": earned_points,
                },
            )
            events_cursor = len(state.learning.history_logs)
            return turn_id, recognized_text, reply_text, earned_points, reply_audio, state, events_cursor

        result, _ = self._run_with_session(session_id, _op, auto_create=auto_create)
        return result

    def push_review_topic(
        self,
        session_id: str,
        *,
        topic_id: str,
        auto_create: bool,
    ) -> tuple[object, bool]:
        def _op(backend: SessionBackend, _runtime: SessionRuntime):
            backend.inject_review_topic(topic_id)
            state = backend.load_app_state()
            queued = topic_id in state.learning.review_queue
            self._append_api_event(
                backend,
                state,
                kind="review_topic_pushed",
                payload={"topic_id": topic_id, "queued": queued},
            )
            return state, queued

        result, _ = self._run_with_session(session_id, _op, auto_create=auto_create)
        return result

    def open_explore_window(
        self,
        session_id: str,
        *,
        minutes: int,
        auto_create: bool,
    ) -> object:
        def _op(backend: SessionBackend, _runtime: SessionRuntime):
            state = backend.load_app_state()
            until = datetime.now(timezone.utc) + timedelta(minutes=max(1, minutes))
            state.learning.explore_window_until = until.isoformat()
            self._append_api_event(
                backend,
                state,
                kind="explore_window_opened",
                payload={"minutes": max(1, minutes), "until": state.learning.explore_window_until},
            )
            return state

        state, _ = self._run_with_session(session_id, _op, auto_create=auto_create)
        return state

    def close_explore_window(self, session_id: str, *, auto_create: bool) -> object:
        def _op(backend: SessionBackend, _runtime: SessionRuntime):
            state = backend.load_app_state()
            state.learning.explore_window_until = None
            self._append_api_event(
                backend,
                state,
                kind="explore_window_closed",
                payload={"source": "frontend_api"},
            )
            return state

        state, _ = self._run_with_session(session_id, _op, auto_create=auto_create)
        return state

    def get_events(self, session_id: str, *, after: int, limit: int, auto_create: bool) -> tuple[object, int, int, list[object]]:
        def _op(backend: SessionBackend, _runtime: SessionRuntime):
            state = backend.load_app_state()
            events = state.learning.history_logs
            start = max(0, after)
            clipped_limit = min(max(1, limit), 200)
            sliced = events[start : start + clipped_limit]
            next_cursor = start + len(sliced)
            return state, start, next_cursor, sliced

        result, _ = self._run_with_session(session_id, _op, auto_create=auto_create)
        return result

    def _run_with_session(self, session_id: str, operation, *, auto_create: bool):
        with self._lock:
            state_path = self._state_path(session_id)
            if not auto_create and not state_path.exists() and session_id not in self._sessions:
                raise KeyError(session_id)

            runtime = self._sessions.get(session_id)
            if runtime is None:
                runtime = self._runtime_from_disk(session_id, state_path)
                self._sessions[session_id] = runtime

            backend = self._backend_factory()
            previous_state_file = backend.state_file
            previous_log_file = backend.log_file

            backend.state_file = state_path
            backend.log_file = self._log_path(session_id)
            try:
                if auto_create and not backend.state_file.exists():
                    backend.state_file.parent.mkdir(parents=True, exist_ok=True)
                    backend.save_app_state(backend.load_app_state())
                if not auto_create and not backend.state_file.exists() and session_id not in self._sessions:
                    raise KeyError(session_id)

                result = operation(backend, runtime)
                runtime.updated_at = _utc_now_iso()
                return result, runtime
            finally:
                backend.state_file = previous_state_file
                backend.log_file = previous_log_file

    def _append_api_event(self, backend: SessionBackend, state, *, kind: str, payload: dict[str, object]) -> None:
        state.learning.history_logs.append(
            LearningEvent(
                ts=_utc_now_iso(),
                kind=kind,
                payload=payload,
            )
        )
        backend.save_app_state(state)

    def _sync_turn_count(self, runtime: SessionRuntime, state) -> None:
        runtime.turn_count = max(runtime.turn_count, self._infer_turn_count(state))

    @staticmethod
    def _infer_turn_count(state) -> int:
        return sum(1 for event in state.learning.history_logs if event.kind == TURN_EVENT_KIND)

    def _runtime_from_disk(self, session_id: str, state_path: Path) -> SessionRuntime:
        if state_path.exists():
            ts = datetime.fromtimestamp(state_path.stat().st_mtime, tz=timezone.utc).isoformat()
        else:
            ts = _utc_now_iso()
        return SessionRuntime(session_id=session_id, created_at=ts, updated_at=ts, turn_count=0)

    def _session_dir(self, session_id: str) -> Path:
        return self.root_dir / session_id

    def _state_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "state.json"

    def _log_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "decision_trace.jsonl"

    def _discover_session_ids(self) -> list[str]:
        if not self.root_dir.exists():
            return []
        session_ids: list[str] = []
        for child in self.root_dir.iterdir():
            if child.is_dir() and (child / "state.json").exists():
                session_ids.append(child.name)
        return session_ids


@lru_cache(maxsize=1)
def get_backend() -> SessionBackend:
    from src.services.session_backend import SessionBackend

    return SessionBackend()


@lru_cache(maxsize=1)
def get_runtime_manager() -> SessionRuntimeManager:
    return SessionRuntimeManager()


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    backend = get_backend()
    return HealthResponse(
        ok=True,
        service="looptutor-frontend-api",
        version=API_VERSION,
        arch_mode=backend.learning_arch_mode,
    )


@app.post("/v1/sessions", response_model=CreateSessionResponse, tags=["sessions"])
def create_session(payload: CreateSessionRequest | None = None) -> CreateSessionResponse:
    manager = get_runtime_manager()
    runtime, state = manager.create_session(payload)
    return CreateSessionResponse(
        session=_session_summary(runtime),
        state=_build_state_response(session_id=runtime.session_id, state=state, runtime=runtime),
    )


@app.get("/v1/sessions", response_model=SessionListResponse, tags=["sessions"])
def list_sessions() -> SessionListResponse:
    manager = get_runtime_manager()
    sessions = [_session_summary(runtime) for runtime in manager.list_sessions()]
    return SessionListResponse(sessions=sessions)


@app.get("/v1/sessions/{session_id}/state", response_model=SessionStateResponse, tags=["sessions"])
def get_session_state_v1(session_id: str) -> SessionStateResponse:
    manager = get_runtime_manager()
    state, runtime = _load_session_or_404(manager, session_id)
    return _build_state_response(session_id=session_id, state=state, runtime=runtime)


@app.post("/v1/sessions/{session_id}/turns/text", response_model=TurnResponse, tags=["turns"])
def submit_text_turn_v1(session_id: str, payload: TextTurnRequest) -> TurnResponse:
    manager = get_runtime_manager()
    user_text = payload.text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text cannot be empty")

    try:
        turn_id, reply_text, earned_points, reply_audio, state, events_cursor = manager.submit_text_turn(
            session_id,
            user_text=user_text,
            auto_create=False,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc

    return _build_turn_response(
        session_id=session_id,
        turn_id=turn_id,
        state=state,
        user_text=user_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
        events_cursor=events_cursor,
    )


@app.post("/v1/sessions/{session_id}/turns/audio", response_model=AudioTurnResponse, tags=["turns"])
async def submit_audio_turn_v1(session_id: str, file: UploadFile = File(...)) -> AudioTurnResponse:
    manager = get_runtime_manager()
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio file is empty")

    try:
        turn_id, recognized_text, reply_text, earned_points, reply_audio, state, events_cursor = manager.submit_audio_turn(
            session_id,
            audio_bytes=audio_bytes,
            auto_create=False,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc

    base = _build_turn_response(
        session_id=session_id,
        turn_id=turn_id,
        state=state,
        user_text=recognized_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
        events_cursor=events_cursor,
    )
    return AudioTurnResponse(recognized_text=recognized_text, **base.model_dump())


@app.get("/v1/sessions/{session_id}/events", response_model=EventListResponse, tags=["events"])
def get_events(session_id: str, after: int = 0, limit: int = 50) -> EventListResponse:
    manager = get_runtime_manager()
    try:
        _state, start, next_cursor, events = manager.get_events(
            session_id,
            after=after,
            limit=limit,
            auto_create=False,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc

    event_items = [
        EventInfo(
            event_index=start + idx,
            ts=event.ts,
            kind=event.kind,
            payload=event.payload,
        )
        for idx, event in enumerate(events)
    ]
    return EventListResponse(
        session_id=session_id,
        after=max(0, after),
        next_cursor=next_cursor,
        events=event_items,
    )


@app.post("/v1/sessions/{session_id}/review-queue", response_model=PushReviewResponse, tags=["review"])
def push_review_topic_v1(session_id: str, payload: PushReviewRequest) -> PushReviewResponse:
    manager = get_runtime_manager()
    try:
        state, queued = manager.push_review_topic(
            session_id,
            topic_id=payload.topic_id,
            auto_create=False,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc

    return PushReviewResponse(
        session_id=session_id,
        queued=queued,
        topic_id=payload.topic_id,
        review_queue_size=len(state.learning.review_queue),
    )


@app.get("/v1/sessions/{session_id}/review-queue", response_model=ReviewQueueResponse, tags=["review"])
def get_review_queue(session_id: str) -> ReviewQueueResponse:
    manager = get_runtime_manager()
    state, _runtime = _load_session_or_404(manager, session_id)
    return ReviewQueueResponse(
        session_id=session_id,
        topics=list(state.learning.review_queue),
        size=len(state.learning.review_queue),
    )


@app.get("/v1/sessions/{session_id}/graph", response_model=KnowledgeGraphResponse, tags=["knowledge"])
def get_graph_v1(session_id: str) -> KnowledgeGraphResponse:
    manager = get_runtime_manager()
    state, _runtime = _load_session_or_404(manager, session_id)
    return _build_graph_response(session_id, state)


@app.get("/v1/sessions/{session_id}/mastery", response_model=MasteryListResponse, tags=["mastery"])
def get_mastery_v1(session_id: str) -> MasteryListResponse:
    manager = get_runtime_manager()
    state, _runtime = _load_session_or_404(manager, session_id)
    return MasteryListResponse(
        session_id=session_id,
        mastery=[_mastery_info(topic_id, mastery) for topic_id, mastery in state.learning.mastery_map.items()],
    )


@app.get("/v1/sessions/{session_id}/explore-window", response_model=ExploreWindowResponse, tags=["explore"])
def get_explore_window(session_id: str) -> ExploreWindowResponse:
    manager = get_runtime_manager()
    state, _runtime = _load_session_or_404(manager, session_id)
    return _build_explore_window_response(session_id, state.learning.explore_window_until)


@app.post("/v1/sessions/{session_id}/explore-window/open", response_model=ExploreWindowResponse, tags=["explore"])
def open_explore_window(session_id: str, payload: ExploreWindowOpenRequest) -> ExploreWindowResponse:
    manager = get_runtime_manager()
    try:
        state = manager.open_explore_window(session_id, minutes=payload.minutes, auto_create=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc
    return _build_explore_window_response(session_id, state.learning.explore_window_until)


@app.post("/v1/sessions/{session_id}/explore-window/close", response_model=ExploreWindowResponse, tags=["explore"])
def close_explore_window(session_id: str) -> ExploreWindowResponse:
    manager = get_runtime_manager()
    try:
        state = manager.close_explore_window(session_id, auto_create=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc
    return _build_explore_window_response(session_id, state.learning.explore_window_until)


# Backward-compatible default-session endpoints.
@app.get("/v1/session/state", response_model=SessionStateResponse, tags=["session", "legacy"])
def get_session_state() -> SessionStateResponse:
    manager = get_runtime_manager()
    state = manager.get_state(DEFAULT_SESSION_ID, auto_create=True)
    runtime = manager.get_runtime(DEFAULT_SESSION_ID)
    return _build_state_response(session_id=DEFAULT_SESSION_ID, state=state, runtime=runtime)


@app.post("/v1/session/input/text", response_model=TurnResponse, tags=["session", "legacy"])
def submit_text_turn(payload: TextTurnRequest) -> TurnResponse:
    manager = get_runtime_manager()
    user_text = payload.text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text cannot be empty")

    turn_id, reply_text, earned_points, reply_audio, state, events_cursor = manager.submit_text_turn(
        DEFAULT_SESSION_ID,
        user_text=user_text,
        auto_create=True,
    )
    return _build_turn_response(
        session_id=DEFAULT_SESSION_ID,
        turn_id=turn_id,
        state=state,
        user_text=user_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
        events_cursor=events_cursor,
    )


@app.post("/v1/session/input/audio", response_model=AudioTurnResponse, tags=["session", "legacy"])
async def submit_audio_turn(file: UploadFile = File(...)) -> AudioTurnResponse:
    manager = get_runtime_manager()
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio file is empty")

    turn_id, recognized_text, reply_text, earned_points, reply_audio, state, events_cursor = manager.submit_audio_turn(
        DEFAULT_SESSION_ID,
        audio_bytes=audio_bytes,
        auto_create=True,
    )
    base = _build_turn_response(
        session_id=DEFAULT_SESSION_ID,
        turn_id=turn_id,
        state=state,
        user_text=recognized_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
        events_cursor=events_cursor,
    )
    return AudioTurnResponse(recognized_text=recognized_text, **base.model_dump())


@app.post("/v1/session/review/push", response_model=PushReviewResponse, tags=["session", "legacy"])
def push_review_topic(payload: PushReviewRequest) -> PushReviewResponse:
    manager = get_runtime_manager()
    state, queued = manager.push_review_topic(
        DEFAULT_SESSION_ID,
        topic_id=payload.topic_id,
        auto_create=True,
    )
    return PushReviewResponse(
        session_id=DEFAULT_SESSION_ID,
        queued=queued,
        topic_id=payload.topic_id,
        review_queue_size=len(state.learning.review_queue),
    )


@app.get("/v1/knowledge/graph", response_model=KnowledgeGraphResponse, tags=["knowledge", "legacy"])
def get_knowledge_graph() -> KnowledgeGraphResponse:
    manager = get_runtime_manager()
    state = manager.get_state(DEFAULT_SESSION_ID, auto_create=True)
    return _build_graph_response(DEFAULT_SESSION_ID, state)


def _load_session_or_404(manager: SessionRuntimeManager, session_id: str) -> tuple[object, SessionRuntime]:
    try:
        state = manager.get_state(session_id, auto_create=False)
        runtime = manager.get_runtime(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc
    return state, runtime


def _session_summary(runtime: SessionRuntime) -> SessionSummary:
    return SessionSummary(
        session_id=runtime.session_id,
        created_at=runtime.created_at,
        updated_at=runtime.updated_at,
        turn_count=runtime.turn_count,
    )


def _build_graph_response(session_id: str, state) -> KnowledgeGraphResponse:
    return KnowledgeGraphResponse(
        session_id=session_id,
        topics=[_topic_info(topic) for topic in state.curriculum.topics],
        proposals=[_proposal_info(proposal) for proposal in state.learning.graph_proposals],
        mastery=[
            _mastery_info(topic_id, mastery)
            for topic_id, mastery in state.learning.mastery_map.items()
        ],
    )


def _build_state_response(*, session_id: str, state, runtime: SessionRuntime) -> SessionStateResponse:
    return SessionStateResponse(
        session_id=session_id,
        profile=SessionProfile(
            student_id=state.profile.student_id,
            display_name=state.profile.display_name,
            locale=state.profile.locale,
        ),
        learning=SessionLearningState(
            current_topic_id=state.learning.current_topic_id,
            current_phase=str(state.learning.current_phase),
            total_score=state.learning.total_score,
            consecutive_correct=state.learning.consecutive_correct,
            consecutive_wrong=state.learning.consecutive_wrong,
            explore_window_until=state.learning.explore_window_until,
            review_queue_size=len(state.learning.review_queue),
            history_event_count=len(state.learning.history_logs),
        ),
        topics=[_topic_info(topic) for topic in state.curriculum.topics],
        proposals=[_proposal_info(proposal) for proposal in state.learning.graph_proposals],
        mastery=[
            _mastery_info(topic_id, mastery)
            for topic_id, mastery in state.learning.mastery_map.items()
        ],
        turn_count=runtime.turn_count,
        events_cursor=len(state.learning.history_logs),
    )


def _build_turn_response(
    *,
    session_id: str,
    turn_id: str,
    state,
    user_text: str,
    reply_text: str,
    earned_points: int,
    reply_audio: bytes,
    events_cursor: int,
) -> TurnResponse:
    audio_base64 = base64.b64encode(reply_audio).decode("ascii") if reply_audio else None
    return TurnResponse(
        session_id=session_id,
        turn_id=turn_id,
        user_text=user_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio_base64=audio_base64,
        current_topic_id=state.learning.current_topic_id,
        current_phase=str(state.learning.current_phase),
        total_score=state.learning.total_score,
        explore_window_until=state.learning.explore_window_until,
        events_cursor=events_cursor,
    )


def _build_explore_window_response(session_id: str, until_text: str | None) -> ExploreWindowResponse:
    until = _parse_iso_ts(until_text)
    if until is None:
        return ExploreWindowResponse(
            session_id=session_id,
            explore_window_until=until_text,
            active=False,
            remaining_seconds=None,
        )

    now = datetime.now(timezone.utc)
    remaining = int((until - now).total_seconds())
    if remaining <= 0:
        return ExploreWindowResponse(
            session_id=session_id,
            explore_window_until=until_text,
            active=False,
            remaining_seconds=0,
        )
    return ExploreWindowResponse(
        session_id=session_id,
        explore_window_until=until_text,
        active=True,
        remaining_seconds=remaining,
    )


def _topic_info(topic) -> TopicInfo:
    return TopicInfo(
        topic_id=topic.topic_id,
        title=topic.title,
        difficulty=topic.difficulty,
        prerequisite_ids=list(topic.prerequisite_ids),
        tags=list(topic.tags),
    )


def _proposal_info(record) -> ProposalInfo:
    return ProposalInfo(
        proposal_id=record.proposal_id,
        title=record.title,
        trigger=record.trigger,
        status=record.status,
        reason=record.reason,
        created_topic_id=record.created_topic_id,
        updated_ts=record.updated_ts,
    )


def _mastery_info(topic_id: str, mastery) -> MasteryInfo:
    return MasteryInfo(
        topic_id=topic_id,
        depth_level=mastery.depth_level,
        stability_level=mastery.stability_level,
        success_count=mastery.success_count,
        success_streak=mastery.success_streak,
        spaced_success_count=mastery.spaced_success_count,
        last_success_ts=mastery.last_success_ts,
    )


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
