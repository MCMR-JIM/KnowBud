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

        # Phase 1: cluster similar topics into relay groups (one LLM call)
        titles = [t.get("title", "") for t in topics]
        relay_nodes = self.cluster_into_relays(titles)

        # Phase 2: for each topic, search top-K relevant existing nodes + decide placement
        placements = {}
        for t in topics:
            title = t.get("title", "")
            desc = t.get("desc", "")
            if not title:
                continue
            # Find top-5 most relevant existing topics by title similarity
            relevant = self._search_relevant_nodes(title, limit=5)
            if not relevant:
                relevant = self._topics[:5]  # fallback: first 5 topics
            relevant_json = json.dumps(
                [[n.topic_id, n.title,
                  [p for p in n.parent_ids if p in {x.topic_id for x in self._topics}],
                  [x.topic_id for x in self._topics if n.topic_id in x.prerequisite_ids]]
                 for n in relevant],
                ensure_ascii=False,
            )
            pos = self._locate_one(title, desc, relevant_json)
            if pos:
                placements[title] = pos

        return {"placements": placements, "relay_nodes": relay_nodes}

    def _search_relevant_nodes(self, title: str, limit: int = 5) -> list["TopicNode"]:
        """Find most relevant existing topics by title substring overlap."""
        title_lower = title.lower()
        scored = []
        for topic in self._topics:
            topic_lower = topic.title.lower()
            # Simple relevance: count shared characters
            overlap = sum(1 for c in title_lower if c in topic_lower and c.isalnum())
            if overlap > 0:
                scored.append((overlap, topic))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:limit]]

    def cluster_into_relays(self, titles: list[str]) -> list[dict]:
        """One LLM call: group related titles into relay clusters."""
        if len(titles) <= 2:
            return []
        titles_json = json.dumps(titles, ensure_ascii=False)
        system = (
            "你是概念分组助手。将一组知识点标题按学科领域分组。\n"
            "每组提炼一个中继标题(加[中继]后缀)，列出组内成员。\n"
            "每组至少 3 个成员才建中继。不够 3 个的不分组。\n"
            f"学科: {self._subject}\n"
            '返回 JSON: [{"title":"XX[中继]","children":["a","b","c"]}]'
        )
        user = f"标题列表:\n{titles_json}"
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role":"system","content":system},{"role":"user","content":user}],
                temperature=0.3, timeout=60.0,
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            if isinstance(data, list):
                return _normalize_relay_nodes(data)
            return []
        except Exception:
            return []

    def _locate_one(self, title: str, desc: str, relevant_json: str) -> dict | None:
        """LLM decides parent_ids + prerequisite_for_ids from relevant nodes only."""
        system = (
            "你是知识图谱定位助手。给定新概念和一组最相关的已有节点，决定新概念的层级位置。\n"
            "格式说明: 每个已有节点为 [id, title, [前置节点id], [后继节点id]]\n\n"
            "parent_ids: 新概念挂在哪个已有节点下（不能为空，至少填根节点ID）\n"
            "prerequisite_for_ids: 哪些已有节点需要先学这个新概念才能学（新概念是它们的前置）\n"
            f"学科: {self._subject}\n"
            '返回 JSON: {"parent_ids":["id"],"prerequisite_for_ids":["id"],"reason":"..."}'
        )
        user = (
            f"最相关的已有节点:\n{relevant_json}\n\n"
            f"新概念: {title}\n描述: {desc[:500]}"
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role":"system","content":system},{"role":"user","content":user}],
                temperature=0.3, timeout=30.0,
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def review_placements(self, placements: dict, graph_snapshot: str | None = None) -> dict:
        if not placements:
            return {"ok": True, "issues": []}

        snap = graph_snapshot or self._build_graph_snapshot()
        placements_json = json.dumps(placements, ensure_ascii=False)
        system = (
            "你是图谱审核助手。检查节点安排是否有明显错误。\n"
            "只标记一眼就能看出的问题，不要求完美。\n\n"
            "【检查项】\n"
            "1. 跨学科错位：如物理概念挂到了化学节点下\n"
            "2. 前置倒置：如「加法」被标记为「乘法」的前置而非反过来\n"
            "3. 不相关父节点：如「光的折射」挂到了「力学[中继]」下\n"
            "4. 自引用：节点引用自己作为 parent 或 prerequisite_for\n\n"
            "返回 JSON: {\"ok\":bool,\"issues\":[{\"title\":\"节点标题\"}]}\n"
            "没有问题时返回 {\"ok\":true,\"issues\":[]}"
        )
        user = (
            f"=== 图结构 ===\n{snap}\n\n"
            f"=== 待审核安排 ===\n{placements_json}\n\n"
            "请审核并返回结果。"
        )
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


def _normalize_relay_nodes(relay_nodes: list) -> list[dict]:
    """Convert relay nodes from LLM response to nested dict format expected by _create_relay_and_attach.
    LLM returns [{"title":"XX[中继]","children":["a","b"]}] (string children).
    We need [{"title":"XX[中继]","children":[{"title":"a","children":[]}]}]."""
    normalized = []
    for node in relay_nodes:
        if isinstance(node, str):
            normalized.append({"title": node, "children": []})
        elif isinstance(node, dict):
            children = node.get("children") or []
            norm_children = []
            for child in children:
                if isinstance(child, str):
                    norm_children.append({"title": child, "children": []})
                elif isinstance(child, dict):
                    norm_children.append(_normalize_relay_nodes([child])[0])
            normalized.append({
                "title": node.get("title", ""),
                "children": norm_children,
            })
    return normalized
