from enum import StrEnum

class LearningPhase(StrEnum):
    """学习阶段"""
    NOT_STARTED = "NOT_STARTED"
    LEARNING = "LEARNING"
    PRACTICING = "PRACTICING"
    REVIEWING = "REVIEWING"
    MASTERED = "MASTERED"

class MediaKind(StrEnum):
    """媒体类型"""
    VIDEO = "VIDEO"
    PDF = "PDF"
    AUDIO = "AUDIO"

class UserIntent(StrEnum):
    """用户意图"""
    NONE = "NONE"
    CONFIRM = "CONFIRM"
    SKIP = "SKIP"
    SUBMIT_ANSWER = "SUBMIT_ANSWER"
    REQUEST_HINT = "REQUEST_HINT"
    MARK_LEARNING_DONE = "MARK_LEARNING_DONE"

class ActionKind(StrEnum):
    """决策引擎输出的动作指令类型"""
    NOOP = "NOOP"
    PLAY_MEDIA = "PLAY_MEDIA"
    SPEAK_SSML = "SPEAK_SSML"
    SPEAK_PLAIN = "SPEAK_PLAIN"
    SHOW_QUESTION = "SHOW_QUESTION"
    REQUEST_USER_INPUT = "REQUEST_USER_INPUT"
    SET_PHASE = "SET_PHASE"