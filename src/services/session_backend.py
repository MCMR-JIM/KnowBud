from __future__ import annotations

import os
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
import datetime
from datetime import timezone

from src.core.enums import UserIntent, LearningPhase
from src.core.models import AppState, UserProfile, LearningState, CurriculumConfig, TopicNode, PendingQuestion, ErrorRecord, LearningEvent, GraphProposalRecord
from src.core.decision_engine import DecisionEngine
from src.skills.base_skill import SkillContext
from src.skills.voice_io_skill import VoiceIOSkill
from src.skills.llm_tutor_skill import LLMTutorSkill
from src.agent.orchestrator import AgentOrchestrator
from src.agent.mastery_engine import MasteryEngine
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
        self.audio_artifact_root = Path(os.getenv("AUDIO_ARTIFACT_ROOT", "./artifacts/audio"))
        self.learning_arch_mode = os.getenv("LEARNING_ARCH_MODE", "legacy").strip().lower()
        self.explore_window_minutes = int(os.getenv("EXPLORE_WINDOW_MINUTES", "5"))
        self.prereq_unlock_depth = int(os.getenv("PREREQ_UNLOCK_DEPTH", "1"))

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
        self.agent_orchestrator = (
            AgentOrchestrator(unlock_depth_threshold=self.prereq_unlock_depth)
            if self.learning_arch_mode in {"agent", "hybrid"}
            else None
        )
        self.mastery_engine = MasteryEngine()

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

            self._apply_answer_outcome(state=state, question=question, is_correct=is_correct)

        decision = self.engine.evaluate(state=state.learning, curriculum=state.curriculum, intent=intent, user_answer_text=text)

        if decision.state_delta.patch_learning:
            for k, v in decision.state_delta.patch_learning.items():
                setattr(state.learning, k, v)

        self._append_decision_log(intent=intent, action_kind=str(decision.action.kind), trace=decision.trace)

        self.save_app_state(state)
        return UIRenderBundle()

    # 🚀 新增：家长端调用，强制推送错题
    def inject_review_topic(self, topic_id: str):
        state = self.load_app_state()
        if topic_id not in state.learning.review_queue:
            state.learning.review_queue.append(topic_id)
            self.save_app_state(state)

    def transcribe_audio(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""

        self._save_audio_artifact(audio_bytes, bucket="incoming", suffix=".wav")

        text = self.voice_skill.transcribe(audio_bytes)
        return text if text else "（哎呀，没听清，能再说一遍吗？）"

    def synthesize_reply_audio(self, text: str) -> bytes:
        if not text:
            return b""

        voice = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
        try:
            audio_bytes = self.voice_skill.synthesize_plain(text, voice=voice)
        except Exception as exc:
            print(f"语音合成失败: {exc}")
            return b""

        self._save_audio_artifact(audio_bytes, bucket="outgoing", suffix=".mp3")
        return audio_bytes

    def evaluate_and_speak(self, user_text: str) -> tuple[str, int, bytes]:
        if self.agent_orchestrator is not None:
            return self._evaluate_and_speak_agent(user_text)

        reply_text, earned_points = self.evaluate_student_answer(user_text)
        reply_audio = self.synthesize_reply_audio(reply_text)
        return reply_text, earned_points, reply_audio

    def _evaluate_and_speak_agent(self, user_text: str) -> tuple[str, int, bytes]:
        state = self.load_app_state()
        window_ended_now = self._consume_explore_window_expiry(state)
        decision = self.agent_orchestrator.process_turn(state=state, user_text=user_text)

        if decision.transition_from_topic_id != decision.transition_to_topic_id:
            self._append_learning_event(
                state=state,
                kind="topic_transition",
                payload={
                    "from": decision.transition_from_topic_id,
                    "to": decision.transition_to_topic_id,
                    "trace": decision.routing.trace,
                },
            )

        if decision.should_answer_directly:
            earned_points = max(0, decision.earned_points)
            if earned_points:
                state.learning.total_score += earned_points
            if decision.proposal is not None:
                self._upsert_graph_proposal(state=state, proposal=decision.proposal)
                self._append_learning_event(
                    state=state,
                    kind="graph_proposal",
                    payload={
                        "proposal_id": decision.proposal.proposal_id,
                        "title": decision.proposal.title,
                        "status": decision.proposal.status.value,
                        "reason": decision.proposal.reason,
                        "created_topic_id": decision.proposal.created_topic_id,
                    },
                )
            self.save_app_state(state)
            self._append_decision_log(
                intent=UserIntent.SUBMIT_ANSWER,
                action_kind="AGENT_DIRECT_REPLY",
                trace=decision.routing.trace,
            )
            reply_text = decision.reply_hint or "这个问题很有趣，我们先记下来，稍后深入探索。"
        else:
            self.save_app_state(state)
            reply_text, earned_points = self.evaluate_student_answer(user_text)
            if decision.reply_hint:
                reply_text = f"{decision.reply_hint}\n\n{reply_text}"

        if window_ended_now:
            reply_text = f"探索时间结束啦，我们回到主线继续学习。\n\n{reply_text}"

        reply_audio = self.synthesize_reply_audio(reply_text)
        return reply_text, earned_points, reply_audio

    def _save_audio_artifact(self, audio_bytes: bytes, *, bucket: str, suffix: str) -> Path | None:
        if not audio_bytes:
            return None

        try:
            bucket_dir = self.audio_artifact_root / bucket
            bucket_dir.mkdir(parents=True, exist_ok=True)
            file_name = f"{bucket}_{int(time.time() * 1000)}{suffix}"
            file_path = bucket_dir / file_name
            file_path.write_bytes(audio_bytes)
            return file_path
        except Exception as exc:
            print(f"音频保存失败: {exc}")
            return None

    def generate_proactive_question(self) -> str:
        state = self.load_app_state()
        topic_title = state.curriculum.topics[0].title if state.curriculum.topics else "新知识"
        return f"准备好探索【{topic_title}】了吗？看视频的时候要仔细哦，一会我要考考你！"

    def evaluate_student_answer(self, user_text: str) -> tuple[str, int]:
        state = self.load_app_state()
        question = state.learning.pending_question or PendingQuestion(question_id="demo_q_01", stem="恐龙为什么会灭绝？", expected_format="open")
        topic_id = state.learning.current_topic_id or question.question_id
        try:
            eval_result = self.llm_skill.evaluate_answer(question=question, user_answer=user_text)
            is_correct = eval_result.is_correct
            state.learning.last_evaluation = eval_result
            reply_text = getattr(eval_result, "feedback_text", "说得太棒了！" if is_correct else "差一点点，再想想？") 
        except Exception as exc:
            print(f"[SessionBackend] 评估失败，启用兜底: {exc}")
            is_correct = "陨石" in user_text or "火山" in user_text
            reply_text = "有道理！跟陨石或火山有关哦！" if is_correct else "好像不太对，是不是跟陨石有关？"

        self._apply_answer_outcome(state=state, question=question, is_correct=is_correct)
        earned_points = 20 if is_correct else 5
        state.learning.total_score += earned_points

        mastery_update = self.mastery_engine.update_from_answer(
            state=state.learning,
            topic_id=topic_id,
            user_text=user_text,
            is_correct=is_correct,
        )
        if mastery_update.mastered_now:
            reply_text = f"{reply_text}\n\n你已经开始会结合应用这个知识点了！"

        if mastery_update.should_open_explore_window:
            self._open_explore_window(state)
            reply_text = f"{reply_text}\n\n🎁 奖励时间开启：接下来 {self.explore_window_minutes} 分钟你可以自由探索提问。"

        if self.agent_orchestrator is not None:
            promoted = self.agent_orchestrator.curator.promote_shadow_topic(
                topic_id=topic_id,
                curriculum=state.curriculum,
                mastery_map=state.learning.mastery_map,
            )
            if promoted:
                reply_text = f"{reply_text}\n\n你已经把这个新知识点学稳了，我已将它转入主学习网。"
                self._mark_proposal_active_for_topic(state=state, topic_id=topic_id)
                self._append_learning_event(
                    state=state,
                    kind="graph_promotion",
                    payload={"topic_id": topic_id, "to": "active"},
                )

        decision = self.engine.evaluate(
            state=state.learning,
            curriculum=state.curriculum,
            intent=UserIntent.SUBMIT_ANSWER,
            user_answer_text=user_text,
        )
        if decision.state_delta.patch_learning:
            for k, v in decision.state_delta.patch_learning.items():
                setattr(state.learning, k, v)

        self._append_decision_log(
            intent=UserIntent.SUBMIT_ANSWER,
            action_kind=str(decision.action.kind),
            trace=decision.trace,
        )
        self._append_learning_event(
            state=state,
            kind="mastery_update",
            payload={
                "topic_id": topic_id,
                "mastered_now": mastery_update.mastered_now,
                "true_mastered_now": mastery_update.true_mastered_now,
                "open_explore_window": mastery_update.should_open_explore_window,
            },
        )
        self.save_app_state(state)
        return reply_text, earned_points

    @staticmethod
    def _apply_answer_outcome(*, state: AppState, question: PendingQuestion, is_correct: bool) -> None:
        if is_correct:
            state.learning.consecutive_correct += 1
            state.learning.consecutive_wrong = 0
            return

        state.learning.consecutive_wrong += 1
        state.learning.consecutive_correct = 0
        existing_ids = [e.topic_id for e in state.learning.error_book]
        if question.question_id not in existing_ids:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            state.learning.error_book.append(
                ErrorRecord(topic_id=question.question_id, stem=question.stem, first_error_time=now_str)
            )

    def _append_decision_log(self, *, intent: UserIntent, action_kind: str, trace: str) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            log_entry = {"intent": str(intent), "action_kind": action_kind, "trace": trace}
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def _append_learning_event(self, *, state: AppState, kind: str, payload: dict[str, object]) -> None:
        event = LearningEvent(
            ts=datetime.datetime.now(timezone.utc).isoformat(),
            kind=kind,
            payload=payload,
        )
        state.learning.history_logs.append(event)

    def _open_explore_window(self, state: AppState) -> None:
        until = datetime.datetime.now(timezone.utc) + datetime.timedelta(minutes=max(1, self.explore_window_minutes))
        state.learning.explore_window_until = until.isoformat()

    def _upsert_graph_proposal(self, *, state: AppState, proposal) -> None:
        now = datetime.datetime.now(timezone.utc).isoformat()
        for rec in state.learning.graph_proposals:
            if rec.proposal_id == proposal.proposal_id:
                rec.status = proposal.status.value
                rec.reason = proposal.reason
                rec.created_topic_id = proposal.created_topic_id
                rec.updated_ts = now
                return

        state.learning.graph_proposals.append(
            GraphProposalRecord(
                proposal_id=proposal.proposal_id,
                title=proposal.title,
                summary=proposal.summary,
                trigger=proposal.trigger,
                parent_node_ids=list(proposal.parent_node_ids),
                edge_type=proposal.edge_type.value,
                status=proposal.status.value,
                reason=proposal.reason,
                created_topic_id=proposal.created_topic_id,
                created_ts=now,
                updated_ts=now,
            )
        )

    def _mark_proposal_active_for_topic(self, *, state: AppState, topic_id: str) -> None:
        now = datetime.datetime.now(timezone.utc).isoformat()
        for rec in state.learning.graph_proposals:
            if rec.created_topic_id == topic_id and rec.status in {"shadow", "validated", "proposed"}:
                rec.status = "active"
                rec.reason = "promoted by mastery evidence"
                rec.updated_ts = now

    def _consume_explore_window_expiry(self, state: AppState) -> bool:
        until_text = state.learning.explore_window_until
        if not until_text:
            return False

        try:
            until = datetime.datetime.fromisoformat(until_text)
        except Exception:
            state.learning.explore_window_until = None
            return True

        if until > datetime.datetime.now(timezone.utc):
            return False

        state.learning.explore_window_until = None
        self._append_learning_event(
            state=state,
            kind="explore_window_closed",
            payload={"closed_at": datetime.datetime.now(timezone.utc).isoformat()},
        )
        self.save_app_state(state)
        return True
