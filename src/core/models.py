# src/core/models.py
from typing import Literal, Any
from pydantic import BaseModel, Field
from src.core.enums import LearningPhase

class UserProfile(BaseModel):
    student_id: str
    display_name: str
    grade_level: str | None = None
    locale: str = "zh-CN"

class TopicNode(BaseModel):
    topic_id: str
    title: str
    difficulty: int
    prerequisite_ids: list[str]
    tags: list[str]

class PendingQuestion(BaseModel):
    question_id: str
    stem: str
    choices: list[str] | None = None
    expected_format: Literal["open", "single_choice", "multi_choice"]

class EvaluationResult(BaseModel):
    is_correct: bool
    error_type: str | None = None
    feedback_text: str

class LearningEvent(BaseModel):
    ts: str
    kind: str
    payload: dict[str, Any]

class LearningState(BaseModel):
    current_topic_id: str | None = None
    current_phase: LearningPhase
    error_rate: float = Field(default=0.0, description="最近 window_size 次答题错误比例")
    error_window_size: int = 10
    consecutive_correct: int = 0
    consecutive_wrong: int = 0
    
    # 🔴 这是为你新增的积分字段，用于前端控制宠物形态
    total_score: int = 0 
    
    history_logs: list[LearningEvent] = Field(default_factory=list)
    pending_question: PendingQuestion | None = None
    last_evaluation: EvaluationResult | None = None

class CurriculumConfig(BaseModel):
    topics: list[TopicNode]

class AppState(BaseModel):
    schema_version: int = 1
    profile: UserProfile
    learning: LearningState
    curriculum: CurriculumConfig