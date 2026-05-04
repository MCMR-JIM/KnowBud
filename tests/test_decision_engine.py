import pytest
from src.core.enums import LearningPhase, UserIntent, ActionKind
from src.core.models import (
    LearningState, CurriculumConfig, TopicNode, UserProfile
)
from src.core.decision_engine import DecisionEngine

# ==========================================
# 准备测试用的假数据 (Fixtures)
# ==========================================

@pytest.fixture
def dummy_curriculum() -> CurriculumConfig:
    """造一个假课程库，里面只有一个测试知识点"""
    return CurriculumConfig(
        topics=[
            TopicNode(
                topic_id="topic_test_01",
                title="测试知识点",
                difficulty=1,
                prerequisite_ids=[],
                tags=["math"]
            )
        ]
    )

@pytest.fixture
def dummy_state() -> LearningState:
    """造一个干净的初始学习状态"""
    return LearningState(
        current_phase=LearningPhase.NOT_STARTED,
        error_rate=0.0,
        consecutive_correct=0,
        consecutive_wrong=0,
        history_logs=[]
    )

@pytest.fixture
def engine() -> DecisionEngine:
    """实例化我们的大脑：设定错3次复习，对3次掌握"""
    return DecisionEngine(fail_threshold=3, master_streak=3)

# ==========================================
# 开始体检 (测试用例)
# ==========================================

def test_initial_assignment(engine: DecisionEngine, dummy_state: LearningState, dummy_curriculum: CurriculumConfig):
    """测试 1：刚开始学习，应该分配第一个知识点并播放视频"""
    result = engine.evaluate(
        state=dummy_state,
        curriculum=dummy_curriculum,
        intent=UserIntent.NONE
    )
    assert result.action.kind == ActionKind.PLAY_MEDIA
    assert result.state_delta.patch_learning["current_phase"] == LearningPhase.LEARNING

def test_mark_learning_done(engine: DecisionEngine, dummy_state: LearningState, dummy_curriculum: CurriculumConfig):
    """测试 2：学完了，应该切换到练习阶段"""
    dummy_state.current_phase = LearningPhase.LEARNING
    result = engine.evaluate(
        state=dummy_state,
        curriculum=dummy_curriculum,
        intent=UserIntent.MARK_LEARNING_DONE
    )
    assert result.action.kind == ActionKind.SET_PHASE
    assert result.state_delta.patch_learning["current_phase"] == LearningPhase.PRACTICING

def test_consecutive_wrong_triggers_review(engine: DecisionEngine, dummy_state: LearningState, dummy_curriculum: CurriculumConfig):
    """测试 3：连续错 3 次，必须强制切到复习阶段"""
    dummy_state.current_phase = LearningPhase.PRACTICING
    dummy_state.consecutive_wrong = 3 # 模拟已经错了3次
    
    result = engine.evaluate(
        state=dummy_state,
        curriculum=dummy_curriculum,
        intent=UserIntent.SUBMIT_ANSWER,
        user_answer_text="我不知道"
    )
    assert result.action.kind == ActionKind.PLAY_MEDIA
    assert getattr(result.action, "prefer_review", False) is True # 确认播放的是复习视频
    assert result.state_delta.patch_learning["current_phase"] == LearningPhase.REVIEWING

def test_consecutive_correct_triggers_mastery(engine: DecisionEngine, dummy_state: LearningState, dummy_curriculum: CurriculumConfig):
    """测试 4：连续对 3 次，算完全掌握"""
    dummy_state.current_phase = LearningPhase.PRACTICING
    dummy_state.consecutive_correct = 3 # 模拟已经对了3次
    
    result = engine.evaluate(
        state=dummy_state,
        curriculum=dummy_curriculum,
        intent=UserIntent.SUBMIT_ANSWER,
        user_answer_text="答案是A"
    )
    assert result.action.kind == ActionKind.SPEAK_PLAIN
    assert result.state_delta.patch_learning["current_phase"] == LearningPhase.MASTERED

def test_invalid_input(engine: DecisionEngine, dummy_state: LearningState, dummy_curriculum: CurriculumConfig):
    """测试 5：乱按按钮，应该不崩溃，且无事发生"""
    dummy_state.current_phase = LearningPhase.NOT_STARTED
    result = engine.evaluate(
        state=dummy_state,
        curriculum=dummy_curriculum,
        intent=UserIntent.SKIP # 没开始学就按跳过，属于瞎按
    )
    assert result.action.kind == ActionKind.NOOP