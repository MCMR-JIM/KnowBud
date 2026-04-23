from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str
    arch_mode: str


class SessionProfile(BaseModel):
    student_id: str
    display_name: str
    locale: str


class SessionLearningState(BaseModel):
    current_topic_id: str | None = None
    current_phase: str
    total_score: int
    consecutive_correct: int
    consecutive_wrong: int
    explore_window_until: str | None = None


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


class SessionStateResponse(BaseModel):
    profile: SessionProfile
    learning: SessionLearningState
    topics: list[TopicInfo] = Field(default_factory=list)
    proposals: list[ProposalInfo] = Field(default_factory=list)
    mastery: list[MasteryInfo] = Field(default_factory=list)


class TextTurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class TurnResponse(BaseModel):
    user_text: str
    reply_text: str
    earned_points: int
    reply_audio_base64: str | None = None
    reply_audio_mime: str = "audio/mpeg"
    current_topic_id: str | None = None
    current_phase: str
    total_score: int
    explore_window_until: str | None = None


class AudioTurnResponse(TurnResponse):
    recognized_text: str


class PushReviewRequest(BaseModel):
    topic_id: str = Field(min_length=1, max_length=120)


class PushReviewResponse(BaseModel):
    queued: bool
    topic_id: str
    review_queue_size: int


class KnowledgeGraphResponse(BaseModel):
    topics: list[TopicInfo] = Field(default_factory=list)
    proposals: list[ProposalInfo] = Field(default_factory=list)
    mastery: list[MasteryInfo] = Field(default_factory=list)
