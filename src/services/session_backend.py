import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

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
        if self.state_file.exists():
            try:
                content = self.state_file.read_text(encoding="utf-8")
                return AppState.model_validate_json(content)
            except Exception as e:
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
            )
        )

    def save_app_state(self, state: AppState) -> None:
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