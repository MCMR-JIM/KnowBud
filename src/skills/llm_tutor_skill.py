from __future__ import annotations

import json
import httpx  # 🚀 新增这一行：用于配置底层网络
from typing import Optional

from pydantic import BaseModel, ValidationError
from openai import OpenAI

from src.skills.base_skill import BaseSkill, SkillContext
from src.core.models import PendingQuestion, EvaluationResult, RadarScore, TopicNode


class ResourceChunkClassification(BaseModel):
    topic_id: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""

class LLMTutorSkill(BaseSkill):
    """大模型导师技能：负责根据知识点出题，以及批改儿童的答案"""
    
    name = "LLMTutorSkill"
    version = "1.1.0" 

    def __init__(self, ctx: SkillContext, *, api_key: str, base_url: str, model: str) -> None:
        self.ctx = ctx
        self.model_name = model

        # 在不同 httpx 版本下统一关闭环境代理，避免本机代理影响请求。
        self.client = OpenAI(
            api_key=api_key, 
            base_url=base_url,
            http_client=self._build_http_client()
        )

    @staticmethod
    def _build_http_client() -> httpx.Client:
        try:
            return httpx.Client(trust_env=False)
        except TypeError:
            return httpx.Client()

    # ... 下面的 analyze_session_performance 等方法保持原样不动 ...

    # 🚀 新增功能：根据对话历史，动态生成 AI 多维学情雷达图数据
    def analyze_session_performance(self, chat_history_text: str) -> RadarScore:
        """根据历史对话记录，利用 LLM 分析出 5 个维度的雷达图数据"""
        system_prompt = (
            "你是一个资深的儿童心理学和教育学专家。请根据以下儿童与AI伙伴的对话记录，评估儿童在本次学习中的表现。\n"
            "【严禁废话】必须且只能输出合法的 JSON 格式，不要用 ```json 包裹。\n"
            "JSON 结构必须严格遵守以下5个维度，每个维度的分数为 0 到 100 的整数（最低不低于50分，保护儿童自尊）：\n"
            "{\n"
            '  "focus": 85,        // 专注度（是否认真听讲、不跑题）\n'
            '  "activeness": 90,   // 提问积极性（是否主动交互）\n'
            '  "logic": 75,        // 逻辑理解力（回答是否切题、有条理）\n'
            '  "mastery": 80,      // 知识掌握度（是否答对核心知识点）\n'
            '  "emotion": 95       // 情绪稳定性（是否有挫败感或负面情绪）\n'
            "}"
        )
        user_prompt = f"对话记录如下：\n{chat_history_text}\n请给出评分 JSON。"

        # 兜底数据：网络断了或大模型抽风时的默认优秀表现
        fallback = RadarScore(focus=80, activeness=85, logic=75, mastery=80, emotion=90)

        return self._call_and_parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_class=RadarScore,
            fallback_obj=fallback
        )

    def generate_question(self, *, topic_id: str, topic_title: str, difficulty: int) -> PendingQuestion:
        system_prompt = (
            "你是一个优秀的儿童家庭教师。请根据指定的知识点出一道练习题。\n"
            "【严禁废话】必须且只能输出合法的 JSON 格式，不要用 ```json 包裹。\n"
            "JSON 结构必须符合以下形式：\n"
            "{\n"
            '  "question_id": "随便生成一个唯一ID",\n'
            '  "stem": "题干内容，要通俗易懂",\n'
            '  "choices": ["选项A", "选项B"] (如果是选择题) 或者 null (如果开放问答),\n'
            '  "expected_format": "open" 或 "single_choice" 或 "multi_choice"\n'
            "}"
        )
        user_prompt = f"请出题。知识点：{topic_title} (ID:{topic_id}), 难度：{difficulty}。"

        return self._call_and_parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_class=PendingQuestion,
            fallback_obj=None
        )

    def evaluate_answer(self, *, question: PendingQuestion, user_answer: str) -> EvaluationResult:
        system_prompt = (
            "你是一个富有耐心的儿童老师。请批改学生的答案。\n"
            "【严禁废话】必须且只能输出合法的 JSON 格式，不要用 ```json 包裹。\n"
            "JSON 结构必须包含以下字段：\n"
            "{\n"
            '  "is_correct": true 或 false,\n'
            '  "error_type": "错误类型，比如 concept(概念错误) 或 null",\n'
            '  "feedback_text": "用温柔、鼓励的语气给儿童看的简短评语"\n'
            "}"
        )
        user_prompt = f"题目：{question.stem}\n学生回答：{user_answer}\n请批改。"
        
        fallback = EvaluationResult(
            is_correct=False,
            error_type="expression",
            feedback_text="哎呀，网络小精灵走神了，你能再说一遍吗？"
        )

        return self._call_and_parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_class=EvaluationResult,
            fallback_obj=fallback
        )

    def classify_resource_chunk(self, *, chunk_text: str, topics: list[TopicNode]) -> dict[str, object]:
        text = chunk_text.strip()
        fallback = ResourceChunkClassification(topic_id=None, confidence=0.0, reason="未找到合适知识点")
        if not text or not topics:
            return fallback.model_dump()

        topic_payload = [
            {
                "topic_id": topic.topic_id,
                "title": topic.title,
                "tags": topic.tags,
                "prerequisite_ids": topic.prerequisite_ids,
            }
            for topic in topics
        ]
        system_prompt = (
            "你是儿童学习资源分类器。你的任务是把教学资源片段归类到最合适的知识节点。"
            "只能使用给定知识节点，不要编造节点。若片段过泛、无法判断、或多个节点都不明确，返回 topic_id=null。\n"
            "请只返回合法 JSON，不要附加解释。"
        )
        user_prompt = (
            "给定知识节点列表：\n"
            f"{json.dumps(topic_payload, ensure_ascii=False)}\n\n"
            "待分类资源片段：\n"
            f"```text\n{text[:4000]}\n```\n"
            '请只返回 JSON：{"topic_id": string|null, "confidence": number, "reason": string}'
        )

        result = self._call_and_parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_class=ResourceChunkClassification,
            fallback_obj=fallback,
        )
        valid_topic_ids = {topic.topic_id for topic in topics}
        topic_id = result.topic_id if result.topic_id in valid_topic_ids else None
        confidence = max(0.0, min(1.0, float(result.confidence)))
        reason = (result.reason or fallback.reason).strip()[:80]
        return {
            "topic_id": topic_id,
            "confidence": confidence,
            "reason": reason,
        }

    def _call_and_parse(self, system_prompt: str, user_prompt: str, model_class, fallback_obj):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.3 
                )
                raw_content = response.choices[0].message.content.strip()
                
                if raw_content.startswith("```json"):
                    raw_content = raw_content[7:]
                if raw_content.startswith("```"):
                    raw_content = raw_content[3:]
                if raw_content.endswith("```"):
                    raw_content = raw_content[:-3]
                    
                return model_class.model_validate_json(raw_content.strip())
                
            except (ValidationError, json.JSONDecodeError) as e:
                if attempt == 0:
                    messages.append({"role": "assistant", "content": raw_content if 'raw_content' in locals() else "无输出"})
                    messages.append({"role": "user", "content": f"解析失败：{e}。请修复为合法 JSON。"})
                else:
                    print(f"[LLMTutorSkill] 连续两次解析失败，触发降级: {e}")
                    if fallback_obj is not None:
                        return fallback_obj
                    raise e
