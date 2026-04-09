from typing import Literal, Any
from pydantic import BaseModel, Field

# 导入我们刚刚在 T1 写的枚举暗号
from src.core.enums import LearningPhase

class UserProfile(BaseModel):
    """用户档案"""
    student_id: str
    display_name: str
    grade_level: str | None = None
    locale: str = "zh-CN"  # 默认中文

class TopicNode(BaseModel):
    """静态知识图谱节点（课程大纲里的一个知识点）"""
    topic_id: str
    title: str
    difficulty: int  # 难度 1-5
    prerequisite_ids: list[str]
    tags: list[str]

class PendingQuestion(BaseModel):
    """练习区展示的题目"""
    question_id: str
    stem: str
    choices: list[str] | None = None
    expected_format: Literal["open", "single_choice", "multi_choice"]

class EvaluationResult(BaseModel):
    """大模型（LLM）批改输出的结果"""
    is_correct: bool
    error_type: str | None = None
    feedback_text: str

class LearningEvent(BaseModel):
    """单条学习历史记录"""
    ts: str  # 推荐使用 ISO8601 字符串格式的时间戳
    kind: str
    payload: dict[str, Any]

class LearningState(BaseModel):
    """儿童当前的学习状态（进度存盘）"""
    current_topic_id: str | None = None
    current_phase: LearningPhase
    error_rate: float = Field(
        default=0.0, 
        description="最近 window_size 次答题错误比例"
    )
    error_window_size: int = 10
    consecutive_correct: int = 0
    consecutive_wrong: int = 0
    history_logs: list[LearningEvent] = Field(default_factory=list)
    pending_question: PendingQuestion | None = None
    last_evaluation: EvaluationResult | None = None

class CurriculumConfig(BaseModel):
    """课程配置（包含多个知识点）"""
    topics: list[TopicNode]

class AppState(BaseModel):
    """全局应用状态（也就是以后存到 state.json 里的根数据）"""
    schema_version: int = 1
    profile: UserProfile
    learning: LearningState
    curriculum: CurriculumConfig