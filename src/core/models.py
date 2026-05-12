from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field
from src.core.enums import LearningPhase
import datetime

class UserProfile(BaseModel):
    student_id: str
    display_name: str
    grade_level: Optional[str] = None
    locale: str = "zh-CN"

class TopicNode(BaseModel):
    topic_id: str
    title: str
    difficulty: int
    parent_ids: list[str] = Field(default_factory=list)
    prerequisite_ids: list[str] = Field(default_factory=list)
    tags: list[str]

class PendingQuestion(BaseModel):
    question_id: str
    stem: str
    choices: Optional[list[str]] = None
    expected_format: Literal["open", "single_choice", "multi_choice"]

class EvaluationResult(BaseModel):
    is_correct: bool
    error_type: Optional[str] = None
    feedback_text: str

# 🚀 新增：雷达图数据模型
class RadarScore(BaseModel):
    focus: int = 85
    activeness: int = 85
    logic: int = 85
    mastery: int = 85
    emotion: int = 85

# 🚀 新增：错题本数据模型
class ErrorRecord(BaseModel):
    topic_id: str
    stem: str
    first_error_time: str
    is_mastered: bool = False

class LearningEvent(BaseModel):
    ts: str
    kind: str
    payload: dict[str, Any]
    audio_file_path: Optional[str] = None  # 🚀 新增：保存孩子录音的本地路径


class ResourceSegment(BaseModel):
    segment_id: str
    start_ms: int = 0
    end_ms: Optional[int] = None
    label: str = "full"
    status: str = "confirmed"
    sequence_index: int = 0
    text: Optional[str] = None
    locator: dict[str, Any] = Field(default_factory=dict)
    topic_id: Optional[str] = None
    proposal_id: Optional[str] = None
    proposed_topic_title: Optional[str] = None
    proposed_parent_node_ids: list[str] = Field(default_factory=list)
    decision: str = "link"
    confidence: float = 0.0
    reason: str = ""
    guiding_question: Optional[str] = None
    teaching_hint: Optional[str] = None


class ResourceRecord(BaseModel):
    resource_id: str
    topic_id: str
    resource_name: str
    category: str = "learn"
    media_type: str
    mime_type: str
    original_filename: str
    stored_path: str
    size_bytes: int
    created_ts: str
    ingestion_status: str = "pending"
    ingestion_error: Optional[str] = None
    extracted_node_count: int = 0
    candidate_graph_json: Optional[str] = None
    review_graph_json: Optional[str] = None
    segments: list[ResourceSegment] = Field(default_factory=list)


class GraphProposalRecord(BaseModel):
    proposal_id: str
    title: str
    summary: str
    trigger: str
    tags: list[str] = Field(default_factory=list)
    parent_node_ids: list[str] = Field(default_factory=list)
    prerequisite_node_ids: list[str] = Field(default_factory=list)
    pending_parent_proposal_ids: list[str] = Field(default_factory=list)
    edge_type: str = "requires"
    status: str = "proposed"
    reason: str = ""
    created_topic_id: Optional[str] = None
    observation_count: int = 0
    created_ts: str
    updated_ts: str


class NodeMastery(BaseModel):
    mastery_state: str = "unknown"
    depth_level: int = 0
    stability_level: int = 0
    success_count: int = 0
    success_streak: int = 0
    spaced_success_count: int = 0
    last_success_ts: Optional[str] = None
    last_state_ts: Optional[str] = None
    reward_window_granted: bool = False

class LearningState(BaseModel):
    current_topic_id: Optional[str] = None
    current_phase: LearningPhase
    error_rate: float = Field(default=0.0, description="最近 window_size 次答题错误比例")
    error_window_size: int = 10
    consecutive_correct: int = 0
    consecutive_wrong: int = 0
    total_score: int = 0  
    
    # 🚀 新增这三个核心字段，支撑家长端功能
    radar_data: RadarScore = Field(default_factory=RadarScore)
    error_book: list[ErrorRecord] = Field(default_factory=list)
    review_queue: list[str] = Field(default_factory=list) # 等待家长强推的复习队列
    explore_window_until: Optional[str] = None
    explore_window_cooldown_until: Optional[str] = None
    mastery_map: dict[str, NodeMastery] = Field(default_factory=dict)
    graph_proposals: list[GraphProposalRecord] = Field(default_factory=list)
    shadow_observation_map: dict[str, int] = Field(default_factory=dict)
    shadow_wrong_streak_map: dict[str, int] = Field(default_factory=dict)
    
    history_logs: list[LearningEvent] = Field(default_factory=list)
    pending_question: Optional[PendingQuestion] = None
    last_evaluation: Optional[EvaluationResult] = None

class CurriculumConfig(BaseModel):
    topics: list[TopicNode]

class AppState(BaseModel):
    schema_version: int = 1
    profile: UserProfile
    learning: LearningState
    curriculum: CurriculumConfig


# ── Candidate Graph Models (RAG extraction output) ──

class SourceRef(BaseModel):
    segment_id: str
    excerpt: str = ""
    relevance: Optional[float] = None


class SourceSegment(BaseModel):
    segment_id: str
    segment_index: int
    locator: dict[str, Any] = Field(default_factory=dict)
    text: str = ""
    status: str = "unclassified"


class CandidateNode(BaseModel):
    temp_id: str
    title: str
    normalized_title: str = ""
    subject: str
    language_id: Optional[str] = None
    facet: str
    summary: str = ""
    node_kind: Literal["knowledge"] = "knowledge"
    tags: list[str] = Field(default_factory=list)
    difficulty: Optional[int] = None
    confidence: float = 0.0
    extraction_label: Optional[str] = None
    source_segment_refs: list[SourceRef] = Field(default_factory=list)
    review_status: str = "pending"
    review_notes: Optional[str] = None


class CandidateRelay(BaseModel):
    relay_id: str
    title: str
    subject: str
    language_id: Optional[str] = None
    facet: str
    node_kind: Literal["relay"] = "relay"
    children_temp_ids: list[str] = Field(default_factory=list)
    parent_temp_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    grouping_rationale: str = ""
    source_segment_refs: list[SourceRef] = Field(default_factory=list)
    review_status: str = "pending"
    review_notes: Optional[str] = None


class CandidateEdge(BaseModel):
    edge_id: str
    source_temp_id: str
    target_temp_id: str
    edge_type: str = "requires"
    edge_kind: str = "parent_child"
    confidence: float = 0.0
    rationale: str = ""
    source_segment_refs: list[SourceRef] = Field(default_factory=list)
    review_status: str = "pending"
    review_notes: Optional[str] = None


class MergeCandidate(BaseModel):
    merge_group_id: str
    canonical_temp_id: str
    merged_temp_ids: list[str] = Field(default_factory=list)
    merge_type: str = "semantic_equivalence"
    confidence: float = 0.0
    rationale: str = ""
    review_status: str = "pending"
    review_notes: Optional[str] = None


class DiagnosticsWarning(BaseModel):
    code: str
    message: str
    affected_temp_ids: list[str] = Field(default_factory=list)
    severity: str = "warn"


class ExtractionDiagnostics(BaseModel):
    extraction_model: str = ""
    extraction_temperature: float = 0.3
    total_extraction_time_ms: int = 0
    pipeline: str = ""
    node_count: int = 0
    relay_count: int = 0
    edge_count: int = 0
    merge_group_count: int = 0
    segment_count: int = 0
    warnings: list[DiagnosticsWarning] = Field(default_factory=list)
    notes: str = ""


class DocumentMeta(BaseModel):
    resource_id: str
    resource_name: str
    media_type: str
    original_filename: str
    subject: str
    language_id: Optional[str] = None
    doc_type: str = ""
    total_chunks: int = 0
    total_chars: int = 0
    extraction_timestamp: str = ""


class CandidateGraph(BaseModel):
    schema_version: str = "2.0"
    extraction_id: str = ""
    document: DocumentMeta
    candidate_nodes: list[CandidateNode] = Field(default_factory=list)
    candidate_relays: list[CandidateRelay] = Field(default_factory=list)
    candidate_edges: list[CandidateEdge] = Field(default_factory=list)
    merge_candidates: list[MergeCandidate] = Field(default_factory=list)
    source_segments: list[SourceSegment] = Field(default_factory=list)
    diagnostics: ExtractionDiagnostics = Field(default_factory=ExtractionDiagnostics)


# ── Review Layer Models (candidate structure review output) ──

class NamingIssue(BaseModel):
    issue_id: str
    temp_id: str
    issue_type: Literal[
        "redundant_name",
        "exercise_title",
        "overlong_title",
        "near_duplicate",
        "mergeable_to_existing",
    ]
    severity: Literal["error", "warn", "info"] = "warn"
    title: str = ""
    suggested_title: Optional[str] = None
    description: str = ""
    merge_target_temp_id: Optional[str] = None
    merge_target_existing_topic_id: Optional[str] = None


class LogicIssue(BaseModel):
    issue_id: str
    temp_id: str
    issue_type: Literal[
        "wrong_parent",
        "prerequisite_inversion",
        "excessive_relay",
        "self_reference",
        "cross_subject",
        "orphan_node",
        "duplicate_edge",
    ]
    severity: Literal["error", "warn", "info"] = "warn"
    description: str = ""
    suggested_parent_ids: list[str] = Field(default_factory=list)
    suggested_prerequisite_ids: list[str] = Field(default_factory=list)
    affected_temp_ids: list[str] = Field(default_factory=list)


class NamingReview(BaseModel):
    passed: bool = True
    issues: list[NamingIssue] = Field(default_factory=list)
    canonical_titles: dict[str, str] = Field(default_factory=dict)


class LogicReview(BaseModel):
    passed: bool = True
    issues: list[LogicIssue] = Field(default_factory=list)


class CompilableNode(BaseModel):
    temp_id: str
    canonical_title: str
    subject: str
    language_id: Optional[str] = None
    facet: str
    summary: str = ""
    node_kind: Literal["knowledge", "relay"] = "knowledge"
    parent_temp_ids: list[str] = Field(default_factory=list)
    prerequisite_temp_ids: list[str] = Field(default_factory=list)
    edge_type: str = "part_of"
    tags: list[str] = Field(default_factory=list)
    difficulty: Optional[int] = None
    source_temp_ids: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    schema_version: str = "2.0"
    review_id: str = ""
    extraction_id: str = ""
    resource_id: str = ""
    naming: NamingReview = Field(default_factory=NamingReview)
    logic: LogicReview = Field(default_factory=LogicReview)
    compilable_nodes: list[CompilableNode] = Field(default_factory=list)
    compilable_edges: list[CandidateEdge] = Field(default_factory=list)
    compilable_relays: list[CandidateRelay] = Field(default_factory=list)
    merge_map: dict[str, str] = Field(default_factory=dict)
    dropped_temp_ids: list[str] = Field(default_factory=list)
