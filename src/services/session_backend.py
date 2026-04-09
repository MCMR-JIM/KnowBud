import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

<<<<<<< HEAD
# 导入我们的核心大脑和模型
from src.core.enums import UserIntent
from src.core.models import AppState, UserProfile, LearningState, CurriculumConfig, TopicNode
from src.core.decision_engine import DecisionEngine

# ==========================================
# 1. 定义发给前端 UI 的“数据包裹”
# ==========================================
@dataclass
class UIRenderBundle:
    """前端只负责渲染这个包裹里的内容，绝对不能包含复杂的业务逻辑"""
    play_path: Path | None = None
    audio_bytes: bytes | None = None
    show_question: object | None = None  # 展示题目
    messages: list[str] = field(default_factory=list) # 要在界面上显示的文字提示


# ==========================================
# 2. 后端大管家
# ==========================================
class SessionBackend:
    """唯一编排者：串联大模型、决策引擎、本地资源，并管理状态存档"""
    
    def __init__(self) -> None:
        # 加载 .env 文件里的配置
        load_dotenv()
        
        # 准备文件路径
        self.state_file = Path(os.getenv("STATE_FILE", "./data/state.json"))
        self.log_file = Path(os.getenv("DECISION_LOG_FILE", "./logs/decision_trace.jsonl"))
        
        # 把“大脑”请进办公室
        fail_th = int(os.getenv("FSM_FAIL_THRESHOLD", "3"))
        master_st = int(os.getenv("FSM_MASTER_STREAK", "3"))
        self.engine = DecisionEngine(fail_threshold=fail_th, master_streak=master_st)

    def load_app_state(self) -> AppState:
        """从磁盘读取进度。如果是第一次玩，就新建一个默认进度。"""
=======
# 引入核心模型与大脑
from src.core.enums import UserIntent, LearningPhase
from src.core.models import AppState, UserProfile, LearningState, CurriculumConfig, TopicNode, PendingQuestion
from src.core.decision_engine import DecisionEngine

# 引入技能插件 (你的手脚和耳目)
from src.skills.base_skill import SkillContext
from src.skills.voice_io_skill import VoiceIOSkill
from src.skills.llm_tutor_skill import LLMTutorSkill

@dataclass
class UIRenderBundle:
    play_path: Path | None = None
    audio_bytes: bytes | None = None
    show_question: object | None = None
    messages: list[str] = field(default_factory=list)

class SessionBackend:
    """系统大管家：负责协调前端、大脑(状态机)、耳朵(Voice)和老师(LLM)"""
    
    def __init__(self) -> None:
        load_dotenv()
        self.state_file = Path(os.getenv("STATE_FILE", "./data/state.json"))
        self.log_file = Path(os.getenv("DECISION_LOG_FILE", "./logs/decision_trace.jsonl"))
        
        # ⚠️ 关键修改 1：为了实现你的“正确答案就是一个完整闭环”，把通关连对次数强制设为 1
        fail_th = int(os.getenv("FSM_FAIL_THRESHOLD", "3"))
        master_st = 1 # 只要答对1次，直接进入MASTERED状态
        self.engine = DecisionEngine(fail_threshold=fail_th, master_streak=master_st)

        # ⚠️ 关键修改 2：把你的技能插件实例化 (调度对接点)
        self.ctx = SkillContext(data_root=Path("./data"))
        self.voice_skill = VoiceIOSkill(self.ctx, whisper_model_size="base")
        self.llm_skill = LLMTutorSkill(
            self.ctx, 
            api_key=os.getenv("OPENAI_API_KEY", "你的默认KEY"), 
            base_url=os.getenv("OPENAI_BASE_URL", "你的默认URL"), 
            model="你的模型名字(比如qwen2.5)"
        )

    def load_app_state(self) -> AppState:
>>>>>>> 02bbe3e38b8e9e5b531c4a10ae0fc0ed4fca0744
        if self.state_file.exists():
            try:
                content = self.state_file.read_text(encoding="utf-8")
                return AppState.model_validate_json(content)
            except Exception as e:
<<<<<<< HEAD
                print(f"[警告] 读取 state.json 失败，将重置进度: {e}")
        
        # 第一次启动，给一个初始的空状态
        return AppState(
            profile=UserProfile(student_id="user_01", display_name="演示同学"),
            learning=LearningState(current_phase="NOT_STARTED"),
            curriculum=CurriculumConfig(
                topics=[
                    TopicNode(
                        topic_id="topic_demo_01", 
                        title="第一课：认识新世界", 
                        difficulty=1, 
                        prerequisite_ids=[], 
                        tags=["demo"]
                    )
                ]
=======
                print(f"读取存档异常: {e}")
        
        # 默认存档
        return AppState(
            profile=UserProfile(student_id="user_01", display_name="演示同学"),
            learning=LearningState(current_phase=LearningPhase.NOT_STARTED),
            curriculum=CurriculumConfig(
                topics=[TopicNode(topic_id="demo_01", title="恐龙为什么会灭绝？", difficulty=1, prerequisite_ids=[], tags=[])]
>>>>>>> 02bbe3e38b8e9e5b531c4a10ae0fc0ed4fca0744
            )
        )

    def save_app_state(self, state: AppState) -> None:
<<<<<<< HEAD
        """
        原子写存档：先写到一个临时文件，写完再替换真文件。
        防止写到一半断电，导致整个存档坏掉。
        """
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_file.with_suffix(".tmp")
        
        with open(tmp_file, "w", encoding="utf-8") as f:
            # indent=2 让存下来的 JSON 文件是格式化排版的，方便人看
            f.write(state.model_dump_json(indent=2))
            
        # 替换原文件
        tmp_file.replace(self.state_file)

    def handle_text_event(self, intent: UserIntent, text: str | None = None) -> UIRenderBundle:
        """
        核心中枢：处理用户的文字/点击事件。
        目前是一个骨架版本，主要验证大脑逻辑和存档机制。
        """
        # 1. 读档
        state = self.load_app_state()
        
        # 2. 让大脑做决定
        decision = self.engine.evaluate(
            state=state.learning,
            curriculum=state.curriculum,
            intent=intent,
            user_answer_text=text
        )
        
        # 3. 记录大脑的思考轨迹到日志文件 (给 Admin 用的 trace)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            log_entry = {
                "intent": intent,
                "action_kind": decision.action.kind,
                "trace": decision.trace
            }
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        # 4. 根据大脑的要求，修改学习进度
        if decision.state_delta.patch_learning:
            for k, v in decision.state_delta.patch_learning.items():
                setattr(state.learning, k, v)
        
        # 5. 存档
        self.save_app_state(state)
        
        # 6. 打包要让前端显示的内容
        bundle = UIRenderBundle()
        bundle.messages.append(f"系统动作: {decision.action.kind}")
        bundle.messages.append(f"内部思考: {decision.trace}")
        
        return bundle
=======
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))
        tmp_file.replace(self.state_file)

    # ⚠️ 关键修改 3：新增处理语音的方法
    def handle_audio_upload(self, audio_bytes: bytes) -> UIRenderBundle:
        """调度流程：前端发来录音 -> Voice插件听写 -> 转交文字处理流程"""
        if not audio_bytes:
            return UIRenderBundle()
            
        print("[管家] 正在调用 VoiceIOSkill 识别语音...")
        # 1. 调用耳朵
        transcribed_text = self.voice_skill.transcribe(audio_bytes)
        print(f"[管家] 识别出文字: {transcribed_text}")
        
        # 2. 识别出来后，就当做用户手敲了文字一样，去走文字判题流程
        if transcribed_text:
            return self.handle_text_event(intent=UserIntent.SUBMIT_ANSWER, text=transcribed_text)
        return UIRenderBundle()

    def handle_text_event(self, intent: UserIntent, text: str | None = None) -> UIRenderBundle:
        state = self.load_app_state()

        # ⚠️ 关键修改 4：真实的大模型批改对接
        if state.learning.current_phase == LearningPhase.PRACTICING and intent == UserIntent.SUBMIT_ANSWER and text:
            # 伪造一个当前题目（实际应从 state.learning.pending_question 取）
            dummy_q = PendingQuestion(question_id="1", stem="恐龙为什么会灭绝？", expected_format="open")
            
            print(f"[管家] 正在调用 LLMTutorSkill 批改答案: {text}...")
            
            # --- 真实调用大模型 (如果你配好了 .env 里的 KEY) ---
            try:
                # 调度老师(LLM)去批改
                eval_result = self.llm_skill.evaluate_answer(question=dummy_q, user_answer=text)
                is_correct = eval_result.is_correct
                print(f"[管家] 大模型批改结果: 对错={is_correct}, 评语={eval_result.feedback_text}")
            except Exception as e:
                print(f"[管家] LLM调用失败，启用备用规则兜底: {e}")
                # 兜底：如果没有API Key，包含“陨石”或“火山”就算对
                is_correct = "陨石" in text or "火山" in text 

            # 根据对错更新数据
            if is_correct:
                state.learning.consecutive_correct += 1
                state.learning.consecutive_wrong = 0
            else:
                state.learning.consecutive_wrong += 1
                state.learning.consecutive_correct = 0

            self.save_app_state(state) # 存盘

        # 大脑根据刚刚更新的对错记录，决定接下来去哪个阶段
        decision = self.engine.evaluate(
            state=state.learning, curriculum=state.curriculum, intent=intent, user_answer_text=text
        )
        
        # 记录日志
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            log_entry = {"intent": intent, "action_kind": decision.action.kind, "trace": decision.trace}
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        # 应用大脑决定的阶段变化
        if decision.state_delta.patch_learning:
            for k, v in decision.state_delta.patch_learning.items():
                setattr(state.learning, k, v)
        self.save_app_state(state)
        
        return UIRenderBundle()
>>>>>>> 02bbe3e38b8e9e5b531c4a10ae0fc0ed4fca0744
