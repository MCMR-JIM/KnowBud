from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str
    arch_mode: str


class SessionProfile(BaseModel):
    student_id: str
    display_name: str
    locale: str = "zh-CN"


class SessionLearningState(BaseModel):
    current_topic_id: str | None = None
    current_phase: str
    total_score: int
    consecutive_correct: int
    consecutive_wrong: int
    explore_window_until: str | None = None
    review_queue_size: int = 0
    history_event_count: int = 0


class TopicInfo(BaseModel):
    topic_id: str
    title: str
    difficulty: int
    prerequisite_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ProposalInfo(BaseModel):
    proposal_id: str
    title: str
    trigger: str
    status: str
    reason: str
    created_topic_id: str | None = None
    updated_ts: str


class MasteryInfo(BaseModel):
    topic_id: str
    depth_level: int
    stability_level: int
    success_count: int
    success_streak: int
    spaced_success_count: int
    last_success_ts: str | None = None


class KnowledgeGraphResponse(BaseModel):
    session_id: str
    topics: list[TopicInfo] = Field(default_factory=list)
    proposals: list[ProposalInfo] = Field(default_factory=list)
    mastery: list[MasteryInfo] = Field(default_factory=list)


class SessionStateResponse(BaseModel):
    session_id: str
    profile: SessionProfile
    learning: SessionLearningState
    topics: list[TopicInfo] = Field(default_factory=list)
    proposals: list[ProposalInfo] = Field(default_factory=list)
    mastery: list[MasteryInfo] = Field(default_factory=list)
    turn_count: int = 0
    events_cursor: int = 0


class TextTurnRequest(BaseModel):
    text: str


class TurnResponse(BaseModel):
    session_id: str
    turn_id: str
    user_text: str
    reply_text: str
    earned_points: int
    reply_audio_base64: str | None = None
    reply_audio_mime: str = "audio/mpeg"
    current_topic_id: str | None = None
    current_phase: str
    total_score: int
    explore_window_until: str | None = None
    events_cursor: int = 0


class AudioTurnResponse(TurnResponse):
    recognized_text: str


class PushReviewRequest(BaseModel):
    topic_id: str


class PushReviewResponse(BaseModel):
    session_id: str
    queued: bool
    topic_id: str
    review_queue_size: int


class CreateSessionRequest(BaseModel):
    student_id: str | None = None
    display_name: str | None = None
    locale: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    created_at: str
    updated_at: str
    turn_count: int


class CreateSessionResponse(BaseModel):
    session: SessionSummary
    state: SessionStateResponse


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary] = Field(default_factory=list)


class EventInfo(BaseModel):
    event_index: int
    ts: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class EventListResponse(BaseModel):
    session_id: str
    after: int
    next_cursor: int
    events: list[EventInfo] = Field(default_factory=list)


class ReviewQueueResponse(BaseModel):
    session_id: str
    topics: list[str] = Field(default_factory=list)
    size: int


class ExploreWindowOpenRequest(BaseModel):
    minutes: int = Field(default=5, ge=1, le=120)


class ExploreWindowResponse(BaseModel):
    session_id: str
    explore_window_until: str | None = None
    active: bool
    remaining_seconds: int | None = None


class MasteryListResponse(BaseModel):
    session_id: str
    mastery: list[MasteryInfo] = Field(default_factory=list)
