from src.core.enums import LearningPhase, MediaKind, UserIntent
from src.core.models import LearningState, CurriculumConfig
from src.core.actions import (
    DecisionResult, StateDelta, PlayMediaAction, SetPhaseAction,
    ShowQuestionAction, SpeakPlainAction, NoopAction
)

class DecisionEngine:
    """系统的核心大脑：根据当前状态和用户意图，决定下一步该干什么"""
    
    def __init__(self, *, fail_threshold: int, master_streak: int) -> None:
        self.fail_threshold = fail_threshold
        self.master_streak = master_streak 

    def evaluate(
        self,
        *,
        state: LearningState,
        curriculum: CurriculumConfig,
        intent: UserIntent,
        user_answer_text: str | None = None,
    ) -> DecisionResult:
        
        # 🚀 【规则 0】：最高优先级劫持！只要复习队列里有错题，并且正准备开启新学习阶段，立刻挂起主线，强制复习。
        if state.review_queue and state.current_phase in {LearningPhase.NOT_STARTED, LearningPhase.MASTERED} and intent in {UserIntent.NONE, UserIntent.CONFIRM}:
            topic_to_review = state.review_queue[0]
            remaining_queue = state.review_queue[1:]
            return DecisionResult(
                action=PlayMediaAction(
                    topic_id=topic_to_review,
                    media=MediaKind.VIDEO,
                    prefer_review=True # 告诉前端播放专门的复习/错题切片视频
                ),
                state_delta=StateDelta(
                    patch_learning={
                        "current_phase": LearningPhase.REVIEWING,
                        "current_topic_id": topic_to_review,
                        "review_queue": remaining_queue # 消耗掉该错题
                    }
                ),
                trace=f"家长控制台触发：强制挂起主线，优先复习错题 {topic_to_review}"
            )

        # 规则 1：刚开始还没学，且没有明确拒绝 -> 分配第一个知识点，开始播放教学视频
        if state.current_phase == LearningPhase.NOT_STARTED and intent in {UserIntent.NONE, UserIntent.CONFIRM}:
            first_topic = curriculum.topics[0]
            return DecisionResult(
                action=PlayMediaAction(
                    topic_id=first_topic.topic_id,
                    media=MediaKind.VIDEO,
                    prefer_review=False
                ),
                state_delta=StateDelta(
                    patch_learning={
                        "current_phase": LearningPhase.LEARNING,
                        "current_topic_id": first_topic.topic_id
                    }
                ),
                trace="分配初始主题，进入学习阶段"
            )

        # 规则 2：小朋友点“我学完了” -> 切换到练习阶段
        if state.current_phase == LearningPhase.LEARNING and intent == UserIntent.MARK_LEARNING_DONE:
            return DecisionResult(
                action=SetPhaseAction(new_phase=LearningPhase.PRACTICING),
                state_delta=StateDelta(
                    patch_learning={"current_phase": LearningPhase.PRACTICING}
                ),
                trace="学习完成，进入练习阶段，等待后端出题"
            )
            
        # 规则 2 补充：已经在练习阶段了，并且系统里已经生成了题目 -> 展示题目
        if state.current_phase == LearningPhase.PRACTICING and state.pending_question is not None and intent != UserIntent.SUBMIT_ANSWER:
            return DecisionResult(
                action=ShowQuestionAction(question=state.pending_question),
                state_delta=StateDelta(),
                trace="展示当前练习题"
            )

        # 规则 3：小朋友提交了答案 -> 判断是不是连续对/错了足够多
        if state.current_phase == LearningPhase.PRACTICING and intent == UserIntent.SUBMIT_ANSWER and user_answer_text:
            if state.consecutive_wrong >= self.fail_threshold:
                return DecisionResult(
                    action=PlayMediaAction(
                        topic_id=state.current_topic_id or "",
                        media=MediaKind.VIDEO,
                        prefer_review=True
                    ),
                    state_delta=StateDelta(
                        patch_learning={"current_phase": LearningPhase.REVIEWING}
                    ),
                    trace=f"连续错 {state.consecutive_wrong} 次，触发自动复习"
                )
            elif state.consecutive_correct >= self.master_streak:
                return DecisionResult(
                    action=SpeakPlainAction(text="太棒了，你已经掌握了这个知识点！"),
                    state_delta=StateDelta(
                        patch_learning={"current_phase": LearningPhase.MASTERED}
                    ),
                    trace=f"连续对 {state.consecutive_correct} 次，达到掌握标准"
                )
            else:
                return DecisionResult(
                    action=NoopAction(),
                    state_delta=StateDelta(),
                    trace="继续当前练习"
                )

        # 规则 4：复习完了，点击确认 -> 重新回到常规学习阶段
        if state.current_phase == LearningPhase.REVIEWING and intent == UserIntent.CONFIRM:
            return DecisionResult(
                action=PlayMediaAction(
                    topic_id=state.current_topic_id or "",
                    media=MediaKind.VIDEO,
                    prefer_review=False
                ),
                state_delta=StateDelta(
                    patch_learning={"current_phase": LearningPhase.LEARNING}
                ),
                trace="复习确认完毕，返回正常学习阶段"
            )

        # 规则 5：兜底处理
        return DecisionResult(
            action=NoopAction(),
            state_delta=StateDelta(),
            trace=f"未命中任何规则 (phase={state.current_phase}, intent={intent})"
        )