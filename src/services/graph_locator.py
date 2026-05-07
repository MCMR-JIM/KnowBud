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

    def batch_locate(self, topics: list[dict]) -> dict:
        if not self._topics or not topics:
            return {"placements": {}, "relay_nodes": []}

        graph_snapshot = self._build_graph_snapshot()
        topics_json = json.dumps(
            [{"title": t.get("title", ""), "desc": t.get("desc", "")[:500]} for t in topics],
            ensure_ascii=False,
        )
        system = (
            "你是知识图谱批量排列助手。\n"
            "现有图结构(每行格式: [id, title, [前置id], [后继id]]):\n"
            f"{graph_snapshot}\n\n"
            "待安排的新节点:\n"
            f"{topics_json}\n\n"
            "任务:\n"
            "1. 为每个新节点决定 parent_ids 和 successor_ids\n"
            "2. 如果多个新节点可被共同概念归纳，创建中继节点(标题加[中继])，挂其下\n"
            "3. 已有节点不要重复创建\n"
            "4. 每个新节点标题必须出现在 placements 中\n"
            "返回 JSON: {\"relay_nodes\":[{\"title\":\"XX[中继]\",\"children\":[\"a\",\"b\"]}],"
            "\"placements\":{\"节点标题\":{\"parent_ids\":[],\"successor_ids\":[],\"reason\":\"...\"}}}"
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "system", "content": system}],
                temperature=0.3, timeout=120.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {"placements": {}, "relay_nodes": []}
            return {
                "placements": data.get("placements") or {},
                "relay_nodes": data.get("relay_nodes") or [],
            }
        except Exception:
            return {"placements": {}, "relay_nodes": []}

    def review_placements(self, placements: dict, graph_snapshot: str | None = None) -> dict:
        if not placements:
            return {"ok": True, "issues": []}

        snap = graph_snapshot or self._build_graph_snapshot()
        placements_json = json.dumps(placements, ensure_ascii=False)
        system = (
            "你是图谱审核助手。检查节点安排是否有明显问题。\n"
            "检查规则:\n"
            "1. 节点是否归到了错误的学科分支下\n"
            "2. 前置关系是否倒置(后置概念成了前置)\n"
            "3. 节点是否挂在了不相关的父节点下\n"
            "不要求完美，只标记明显不合理处。\n"
            "返回 JSON: {\"ok\":bool,\"issues\":[{\"title\":\"...\",\"problem\":\"...\",\"suggestion\":\"...\"}]}"
        )
        user = f"图结构:\n{snap}\n\n安排结果:\n{placements_json}\n请审核。"
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.2, timeout=60.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            if isinstance(data, dict):
                return {"ok": bool(data.get("ok", True)), "issues": data.get("issues") or []}
            return {"ok": True, "issues": []}
        except Exception:
            return {"ok": True, "issues": []}

    def _compute_successors(self, tid: str) -> list[str]:
        return [t.topic_id for t in self._topics if tid in t.prerequisite_ids]

    def refresh(self) -> None:
        self._topics_cache = None

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
