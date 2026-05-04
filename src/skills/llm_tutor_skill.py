from __future__ import annotations

import json
import httpx  # 🚀 新增这一行：用于配置底层网络
from typing import Optional

from pydantic import BaseModel, Field, ValidationError
from openai import OpenAI

from src.skills.base_skill import BaseSkill, SkillContext
from src.agent.models import EdgeType
from src.core.models import PendingQuestion, EvaluationResult, RadarScore, TopicNode


class ResourceChunkClassification(BaseModel):
    topic_id: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""


class ProposedTopicPayload(BaseModel):
    title: str = ""
    summary: str = ""
    parent_node_ids: list[str] = Field(default_factory=list)
    edge_type: str = "requires"


class ResourceChunkProposalDecision(BaseModel):
    decision: str = "unclassified"
    topic_id: Optional[str] = None
    confidence: float = 0.0
    reason: str = "未找到合适知识点"
    proposed_topic: Optional[ProposedTopicPayload] = None
    guiding_question: str = ""
    teaching_hint: str = ""

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
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
        try:
            return httpx.Client(timeout=timeout, trust_env=False)
        except TypeError:
            return httpx.Client(timeout=timeout)

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
        result = self.classify_or_propose_resource_chunk(chunk_text=chunk_text, topics=topics)
        return {
            "topic_id": result.get("topic_id"),
            "confidence": result.get("confidence", 0.0),
            "reason": result.get("reason", "未找到合适知识点"),
        }

    def classify_or_propose_resource_chunk(
        self,
        *,
        chunk_text: str,
        topics: list[TopicNode],
        default_parent_topic_id: str | None = None,
    ) -> dict[str, object]:
        text = chunk_text.strip()
        fallback = ResourceChunkProposalDecision()
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
            "你是儿童学习知识图谱策展助手。你的任务是判断一个教学资源片段应该挂到已有知识节点，"
            "还是应该提出一个新知识节点。只能复用给定的已有节点；如果没有合适节点，但片段表达了明确、"
            "可教学的知识点，请提出新节点。不要为了泛泛内容创建节点。"
        )
        user_prompt = (
            "给定已有知识节点列表：\n"
            f"{json.dumps(topic_payload, ensure_ascii=False)}\n\n"
            "默认父节点：\n"
            f"{json.dumps(default_parent_topic_id, ensure_ascii=False)}\n\n"
            "待处理资源片段：\n"
            f"```text\n{text[:4000]}\n```\n"
            '只返回 JSON：{ "decision": "link" | "propose" | "unclassified", "topic_id": string|null, '
            '"confidence": number, "reason": string, "proposed_topic": { "title": string, '
            '"summary": string, "parent_node_ids": [string], "edge_type": "requires" | "supports" | "related" | "part_of" | "derived_from" | "defines" | "explains" | "evidence_for" | "causes" | "uses" | "formula_uses_quantity" } | null, '
            '"guiding_question": string, "teaching_hint": string }\n'
            "guiding_question 是老师可以直接用来引出学习的儿童友好问题，不超过 60 字。"
            "teaching_hint 是老师讲解该片段的简短提示，不超过 80 字。"
        )

        result = self._call_and_parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_class=ResourceChunkProposalDecision,
            fallback_obj=fallback,
        )
        return self._sanitize_resource_chunk_decision(
            result=result,
            topics=topics,
            default_parent_topic_id=default_parent_topic_id,
        )

    def _sanitize_resource_chunk_decision(
        self,
        *,
        result: ResourceChunkProposalDecision,
        topics: list[TopicNode],
        default_parent_topic_id: str | None,
    ) -> dict[str, object]:
        valid_topic_ids = {topic.topic_id for topic in topics}
        allowed_decisions = {"link", "propose", "unclassified"}
        allowed_edge_types = {item.value for item in EdgeType}

        decision = result.decision if result.decision in allowed_decisions else "unclassified"
        topic_id = result.topic_id if result.topic_id in valid_topic_ids else None
        try:
            confidence = max(0.0, min(1.0, float(result.confidence)))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = (result.reason or "未找到合适知识点").strip()[:80]
        guiding_question = (result.guiding_question or "").strip()[:60]
        teaching_hint = (result.teaching_hint or "").strip()[:80]

        proposed_topic: dict[str, object] | None = None
        if decision == "propose" and result.proposed_topic is not None:
            title = result.proposed_topic.title.strip()
            summary = result.proposed_topic.summary.strip()
            parent_node_ids = [
                parent_id for parent_id in result.proposed_topic.parent_node_ids if parent_id in valid_topic_ids
            ]
            if not parent_node_ids and default_parent_topic_id in valid_topic_ids:
                parent_node_ids = [default_parent_topic_id]
            edge_type = result.proposed_topic.edge_type if result.proposed_topic.edge_type in allowed_edge_types else "requires"
            if title:
                proposed_topic = {
                    "title": title,
                    "summary": summary,
                    "parent_node_ids": parent_node_ids,
                    "edge_type": edge_type,
                }

        if confidence < 0.55:
            decision = "unclassified"

        if decision == "link":
            if topic_id is None:
                decision = "unclassified"
        elif decision == "propose":
            topic_id = None
            if proposed_topic is None:
                decision = "unclassified"
        else:
            topic_id = None
            proposed_topic = None

        if decision == "unclassified":
            topic_id = None
            proposed_topic = None

        return {
            "decision": decision,
            "topic_id": topic_id,
            "confidence": confidence,
            "reason": reason,
            "proposed_topic": proposed_topic,
            "guiding_question": guiding_question,
            "teaching_hint": teaching_hint,
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
                    temperature=0.3,
                    timeout=60.0,
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
