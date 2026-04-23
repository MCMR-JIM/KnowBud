from typing import Literal, Any
from pydantic import BaseModel, Field
from src.core.enums import LearningPhase
import datetime

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
    audio_file_path: str | None = None  # 🚀 新增：保存孩子录音的本地路径

class LearningState(BaseModel):
    current_topic_id: str | None = None
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
