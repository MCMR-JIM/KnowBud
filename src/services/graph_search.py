from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.services.resource_graph_curation import (
    _contains_cjk,
    _facet_from_tags,
    _language_id_from_tags,
    _subject_from_tags,
)

if TYPE_CHECKING:
    from src.core.models import TopicNode
    from src.services.session_backend import SessionBackend


@dataclass
class SearchResult:
    decision: str  # "link" | "propose" | "ambiguous"
    matched_topic_id: str | None = None
    matched_title: str | None = None
    parent_node_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    proposed_title: str | None = None


class GraphSearchAgent:
    MAX_TOOL_ROUNDS = 5

    def __init__(self, backend: "SessionBackend", subject: str, language_id: str | None = None):
        self._backend = backend
        self._subject = subject
        self._language_id = language_id
        self._topics_cache: list[TopicNode] | None = None

    @property
    def _client(self):
        return self._backend.llm_skill.client

    @property
    def _model_name(self):
        return self._backend.llm_skill.model_name

    @property
    def _topics(self) -> list["TopicNode"]:
        if self._topics_cache is None:
            state = self._backend.load_app_state(include_history=False)
            self._topics_cache = list(state.curriculum.topics)
        return self._topics_cache

    def search(self, chunk_text: str, chunk_context: str = "") -> SearchResult:
        fallback = SearchResult(
            decision="propose",
            reason="graph search agent returned no result",
        )
        try:
            messages = self._build_initial_messages(chunk_text, chunk_context)
            tools = self._build_tools_spec()
            for _ in range(self.MAX_TOOL_ROUNDS):
                response = self._client.chat.completions.create(
                    model=self._model_name,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.3,
                    timeout=60.0,
                )
                choice = response.choices[0]
                if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                    messages.append(choice.message.model_dump())
                    for tool_call in choice.message.tool_calls:
                        result = self._execute_tool(
                            tool_call.function.name,
                            tool_call.function.arguments,
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                    continue
                content = choice.message.content or ""
                return self._parse_search_result(content)
            return fallback
        except Exception as exc:
            return SearchResult(
                decision="propose",
                reason=f"graph search error: {str(exc)[:80]}",
            )

    def _build_initial_messages(self, chunk_text: str, chunk_context: str) -> list[dict]:
        language_hint = f"语言范围: {self._language_id}\n" if self._language_id else ""
        system = (
            "你是知识图谱搜索助手。给定一个文档片段，请在已有知识图谱中搜索匹配的 topic。\n"
            "你可以使用工具搜索图谱。推荐步骤：\n"
            "1. 用 list_topics_by_subject_facet 列出学科范围内的 topic\n"
            "2. 用 search_topics_by_title 按标题搜索\n"
            "3. 若找到多个候选，用 rerank_topics_by_relevance 做语义排序\n"
            "4. 用 get_topic_detail 查看详情\n"
            "5. 最后给出决策\n\n"
            "【决策规则】\n"
            "- 找到概念本质相同的 topic（标题表述可能不同）→ decision=link\n"
            "- 确实无匹配，且片段表达了明确可教学的知识点 → decision=propose\n"
            "- 泛泛内容不要创建节点，拿不准 → decision=ambiguous\n"
            "- propose 时必须给出规范化标题：去冗余前缀/后缀，保留核心术语\n\n"
            f"学科: {self._subject}\n{language_hint}"
        )
        context_block = f"上下文: {chunk_context}\n\n" if chunk_context else ""
        user = (
            f"文档片段:\n```text\n{chunk_text[:3000]}\n```\n\n"
            f"{context_block}"
            "请搜索知识图谱，判断是否已有匹配的 topic。\n"
            '只返回 JSON: {"decision":"link|propose|ambiguous","matched_topic_id":string|null,'
            '"matched_title":string|null,"parent_node_ids":[string],"confidence":number,"reason":string,'
            '"proposed_title":string|null}'
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _build_tools_spec(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_topics_by_subject_facet",
                    "description": "列出当前学科的所有 topic 节点，可按 facet 筛选",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "facet": {
                                "type": "string",
                                "description": "可选，topic 子类，如 grammar、vocabulary、reading",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_topics_by_title",
                    "description": "用模糊匹配搜索 title 中包含查询词的 topic。中文按子串匹配，英文忽略大小写",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "搜索关键词"},
                            "limit": {
                                "type": "integer",
                                "description": "最多返回多少个结果，默认 10",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rerank_topics_by_relevance",
                    "description": "给定候选 topic ID 列表和概念描述，用 LLM 判断语义匹配度并排序。relevance 取 high|medium|low，仅 high 视为匹配成功",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "candidates": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "候选 topic_id 列表",
                            },
                            "concept_description": {
                                "type": "string",
                                "description": "核心概念的描述文本",
                            },
                        },
                        "required": ["candidates", "concept_description"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_topic_detail",
                    "description": "获取指定 topic 的完整信息，含 parent_ids、tags",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic_id": {"type": "string", "description": "topic ID"},
                        },
                        "required": ["topic_id"],
                    },
                },
            },
        ]

    def _execute_tool(self, name: str, arguments: str) -> dict:
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": f"invalid arguments: {arguments}"}
        if name == "list_topics_by_subject_facet":
            return {"topics": self._list_topics_by_subject_facet(facet=args.get("facet"))}
        if name == "search_topics_by_title":
            return {
                "topics": self._search_topics_by_title(
                    query=str(args.get("query", "")),
                    limit=int(args.get("limit", 10)),
                )
            }
        if name == "rerank_topics_by_relevance":
            return {
                "topics": self._rerank_topics_by_relevance(
                    candidates=list(args.get("candidates", [])),
                    concept_description=str(args.get("concept_description", "")),
                )
            }
        if name == "get_topic_detail":
            return {"topic": self._get_topic_detail(topic_id=str(args.get("topic_id", "")))}
        return {"error": f"unknown tool: {name}"}

    def _list_topics_by_subject_facet(self, facet: str | None = None) -> list[dict]:
        results: list[dict] = []
        for topic in self._topics:
            topic_subject = _subject_from_tags(topic.tags)
            if topic_subject is not None:
                if topic_subject != self._subject and topic_subject != "general":
                    continue
            if facet is not None:
                topic_facet = _facet_from_tags(topic.tags)
                if topic_facet is not None and topic_facet != facet:
                    continue
            if self._subject == "language" and self._language_id:
                topic_lang = _language_id_from_tags(topic.tags)
                if topic_lang is not None and topic_lang != self._language_id:
                    continue
            results.append(
                {
                    "topic_id": topic.topic_id,
                    "title": topic.title,
                    "tags": topic.tags,
                    "difficulty": topic.difficulty,
                }
            )
        return results

    def _search_topics_by_title(self, query: str, limit: int = 10) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        scored: list[tuple[int, dict]] = []
        query_lower = query.lower()
        for topic in self._topics:
            title = topic.title.strip()
            title_lower = title.lower()
            info = {
                "topic_id": topic.topic_id,
                "title": topic.title,
                "tags": topic.tags,
                "difficulty": topic.difficulty,
            }
            if _contains_cjk(query):
                pos = title.find(query)
                if pos >= 0:
                    scored.append((pos, info))
            else:
                pos = title_lower.find(query_lower)
                if pos >= 0:
                    scored.append((pos, info))
                elif self._is_subsequence(query_lower, title_lower):
                    scored.append((999, info))
        scored.sort(key=lambda item: (item[0], len(item[1]["title"])))
        return [item[1] for item in scored[:limit]]

    def _rerank_topics_by_relevance(
        self, candidates: list[str], concept_description: str
    ) -> list[dict]:
        if not candidates or not concept_description.strip():
            return []
        candidate_infos: list[dict] = []
        seen: set[str] = set()
        for cid in candidates:
            if cid in seen:
                continue
            seen.add(cid)
            detail = self._get_topic_detail(cid)
            if detail:
                candidate_infos.append(
                    {"topic_id": detail["topic_id"], "title": detail["title"], "tags": detail["tags"]}
                )
        if not candidate_infos:
            return []
        capped = candidate_infos[:20]
        info_text = json.dumps(capped, ensure_ascii=False)
        system = (
            "你是语义匹配专家。判断每个候选 topic 与给定概念的语义匹配度。\n"
            "relevance 取 high|medium|low。概念本质相同（仅表述不同）→ high。\n"
            "相似但不同 → medium。不相关 → low。"
        )
        user = (
            f"概念描述: {concept_description[:500]}\n\n"
            f"候选 topic:\n{info_text}\n\n"
            '只返回 JSON 数组: [{"topic_id":"...","relevance":"high|medium|low"}]'
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                timeout=60.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            return self._parse_rerank_result(raw)
        except Exception:
            return []

    def _get_topic_detail(self, topic_id: str) -> dict | None:
        for topic in self._topics:
            if topic.topic_id == topic_id:
                return {
                    "topic_id": topic.topic_id,
                    "title": topic.title,
                    "difficulty": topic.difficulty,
                    "parent_ids": topic.parent_ids,
                    "prerequisite_ids": topic.prerequisite_ids,
                    "tags": topic.tags,
                }
        return None

    def _parse_search_result(self, raw_content: str) -> SearchResult:
        content = raw_content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        try:
            data = json.loads(content.strip())
        except json.JSONDecodeError:
            return SearchResult(decision="ambiguous", reason="output parse failed")
        decision = data.get("decision", "ambiguous")
        if decision not in {"link", "propose", "ambiguous"}:
            decision = "ambiguous"
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        return SearchResult(
            decision=decision,
            matched_topic_id=data.get("matched_topic_id"),
            matched_title=data.get("matched_title"),
            parent_node_ids=data.get("parent_node_ids") or [],
            confidence=confidence,
            reason=str(data.get("reason", ""))[:200],
            proposed_title=data.get("proposed_title"),
        )

    @staticmethod
    def _parse_rerank_result(raw: str) -> list[dict]:
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [
            item
            for item in data
            if isinstance(item, dict) and "topic_id" in item and "relevance" in item
        ]

    @staticmethod
    def _is_subsequence(query: str, text: str) -> bool:
        chars = [c for c in query if c.isalnum()]
        if not chars:
            return False
        idx = 0
        for ch in text:
            if ch == chars[idx]:
                idx += 1
                if idx >= len(chars):
                    return True
        return False
