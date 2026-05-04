from __future__ import annotations

from typing import Annotated, Union, Literal, Any, Optional
from pydantic import BaseModel, Field

# 导入我们之前写的枚举和模型
from src.core.enums import ActionKind, LearningPhase, MediaKind
from src.core.models import PendingQuestion, LearningEvent

# ==========================================
# 1. 定义各种具体的动作指令
# ==========================================

class NoopAction(BaseModel):
    """占位动作，什么都不做"""
    kind: Literal[ActionKind.NOOP] = ActionKind.NOOP

class PlayMediaAction(BaseModel):
    """播放媒体动作"""
    kind: Literal[ActionKind.PLAY_MEDIA] = ActionKind.PLAY_MEDIA
    topic_id: str
    media: MediaKind
    prefer_review: bool

class SpeakSSMLAction(BaseModel):
    """语音播报动作（带感情的 SSML 格式）"""
    kind: Literal[ActionKind.SPEAK_SSML] = ActionKind.SPEAK_SSML
    ssml: str

class SpeakPlainAction(BaseModel):
    """语音播报动作（纯文本，兜底用）"""
    kind: Literal[ActionKind.SPEAK_PLAIN] = ActionKind.SPEAK_PLAIN
    text: str

class ShowQuestionAction(BaseModel):
    """展示题目的动作"""
    kind: Literal[ActionKind.SHOW_QUESTION] = ActionKind.SHOW_QUESTION
    question: PendingQuestion

class RequestUserInputAction(BaseModel):
    """请求用户输入的动作（比如提示小朋友继续）"""
    kind: Literal[ActionKind.REQUEST_USER_INPUT] = ActionKind.REQUEST_USER_INPUT
    prompt_plain: str

class SetPhaseAction(BaseModel):
    """强行改变学习阶段的动作"""
    kind: Literal[ActionKind.SET_PHASE] = ActionKind.SET_PHASE
    new_phase: LearningPhase


# ==========================================
# 2. 把它们打包成一个“任意动作”类型 (Tagged Union)
# ==========================================
# 这行代码很关键：它告诉系统，ActionCommand 只能是上面定义的其中一种。
# 以后解析的时候，系统看到 kind 字段就知道是哪个具体动作了。
ActionCommand = Annotated[
    Union[
        NoopAction,
        PlayMediaAction,
        SpeakSSMLAction,
        SpeakPlainAction,
        ShowQuestionAction,
        RequestUserInputAction,
        SetPhaseAction
    ],
    Field(discriminator="kind")
]


# ==========================================
# 3. 定义状态的改变和最终的决策结果
# ==========================================

class StateDelta(BaseModel):
    """不可变补丁：描述系统状态需要发生什么改变"""
    patch_learning: Optional[dict[str, Any]] = None
    clear_pending_question: bool = False
    append_event: Optional[LearningEvent] = None

class DecisionResult(BaseModel):
    """这是引擎大脑最终吐出来的完整结果"""
    action: ActionCommand
    state_delta: StateDelta
    trace: str  # 说人话的解释，专门留给 Admin 看的日志
