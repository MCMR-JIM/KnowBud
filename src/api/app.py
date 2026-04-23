from __future__ import annotations

import base64
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import TYPE_CHECKING, AsyncIterator, Callable

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

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
    StreamInterruptResponse,
    StreamTurnInitResponse,
    TextTurnRequest,
    TopicInfo,
    TurnResponse,
)

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend

API_VERSION = "1.3.0"
SINGLE_SESSION_ID = "default"
TURN_EVENT_KIND = "api_turn_completed"

app = FastAPI(
    title="LoopTutor Frontend API",
    version=API_VERSION,
    description="Single-session frontend APIs with transactional state storage and on-demand memory retrieval.",
)


@dataclass
class StreamJob:
    stream_id: str
    text: str
    stop_signal: threading.Event


class SingleSessionRuntime:
    def __init__(self, backend_factory: Callable[[], "SessionBackend"] | None = None) -> None:
        self._backend_factory = backend_factory or get_backend
        self._lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._stream_jobs: dict[str, StreamJob] = {}

    def load_state(self):
        backend = self._backend_factory()
        return backend.load_app_state(include_history=False)

    def turn_count(self) -> int:
        backend = self._backend_factory()
        return backend.get_learning_event_count(kind=TURN_EVENT_KIND)

    def events_cursor(self) -> int:
        backend = self._backend_factory()
        return backend.get_learning_event_count()

    def submit_text_turn(self, user_text: str) -> tuple[str, str, int, bytes, object, int]:
        backend = self._backend_factory()
        with self._lock:
            turn_id = self._next_turn_id(backend)
            reply_text, earned_points, reply_audio = backend.evaluate_and_speak(user_text)
            state = backend.load_app_state(include_history=False)
            backend.append_learning_event(
                kind=TURN_EVENT_KIND,
                payload={
                    "turn_id": turn_id,
                    "input_mode": "text",
                    "user_text": user_text,
                    "earned_points": earned_points,
                },
            )
            cursor = backend.get_learning_event_count()
            return turn_id, reply_text, earned_points, reply_audio, state, cursor

    def submit_audio_turn(self, audio_bytes: bytes) -> tuple[str, str, str, int, bytes, object, int]:
        backend = self._backend_factory()
        with self._lock:
            turn_id = self._next_turn_id(backend)
            recognized_text = backend.transcribe_audio(audio_bytes)
            reply_text, earned_points, reply_audio = backend.evaluate_and_speak(recognized_text)
            state = backend.load_app_state(include_history=False)
            backend.append_learning_event(
                kind=TURN_EVENT_KIND,
                payload={
                    "turn_id": turn_id,
                    "input_mode": "audio",
                    "recognized_text": recognized_text,
                    "earned_points": earned_points,
                },
            )
            cursor = backend.get_learning_event_count()
            return turn_id, recognized_text, reply_text, earned_points, reply_audio, state, cursor

    def init_stream_turn(self, user_text: str) -> tuple[StreamJob, str, str, int, object, int]:
        backend = self._backend_factory()
        with self._lock:
            turn_id = self._next_turn_id(backend)
            reply_text, earned_points = backend.evaluate_text_turn(user_text)
            state = backend.load_app_state(include_history=False)

            stream_id = f"stream_{uuid.uuid4().hex[:12]}"
            job = StreamJob(stream_id=stream_id, text=reply_text, stop_signal=threading.Event())
            with self._stream_lock:
                self._stream_jobs[stream_id] = job

            backend.append_learning_event(
                kind=TURN_EVENT_KIND,
                payload={
                    "turn_id": turn_id,
                    "input_mode": "text",
                    "audio_mode": "stream",
                    "user_text": user_text,
                    "earned_points": earned_points,
                    "stream_id": stream_id,
                },
            )
            cursor = backend.get_learning_event_count()
            return job, turn_id, reply_text, earned_points, state, cursor

    def get_stream_job(self, stream_id: str) -> StreamJob:
        with self._stream_lock:
            job = self._stream_jobs.get(stream_id)
            if job is None:
                raise KeyError(stream_id)
            return job

    def consume_stream_job(self, stream_id: str) -> None:
        with self._stream_lock:
            self._stream_jobs.pop(stream_id, None)

    def interrupt_stream(self, stream_id: str) -> bool:
        with self._stream_lock:
            job = self._stream_jobs.get(stream_id)
            if job is None:
                return False
            job.stop_signal.set()
            return True

    def push_review_topic(self, topic_id: str) -> tuple[object, bool]:
        backend = self._backend_factory()
        with self._lock:
            backend.inject_review_topic(topic_id)
            state = backend.load_app_state(include_history=False)
            queued = topic_id in state.learning.review_queue
            backend.append_learning_event(
                kind="review_topic_pushed",
                payload={"topic_id": topic_id, "queued": queued},
            )
            return state, queued

    def open_explore_window(self, minutes: int):
        backend = self._backend_factory()
        with self._lock:
            state = backend.load_app_state(include_history=False)
            cooldown_until = _parse_iso_ts(state.learning.explore_window_cooldown_until)
            if cooldown_until and cooldown_until > datetime.now(timezone.utc):
                backend.append_learning_event(
                    kind="explore_window_open_blocked",
                    payload={
                        "reason": "cooldown_active",
                        "cooldown_until": state.learning.explore_window_cooldown_until,
                    },
                )
                return state

            until = datetime.now(timezone.utc).timestamp() + (max(1, minutes) * 60)
            state.learning.explore_window_until = datetime.fromtimestamp(until, tz=timezone.utc).isoformat()
            state.learning.explore_window_cooldown_until = None
            backend.save_app_state(state)
            backend.append_learning_event(
                kind="explore_window_opened",
                payload={"minutes": max(1, minutes), "until": state.learning.explore_window_until},
            )
            return state

    def close_explore_window(self):
        backend = self._backend_factory()
        with self._lock:
            state = backend.force_close_explore_window(source="frontend_api")
            return state

    def get_events(self, *, after: int, limit: int) -> tuple[int, int, list[object]]:
        backend = self._backend_factory()
        start, next_cursor, events = backend.get_learning_events(after=after, limit=limit)
        return start, next_cursor, events

    @staticmethod
    def _next_turn_id(backend: "SessionBackend") -> str:
        next_turn = backend.get_learning_event_count(kind=TURN_EVENT_KIND) + 1
        return f"turn_{next_turn:06d}"


@lru_cache(maxsize=1)
def get_backend() -> "SessionBackend":
    from src.services.session_backend import SessionBackend

    return SessionBackend()


@lru_cache(maxsize=1)
def get_runtime() -> SingleSessionRuntime:
    return SingleSessionRuntime()


@lru_cache(maxsize=1)
def get_max_text_chars() -> int:
    raw = os.getenv("API_TEXT_MAX_CHARS", "128").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 128
    return max(1, min(8192, value))


@lru_cache(maxsize=1)
def get_max_audio_bytes() -> int:
    raw = os.getenv("API_AUDIO_MAX_BYTES", "5242880").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 5242880
    return max(1024, min(25 * 1024 * 1024, value))


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    backend = get_backend()
    return HealthResponse(
        ok=True,
        service="looptutor-frontend-api",
        version=API_VERSION,
        arch_mode=backend.learning_arch_mode,
    )


@app.get("/v1/session/state", response_model=SessionStateResponse, tags=["session"])
def get_session_state() -> SessionStateResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return _build_state_response(state=state, turn_count=runtime.turn_count(), events_cursor=runtime.events_cursor())


@app.post("/v1/session/input/text", response_model=TurnResponse, tags=["session"])
def submit_text_turn(payload: TextTurnRequest) -> TurnResponse:
    user_text = payload.text.strip()
    _validate_text(user_text)
    runtime = get_runtime()
    turn_id, reply_text, earned_points, reply_audio, state, cursor = runtime.submit_text_turn(user_text)
    return _build_turn_response(
        turn_id=turn_id,
        state=state,
        user_text=user_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
        events_cursor=cursor,
    )


@app.post("/v1/session/input/audio", response_model=AudioTurnResponse, tags=["session"])
async def submit_audio_turn(file: UploadFile = File(...)) -> AudioTurnResponse:
    audio_bytes = await file.read()
    _validate_audio(audio_bytes)
    runtime = get_runtime()
    turn_id, recognized_text, reply_text, earned_points, reply_audio, state, cursor = runtime.submit_audio_turn(audio_bytes)
    base = _build_turn_response(
        turn_id=turn_id,
        state=state,
        user_text=recognized_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
        events_cursor=cursor,
    )
    return AudioTurnResponse(recognized_text=recognized_text, **base.model_dump())


@app.post("/v1/session/input/audio/sentence", response_model=AudioTurnResponse, tags=["session", "realtime"])
async def submit_audio_sentence(file: UploadFile = File(...)) -> AudioTurnResponse:
    return await submit_audio_turn(file)


@app.post("/v1/session/input/text/realtime", response_model=StreamTurnInitResponse, tags=["session", "realtime"])
def submit_text_turn_realtime(payload: TextTurnRequest) -> StreamTurnInitResponse:
    user_text = payload.text.strip()
    _validate_text(user_text)
    runtime = get_runtime()
    job, turn_id, reply_text, earned_points, state, cursor = runtime.init_stream_turn(user_text)
    return StreamTurnInitResponse(
        session_id=SINGLE_SESSION_ID,
        turn_id=turn_id,
        reply_text=reply_text,
        earned_points=earned_points,
        current_topic_id=state.learning.current_topic_id,
        current_phase=str(state.learning.current_phase),
        total_score=state.learning.total_score,
        explore_window_until=state.learning.explore_window_until,
        stream_id=job.stream_id,
        events_cursor=cursor,
    )


@app.get("/v1/session/output/audio/stream/{stream_id}", tags=["session", "realtime"])
async def stream_reply_audio(stream_id: str):
    runtime = get_runtime()
    backend = get_backend()
    try:
        job = runtime.get_stream_job(stream_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"stream not found: {stream_id}") from exc

    async def _iterator() -> AsyncIterator[bytes]:
        try:
            async for chunk in backend.synthesize_reply_audio_stream(job.text, stop_signal=job.stop_signal):
                if job.stop_signal.is_set():
                    break
                yield chunk
        finally:
            runtime.consume_stream_job(stream_id)

    return StreamingResponse(_iterator(), media_type="audio/mpeg")


@app.post(
    "/v1/session/output/audio/interrupt/{stream_id}",
    response_model=StreamInterruptResponse,
    tags=["session", "realtime"],
)
def interrupt_stream(stream_id: str) -> StreamInterruptResponse:
    runtime = get_runtime()
    interrupted = runtime.interrupt_stream(stream_id)
    return StreamInterruptResponse(
        session_id=SINGLE_SESSION_ID,
        stream_id=stream_id,
        interrupted=interrupted,
    )


@app.get("/v1/session/events", response_model=EventListResponse, tags=["session"])
def get_events(after: int = 0, limit: int = 50) -> EventListResponse:
    runtime = get_runtime()
    start, next_cursor, events = runtime.get_events(after=after, limit=limit)
    items = [
        EventInfo(
            event_index=start + idx + 1,
            ts=event.ts,
            kind=event.kind,
            payload=event.payload,
        )
        for idx, event in enumerate(events)
    ]
    return EventListResponse(
        session_id=SINGLE_SESSION_ID,
        after=max(0, after),
        next_cursor=next_cursor,
        events=items,
    )


@app.post("/v1/session/review/push", response_model=PushReviewResponse, tags=["session"])
def push_review_topic(payload: PushReviewRequest) -> PushReviewResponse:
    runtime = get_runtime()
    state, queued = runtime.push_review_topic(payload.topic_id)
    return PushReviewResponse(
        session_id=SINGLE_SESSION_ID,
        queued=queued,
        topic_id=payload.topic_id,
        review_queue_size=len(state.learning.review_queue),
    )


@app.get("/v1/session/review-queue", response_model=ReviewQueueResponse, tags=["session"])
def get_review_queue() -> ReviewQueueResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return ReviewQueueResponse(
        session_id=SINGLE_SESSION_ID,
        topics=list(state.learning.review_queue),
        size=len(state.learning.review_queue),
    )


@app.get("/v1/knowledge/graph", response_model=KnowledgeGraphResponse, tags=["knowledge"])
def get_knowledge_graph() -> KnowledgeGraphResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return _build_graph_response(state)


@app.get("/v1/session/mastery", response_model=MasteryListResponse, tags=["session"])
def get_mastery() -> MasteryListResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return MasteryListResponse(
        session_id=SINGLE_SESSION_ID,
        mastery=[_mastery_info(topic_id, mastery) for topic_id, mastery in state.learning.mastery_map.items()],
    )


@app.get("/v1/session/explore-window", response_model=ExploreWindowResponse, tags=["session"])
def get_explore_window() -> ExploreWindowResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return _build_explore_window_response(
        until_text=state.learning.explore_window_until,
        cooldown_text=state.learning.explore_window_cooldown_until,
    )


@app.post("/v1/session/explore-window/open", response_model=ExploreWindowResponse, tags=["session"])
def open_explore_window(payload: ExploreWindowOpenRequest) -> ExploreWindowResponse:
    runtime = get_runtime()
    state = runtime.open_explore_window(payload.minutes)
    return _build_explore_window_response(
        until_text=state.learning.explore_window_until,
        cooldown_text=state.learning.explore_window_cooldown_until,
    )


@app.post("/v1/session/explore-window/close", response_model=ExploreWindowResponse, tags=["session"])
def close_explore_window() -> ExploreWindowResponse:
    runtime = get_runtime()
    state = runtime.close_explore_window()
    return _build_explore_window_response(
        until_text=state.learning.explore_window_until,
        cooldown_text=state.learning.explore_window_cooldown_until,
    )


# Compatibility wrappers: keep /v1/sessions/* but bind to single default session.
@app.post("/v1/sessions", response_model=CreateSessionResponse, tags=["sessions", "compat"])
def create_session_compat(payload: CreateSessionRequest | None = None) -> CreateSessionResponse:
    runtime = get_runtime()
    backend = get_backend()
    with runtime._lock:
        state = runtime.load_state()
        if payload:
            if payload.student_id:
                state.profile.student_id = payload.student_id
            if payload.display_name:
                state.profile.display_name = payload.display_name
            if payload.locale:
                state.profile.locale = payload.locale
            backend.save_app_state(state)
            state = backend.load_app_state(include_history=False)

    summary = _build_session_summary(turn_count=runtime.turn_count())
    state_resp = _build_state_response(state=state, turn_count=runtime.turn_count(), events_cursor=runtime.events_cursor())
    return CreateSessionResponse(session=summary, state=state_resp)


@app.get("/v1/sessions", response_model=SessionListResponse, tags=["sessions", "compat"])
def list_sessions_compat() -> SessionListResponse:
    runtime = get_runtime()
    return SessionListResponse(sessions=[_build_session_summary(turn_count=runtime.turn_count())])


@app.get("/v1/sessions/{session_id}/state", response_model=SessionStateResponse, tags=["sessions", "compat"])
def get_session_state_compat(session_id: str) -> SessionStateResponse:
    _ensure_default_session(session_id)
    return get_session_state()


@app.post("/v1/sessions/{session_id}/turns/text", response_model=TurnResponse, tags=["turns", "compat"])
def submit_text_turn_compat(session_id: str, payload: TextTurnRequest) -> TurnResponse:
    _ensure_default_session(session_id)
    return submit_text_turn(payload)


@app.post("/v1/sessions/{session_id}/turns/audio", response_model=AudioTurnResponse, tags=["turns", "compat"])
async def submit_audio_turn_compat(session_id: str, file: UploadFile = File(...)) -> AudioTurnResponse:
    _ensure_default_session(session_id)
    return await submit_audio_turn(file)


@app.get("/v1/sessions/{session_id}/events", response_model=EventListResponse, tags=["events", "compat"])
def get_events_compat(session_id: str, after: int = 0, limit: int = 50) -> EventListResponse:
    _ensure_default_session(session_id)
    return get_events(after=after, limit=limit)


@app.post("/v1/sessions/{session_id}/review-queue", response_model=PushReviewResponse, tags=["review", "compat"])
def push_review_topic_compat(session_id: str, payload: PushReviewRequest) -> PushReviewResponse:
    _ensure_default_session(session_id)
    return push_review_topic(payload)


@app.get("/v1/sessions/{session_id}/review-queue", response_model=ReviewQueueResponse, tags=["review", "compat"])
def get_review_queue_compat(session_id: str) -> ReviewQueueResponse:
    _ensure_default_session(session_id)
    return get_review_queue()


@app.get("/v1/sessions/{session_id}/graph", response_model=KnowledgeGraphResponse, tags=["knowledge", "compat"])
def get_graph_compat(session_id: str) -> KnowledgeGraphResponse:
    _ensure_default_session(session_id)
    return get_knowledge_graph()


@app.get("/v1/sessions/{session_id}/mastery", response_model=MasteryListResponse, tags=["mastery", "compat"])
def get_mastery_compat(session_id: str) -> MasteryListResponse:
    _ensure_default_session(session_id)
    return get_mastery()


@app.get("/v1/sessions/{session_id}/explore-window", response_model=ExploreWindowResponse, tags=["explore", "compat"])
def get_explore_window_compat(session_id: str) -> ExploreWindowResponse:
    _ensure_default_session(session_id)
    return get_explore_window()


@app.post("/v1/sessions/{session_id}/explore-window/open", response_model=ExploreWindowResponse, tags=["explore", "compat"])
def open_explore_window_compat(session_id: str, payload: ExploreWindowOpenRequest) -> ExploreWindowResponse:
    _ensure_default_session(session_id)
    return open_explore_window(payload)


@app.post("/v1/sessions/{session_id}/explore-window/close", response_model=ExploreWindowResponse, tags=["explore", "compat"])
def close_explore_window_compat(session_id: str) -> ExploreWindowResponse:
    _ensure_default_session(session_id)
    return close_explore_window()


def _ensure_default_session(session_id: str) -> None:
    if session_id != SINGLE_SESSION_ID:
        raise HTTPException(status_code=404, detail=f"single-session mode only supports: {SINGLE_SESSION_ID}")


def _build_state_response(*, state, turn_count: int, events_cursor: int) -> SessionStateResponse:
    return SessionStateResponse(
        session_id=SINGLE_SESSION_ID,
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
            explore_window_cooldown_until=state.learning.explore_window_cooldown_until,
            review_queue_size=len(state.learning.review_queue),
            history_event_count=events_cursor,
        ),
        topics=[_topic_info(topic) for topic in state.curriculum.topics],
        proposals=[_proposal_info(proposal) for proposal in state.learning.graph_proposals],
        mastery=[_mastery_info(topic_id, mastery) for topic_id, mastery in state.learning.mastery_map.items()],
        turn_count=turn_count,
        events_cursor=events_cursor,
    )


def _build_graph_response(state) -> KnowledgeGraphResponse:
    return KnowledgeGraphResponse(
        session_id=SINGLE_SESSION_ID,
        topics=[_topic_info(topic) for topic in state.curriculum.topics],
        proposals=[_proposal_info(proposal) for proposal in state.learning.graph_proposals],
        mastery=[_mastery_info(topic_id, mastery) for topic_id, mastery in state.learning.mastery_map.items()],
    )


def _build_turn_response(
    *,
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
        session_id=SINGLE_SESSION_ID,
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


def _build_explore_window_response(*, until_text: str | None, cooldown_text: str | None) -> ExploreWindowResponse:
    until = _parse_iso_ts(until_text)
    cooldown_until = _parse_iso_ts(cooldown_text)
    cooldown_remaining: int | None = None
    if cooldown_until is not None:
        remaining = int((cooldown_until - datetime.now(timezone.utc)).total_seconds())
        cooldown_remaining = remaining if remaining > 0 else 0

    if until is None:
        return ExploreWindowResponse(
            session_id=SINGLE_SESSION_ID,
            explore_window_until=until_text,
            active=False,
            remaining_seconds=None,
            cooldown_until=cooldown_text,
            cooldown_remaining_seconds=cooldown_remaining,
        )

    now = datetime.now(timezone.utc)
    remaining = int((until - now).total_seconds())
    if remaining <= 0:
        return ExploreWindowResponse(
            session_id=SINGLE_SESSION_ID,
            explore_window_until=until_text,
            active=False,
            remaining_seconds=0,
            cooldown_until=cooldown_text,
            cooldown_remaining_seconds=cooldown_remaining,
        )

    return ExploreWindowResponse(
        session_id=SINGLE_SESSION_ID,
        explore_window_until=until_text,
        active=True,
        remaining_seconds=remaining,
        cooldown_until=cooldown_text,
        cooldown_remaining_seconds=cooldown_remaining,
    )


def _build_session_summary(*, turn_count: int) -> SessionSummary:
    now = datetime.now(timezone.utc).isoformat()
    return SessionSummary(
        session_id=SINGLE_SESSION_ID,
        created_at=now,
        updated_at=now,
        turn_count=turn_count,
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
        mastery_state=getattr(mastery, "mastery_state", "unknown"),
        depth_level=mastery.depth_level,
        stability_level=mastery.stability_level,
        success_count=mastery.success_count,
        success_streak=mastery.success_streak,
        spaced_success_count=mastery.spaced_success_count,
        last_success_ts=mastery.last_success_ts,
    )


def _validate_text(text: str) -> None:
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")
    max_chars = get_max_text_chars()
    if len(text) > max_chars:
        raise HTTPException(status_code=400, detail=f"text too long, max chars: {max_chars}")


def _validate_audio(audio_bytes: bytes) -> None:
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio file is empty")
    max_bytes = get_max_audio_bytes()
    if len(audio_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"audio file too large, max bytes: {max_bytes}")


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
