from __future__ import annotations

from typing import Any, Optional

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
    current_topic_id: Optional[str] = None
    current_phase: str
    total_score: int
    consecutive_correct: int
    consecutive_wrong: int
    explore_window_until: Optional[str] = None
    explore_window_cooldown_until: Optional[str] = None
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
    summary: str = ""
    trigger: str
    parent_node_ids: list[str] = Field(default_factory=list)
    edge_type: str = "requires"
    status: str
    reason: str
    created_topic_id: Optional[str] = None
    updated_ts: str


class ProposalReviewRequest(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    parent_node_ids: Optional[list[str]] = None
    edge_type: Optional[str] = None
    difficulty: int = Field(default=1, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    reason: Optional[str] = None


class ProposalReviewResponse(BaseModel):
    session_id: str
    proposal: ProposalInfo
    topic: Optional[TopicInfo] = None
    relinked_segment_count: int = 0
    rescanned_segment_count: int = 0


class MasteryInfo(BaseModel):
    topic_id: str
    mastery_state: str
    depth_level: int
    stability_level: int
    success_count: int
    success_streak: int
    spaced_success_count: int
    last_success_ts: Optional[str] = None


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
    text: str = Field(min_length=1, max_length=8192)


class TurnResponse(BaseModel):
    session_id: str
    turn_id: str
    user_text: str
    reply_text: str
    earned_points: int
    reply_audio_base64: Optional[str] = None
    reply_audio_mime: str = "audio/mpeg"
    current_topic_id: Optional[str] = None
    current_phase: str
    total_score: int
    explore_window_until: Optional[str] = None
    events_cursor: int = 0


class AudioTurnResponse(TurnResponse):
    recognized_text: str


class PushReviewRequest(BaseModel):
    topic_id: Optional[str] = None
    content: Optional[str] = None


class PushReviewResponse(BaseModel):
    session_id: str
    queued: bool
    topic_id: str
    review_queue_size: int


class PageKnowledgeResponse(BaseModel):
    session_id: str
    topic_id: str
    page: int
    knowledge_text: str
    resource_id: Optional[str] = None
    segment_id: Optional[str] = None
    guiding_question: Optional[str] = None
    teaching_hint: Optional[str] = None


class ReviewQueueItem(BaseModel):
    topic_id: str
    title: str
    resource_count: int = 0


class ResourceSegmentInfo(BaseModel):
    segment_id: str
    start_ms: int = 0
    end_ms: Optional[int] = None
    label: str = "full"
    status: str
    sequence_index: int = 0
    text: Optional[str] = None
    locator: dict[str, Any] = Field(default_factory=dict)
    topic_id: Optional[str] = None
    proposal_id: Optional[str] = None
    proposed_topic_title: Optional[str] = None
    decision: str = "link"
    confidence: float = 0.0
    reason: str = ""
    guiding_question: Optional[str] = None
    teaching_hint: Optional[str] = None


class ResourceInfo(BaseModel):
    resource_id: str
    topic_id: str
    topic_title: str
    resource_name: str
    category: str
    media_type: str
    mime_type: str
    original_filename: str
    resource_url: str
    size_bytes: int
    created_ts: str
    ingestion_status: str = "pending"
    ingestion_error: Optional[str] = None
    segments: list[ResourceSegmentInfo] = Field(default_factory=list)


class ResourceTeachingCueInfo(BaseModel):
    resource_id: str
    resource_name: str
    media_type: str
    segment_id: str
    sequence_index: int = 0
    text: Optional[str] = None
    locator: dict[str, Any] = Field(default_factory=dict)
    guiding_question: Optional[str] = None
    teaching_hint: Optional[str] = None
    confidence: float = 0.0


class ResourceUploadResponse(BaseModel):
    session_id: str
    queued: bool
    review_queue_size: int
    resource: ResourceInfo


class TopicResourceListResponse(BaseModel):
    session_id: str
    topic_id: str
    topic_title: str
    resources: list[ResourceInfo] = Field(default_factory=list)


class TopicTeachingCueListResponse(BaseModel):
    session_id: str
    topic_id: str
    topic_title: str
    cues: list[ResourceTeachingCueInfo] = Field(default_factory=list)


class ResourceSegmentListResponse(BaseModel):
    resource_id: str
    segments: list[ResourceSegmentInfo] = Field(default_factory=list)


class ResourceIngestionStatusResponse(BaseModel):
    resource_id: str
    status: str
    segment_count: int = 0
    classified_count: int = 0
    proposed_count: int = 0
    unclassified_count: int = 0
    parse_failed_count: int = 0
    error: Optional[str] = None


class CreateSessionRequest(BaseModel):
    student_id: Optional[str] = None
    display_name: Optional[str] = None
    locale: Optional[str] = None


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
    items: list[ReviewQueueItem] = Field(default_factory=list)


class ExploreWindowOpenRequest(BaseModel):
    minutes: int = Field(default=5, ge=1, le=120)


class ExploreWindowResponse(BaseModel):
    session_id: str
    explore_window_until: Optional[str] = None
    active: bool
    remaining_seconds: Optional[int] = None
    cooldown_until: Optional[str] = None
    cooldown_remaining_seconds: Optional[int] = None


class MasteryListResponse(BaseModel):
    session_id: str
    mastery: list[MasteryInfo] = Field(default_factory=list)


class StreamTurnInitResponse(BaseModel):
    session_id: str
    turn_id: str
    reply_text: str
    earned_points: int
    current_topic_id: Optional[str] = None
    current_phase: str
    total_score: int
    explore_window_until: Optional[str] = None
    stream_id: str
    events_cursor: int = 0


class StreamInterruptResponse(BaseModel):
    session_id: str
    stream_id: str
    interrupted: bool
