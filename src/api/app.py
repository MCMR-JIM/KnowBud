from __future__ import annotations

import base64
import threading
from functools import lru_cache

from fastapi import FastAPI, File, HTTPException, UploadFile

from src.api.schemas import (
    AudioTurnResponse,
    HealthResponse,
    KnowledgeGraphResponse,
    MasteryInfo,
    ProposalInfo,
    PushReviewRequest,
    PushReviewResponse,
    SessionLearningState,
    SessionProfile,
    SessionStateResponse,
    TextTurnRequest,
    TopicInfo,
    TurnResponse,
)
from src.services.session_backend import SessionBackend

app = FastAPI(
    title="LoopTutor Frontend API",
    version="0.1.0",
    description="Reserved backend HTTP interfaces for future standalone frontend integration.",
)

_backend_lock = threading.Lock()


@lru_cache(maxsize=1)
def get_backend() -> SessionBackend:
    return SessionBackend()


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    backend = get_backend()
    return HealthResponse(
        ok=True,
        service="looptutor-frontend-api",
        version="0.1.0",
        arch_mode=backend.learning_arch_mode,
    )


@app.get("/v1/session/state", response_model=SessionStateResponse, tags=["session"])
def get_session_state() -> SessionStateResponse:
    backend = get_backend()
    with _backend_lock:
        state = backend.load_app_state()
    return _build_state_response(state)


@app.post("/v1/session/input/text", response_model=TurnResponse, tags=["session"])
def submit_text_turn(payload: TextTurnRequest) -> TurnResponse:
    backend = get_backend()
    user_text = payload.text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text cannot be empty")

    with _backend_lock:
        reply_text, earned_points, reply_audio = backend.evaluate_and_speak(user_text)
        state = backend.load_app_state()

    return _build_turn_response(
        state=state,
        user_text=user_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
    )


@app.post("/v1/session/input/audio", response_model=AudioTurnResponse, tags=["session"])
async def submit_audio_turn(file: UploadFile = File(...)) -> AudioTurnResponse:
    backend = get_backend()
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio file is empty")

    with _backend_lock:
        recognized_text = backend.transcribe_audio(audio_bytes)
        reply_text, earned_points, reply_audio = backend.evaluate_and_speak(recognized_text)
        state = backend.load_app_state()

    base = _build_turn_response(
        state=state,
        user_text=recognized_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
    )
    return AudioTurnResponse(recognized_text=recognized_text, **base.model_dump())


@app.post("/v1/session/review/push", response_model=PushReviewResponse, tags=["session", "admin"])
def push_review_topic(payload: PushReviewRequest) -> PushReviewResponse:
    backend = get_backend()
    with _backend_lock:
        backend.inject_review_topic(payload.topic_id)
        state = backend.load_app_state()
    return PushReviewResponse(
        queued=payload.topic_id in state.learning.review_queue,
        topic_id=payload.topic_id,
        review_queue_size=len(state.learning.review_queue),
    )


@app.get("/v1/knowledge/graph", response_model=KnowledgeGraphResponse, tags=["knowledge"])
def get_knowledge_graph() -> KnowledgeGraphResponse:
    backend = get_backend()
    with _backend_lock:
        state = backend.load_app_state()
    return KnowledgeGraphResponse(
        topics=[_topic_info(t) for t in state.curriculum.topics],
        proposals=[_proposal_info(p) for p in state.learning.graph_proposals],
        mastery=[
            MasteryInfo(
                topic_id=topic_id,
                depth_level=m.depth_level,
                stability_level=m.stability_level,
                success_count=m.success_count,
                success_streak=m.success_streak,
                spaced_success_count=m.spaced_success_count,
                last_success_ts=m.last_success_ts,
            )
            for topic_id, m in state.learning.mastery_map.items()
        ],
    )


def _build_state_response(state) -> SessionStateResponse:
    return SessionStateResponse(
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
        ),
        topics=[_topic_info(t) for t in state.curriculum.topics],
        proposals=[_proposal_info(p) for p in state.learning.graph_proposals],
        mastery=[
            MasteryInfo(
                topic_id=topic_id,
                depth_level=m.depth_level,
                stability_level=m.stability_level,
                success_count=m.success_count,
                success_streak=m.success_streak,
                spaced_success_count=m.spaced_success_count,
                last_success_ts=m.last_success_ts,
            )
            for topic_id, m in state.learning.mastery_map.items()
        ],
    )


def _build_turn_response(*, state, user_text: str, reply_text: str, earned_points: int, reply_audio: bytes) -> TurnResponse:
    audio_base64 = base64.b64encode(reply_audio).decode("ascii") if reply_audio else None
    return TurnResponse(
        user_text=user_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio_base64=audio_base64,
        current_topic_id=state.learning.current_topic_id,
        current_phase=str(state.learning.current_phase),
        total_score=state.learning.total_score,
        explore_window_until=state.learning.explore_window_until,
    )


def _topic_info(topic) -> TopicInfo:
    return TopicInfo(
        topic_id=topic.topic_id,
        title=topic.title,
        difficulty=topic.difficulty,
        prerequisite_ids=list(topic.prerequisite_ids),
        tags=list(topic.tags),
    )


def _proposal_info(rec) -> ProposalInfo:
    return ProposalInfo(
        proposal_id=rec.proposal_id,
        title=rec.title,
        trigger=rec.trigger,
        status=rec.status,
        reason=rec.reason,
        created_topic_id=rec.created_topic_id,
        updated_ts=rec.updated_ts,
    )
