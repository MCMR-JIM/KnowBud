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
    def __init__(self) -> None:
        load_project_env()
        data_root = Path(os.getenv("DATA_ROOT", "./data"))
        self.ctx = SkillContext(data_root=data_root)
        self.state_file = Path(os.getenv("STATE_FILE", "./data/state.json"))
        self.log_file = Path(os.getenv("DECISION_LOG_FILE", "./logs/decision_trace.jsonl"))

        fail_th = int(os.getenv("FSM_FAIL_THRESHOLD", "3"))
        master_st = int(os.getenv("FSM_MASTER_STREAK", "3"))
        self.engine = DecisionEngine(fail_threshold=fail_th, master_streak=master_st)

        self.voice_skill = VoiceIOSkill(self.ctx, whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", "tiny"))
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
                topics=[TopicNode(topic_id="demo_01", title="恐龙为什么会灭绝？", difficulty=1, prerequisite_ids=[], tags=[])]
            ),
        )

    def save_app_state(self, state: AppState) -> None:
        # 直接写入以解决 Windows 权限冲突 (PermissionError)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def handle_text_event(self, intent: UserIntent, text: str | None = None) -> UIRenderBundle:
        state = self.load_app_state()
        if state.learning.current_phase == LearningPhase.PRACTICING and intent == UserIntent.SUBMIT_ANSWER and text:
            question = state.learning.pending_question or PendingQuestion(
                question_id="demo_q_01", stem="恐龙为什么会灭绝？", expected_format="open"
            )
            try:
                eval_result = self.llm_skill.evaluate_answer(question=question, user_answer=text)
                is_correct = eval_result.is_correct
                state.learning.last_evaluation = eval_result
            except Exception as exc:
                print(f"[SessionBackend] LLM调用失败，启用兜底: {exc}")
                is_correct = "陨石" in text or "火山" in text

            if is_correct:
                state.learning.consecutive_correct += 1
                state.learning.consecutive_wrong = 0
            else:
                state.learning.consecutive_wrong += 1
                state.learning.consecutive_correct = 0

        decision = self.engine.evaluate(state=state.learning, curriculum=state.curriculum, intent=intent, user_answer_text=text)

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            log_entry = {"intent": str(intent), "action_kind": str(decision.action.kind), "trace": decision.trace}
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

            if decision.state_delta.patch_learning:
                for k, v in decision.state_delta.patch_learning.items():
                    setattr(state.learning, k, v)

        self.save_app_state(state)
        return UIRenderBundle()

    # --- UI 桥接接口 ---
    def transcribe_audio(self, audio_bytes: bytes) -> str:
        if not audio_bytes: return ""
        text = self.voice_skill.transcribe(audio_bytes)
        return text if text else "（哎呀，没听清，能再说一遍吗？）"

    def generate_proactive_question(self) -> str:
        state = self.load_app_state()
        topic_title = state.curriculum.topics[0].title if state.curriculum.topics else "新知识"
        return f"准备好探索【{topic_title}】了吗？看视频的时候要仔细哦，一会我要考考你！"

    def evaluate_student_answer(self, user_text: str) -> tuple[str, int]:
        state = self.load_app_state()
        question = state.learning.pending_question or PendingQuestion(question_id="demo_q_01", stem="恐龙为什么会灭绝？", expected_format="open")
        try:
            eval_result = self.llm_skill.evaluate_answer(question=question, user_answer=user_text)
            is_correct = eval_result.is_correct
            reply_text = getattr(eval_result, "feedback_text", "说得太棒了！" if is_correct else "差一点点，再想想？") 
        except Exception:
            is_correct = "陨石" in user_text or "火山" in user_text
            reply_text = "有道理！跟陨石或火山有关哦！" if is_correct else "好像不太对，是不是跟陨石有关？"

        earned_points = 20 if is_correct else 5
        state.learning.total_score += earned_points
        self.save_app_state(state)
        self.handle_text_event(intent=UserIntent.SUBMIT_ANSWER, text=user_text)
        return reply_text, earned_points