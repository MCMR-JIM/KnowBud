from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend
    from src.core.models import TopicNode


@dataclass
class GraphPosition:
    exists: bool
    node_id: str | None = None
    parent_ids: list[str] = field(default_factory=list)
    successor_ids: list[str] = field(default_factory=list)
    reason: str = ""


class GraphLocator:
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

    def locate(self, topic_title: str, topic_desc: str = "") -> GraphPosition:
        if not self._topics:
            return GraphPosition(exists=False, reason="empty graph")

        # 1. Deterministic exact-title match (no LLM, fast)
        title_lower = topic_title.strip().lower()
        for topic in self._topics:
            if topic.title.strip().lower() == title_lower:
                return GraphPosition(
                    exists=True, node_id=topic.topic_id,
                    parent_ids=list(topic.parent_ids),
                    successor_ids=self._compute_successors(topic.topic_id),
                    reason="exact title match, no LLM needed",
                )

        # 2. LLM-based position search with full compact graph snapshot
        graph_snapshot = self._build_graph_snapshot()

        system = (
            "你是知识图谱定位助手。完整图结构每条格式：[id, title, [前置节点id], [后继节点id]]\n"
            "判断新 topic 是否已存在（标题语义等价），或应放在图中的什么位置。\n"
            f"学科: {self._subject}\n"
            '返回 JSON: {"exists":bool,"node_id":string|null,'
            '"parent_ids":[string],"successor_ids":[string],"reason":string}'
        )
        user = (
            f"图结构:\n{graph_snapshot}\n\n"
            f"新 topic: {topic_title}\n"
            f"描述: {topic_desc[:500]}\n"
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
            return self._parse_position(raw)
        except Exception:
            return GraphPosition(exists=False, reason="LLM call failed")

    def _compute_successors(self, tid: str) -> list[str]:
        return [t.topic_id for t in self._topics if tid in t.prerequisite_ids]

    def _build_graph_snapshot(self) -> str:
        topic_ids = {t.topic_id for t in self._topics}
        nodes = []
        for topic in self._topics:
            nodes.append([
                topic.topic_id,
                topic.title,
                [p for p in topic.parent_ids if p in topic_ids],
                self._compute_successors(topic.topic_id),
            ])
        return json.dumps(nodes, ensure_ascii=False)

    @staticmethod
    def _parse_position(raw: str) -> GraphPosition:
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return GraphPosition(exists=False, reason="unexpected LLM response format")
            return GraphPosition(
                exists=bool(data.get("exists", False)),
                node_id=data.get("node_id"),
                parent_ids=data.get("parent_ids") or [],
                successor_ids=data.get("successor_ids") or [],
                reason=str(data.get("reason", "")),
            )
        except json.JSONDecodeError:
            return GraphPosition(exists=False, reason="LLM response parse failed")
