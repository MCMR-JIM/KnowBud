# src/services/session_backend.py
import os
import json
from pathlib import Path
from dataclasses import dataclass, field

from src.core.enums import UserIntent, LearningPhase
from src.core.models import AppState, UserProfile, LearningState, CurriculumConfig, TopicNode, PendingQuestion
from src.core.decision_engine import DecisionEngine
from src.skills.base_skill import SkillContext
from src.skills.voice_io_skill import VoiceIOSkill
from src.skills.llm_tutor_skill import LLMTutorSkill
from src.services.env_loader import load_project_env

@dataclass
class UIRenderBundle:
    play_path: Path | None = None
    audio_bytes: bytes | None = None
    show_question: object | None = None
    messages: list[str] = field(default_factory=list)

class SessionBackend:
    """系统大管家：负责协调前端、状态机、语音与LLM技能。"""

    def __init__(self) -> None:
        load_project_env()

        data_root = Path(os.getenv("DATA_ROOT", "./data"))
        self.ctx = SkillContext(data_root=data_root)

        self.state_file = Path(os.getenv("STATE_FILE", "./data/state.json"))
        self.log_file = Path(os.getenv("DECISION_LOG_FILE", "./logs/decision_trace.jsonl"))

        fail_th = int(os.getenv("FSM_FAIL_THRESHOLD", "3"))
        master_st = int(os.getenv("FSM_MASTER_STREAK", "3"))
        self.engine = DecisionEngine(fail_threshold=fail_th, master_streak=master_st)

        self.voice_skill = VoiceIOSkill(self.ctx, whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", "base"))
        self.llm_skill = LLMTutorSkill(
            self.ctx,
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )

    def load_app_state(self) -> AppState:
        if self.state_file.exists():
            try:
                return AppState.model_validate_json(self.state_file.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"读取存档异常: {exc}")

        return AppState(
            profile=UserProfile(student_id="user_01", display_name="演示同学"),
            learning=LearningState(current_phase=LearningPhase.NOT_STARTED, total_score=0),
            curriculum=CurriculumConfig(
                topics=[
                    TopicNode(
                        topic_id="demo_01",
                        title="恐龙为什么会灭绝？",
                        difficulty=1,
                        prerequisite_ids=[],
                        tags=[],
                    )
                ]
            ),
        )

    def save_app_state(self, state: AppState) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_file.with_suffix(".tmp")
        tmp_file.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        tmp_file.replace(self.state_file)

    def handle_audio_upload(self, audio_bytes: bytes) -> UIRenderBundle:
        if not audio_bytes:
            return UIRenderBundle()
        transcribed_text = self.voice_skill.transcribe(audio_bytes)
        if transcribed_text:
            return self.handle_text_event(intent=UserIntent.SUBMIT_ANSWER, text=transcribed_text)
        return UIRenderBundle()

    def handle_text_event(self, intent: UserIntent, text: str | None = None) -> UIRenderBundle:
        state = self.load_app_state()

        if state.learning.current_phase == LearningPhase.PRACTICING and intent == UserIntent.SUBMIT_ANSWER and text:
            question = state.learning.pending_question or PendingQuestion(
                question_id="demo_q_01",
                stem="恐龙为什么会灭绝？",
                expected_format="open",
            )
            try:
                eval_result = self.llm_skill.evaluate_answer(question=question, user_answer=text)
                is_correct = eval_result.is_correct
                state.learning.last_evaluation = eval_result
            except Exception as exc:
                print(f"[SessionBackend] LLM调用失败，启用兜底规则: {exc}")
                is_correct = "陨石" in text or "火山" in text

            if is_correct:
                state.learning.consecutive_correct += 1
                state.learning.consecutive_wrong = 0
            else:
                state.learning.consecutive_wrong += 1
                state.learning.consecutive_correct = 0

        decision = self.engine.evaluate(
            state=state.learning,
            curriculum=state.curriculum,
            intent=intent,
            user_answer_text=text,
        )

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            log_entry = {
                "intent": str(intent),
                "action_kind": str(decision.action.kind),
                "trace": decision.trace,
            }
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        if decision.state_delta.patch_learning:
            for k, v in decision.state_delta.patch_learning.items():
                setattr(state.learning, k, v)

        self.save_app_state(state)
        return UIRenderBundle()

    # ==========================================
    # 以下为对接前端UI的桥接方法
    # ==========================================

    def transcribe_audio(self, audio_bytes: bytes) -> str:
        """供前端调用：将音频字节流转为文本"""
        if not audio_bytes:
            return ""
        transcribed_text = self.voice_skill.transcribe(audio_bytes)
        return transcribed_text if transcribed_text else "（哎呀，我没听清，能再说一遍吗？）"

    def generate_proactive_question(self) -> str:
        """供前端调用：AI主动向孩子发起提问或引导"""
        state = self.load_app_state()
        topic_title = state.curriculum.topics[0].title if state.curriculum.topics else "新知识"
        return f"嗷呜！准备好探索【{topic_title}】了吗？看视频的时候要仔细哦，一会我要考考你！"

    def evaluate_student_answer(self, user_text: str) -> tuple[str, int]:
        """
        供前端调用：处理孩子的回答，返回 AI的文字回复 和 获得的积分
        返回值: (reply_text, earned_points)
        """
        state = self.load_app_state()
        
        question = state.learning.pending_question or PendingQuestion(
            question_id="demo_q_01",
            stem="恐龙为什么会灭绝？",
            expected_format="open",
        )
        
        try:
            eval_result = self.llm_skill.evaluate_answer(question=question, user_answer=user_text)
            is_correct = eval_result.is_correct
            # 假设 eval_result 有 feedback_text 字段 (根据你的 models.py)
            reply_text = getattr(eval_result, "feedback_text", "哇，你说得太棒了！" if is_correct else "差一点点哦，再想想？") 
        except Exception as exc:
            print(f"[SessionBackend] LLM评判失败，启用兜底: {exc}")
            is_correct = "陨石" in user_text or "火山" in user_text
            reply_text = "哇，你说得有道理！跟陨石或火山爆发有关哦！" if is_correct else "好像不太对哦，是不是跟陨石有关？"

        # 对了给20分，错了给5分鼓励
        earned_points = 20 if is_correct else 5
        
        # 更新积分并保存
        state.learning.total_score += earned_points
        self.save_app_state(state)
        
        # 触发底层状态机记录日志
        self.handle_text_event(intent=UserIntent.SUBMIT_ANSWER, text=user_text)
        
        return reply_text, earned_points