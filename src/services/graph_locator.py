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
            "你是知识图谱批量层级排列助手。你的任务是为一组新概念在图中找到层级归属。\n\n"
            "【图结构格式说明】\n"
            "现有图每条格式: [节点ID, 节点标题, [前置节点ID列表], [后继节点ID列表]]\n"
            "例如: [\"light\",\"光学[中继]\",[\"root\"],[\"refraction\",\"reflection\"]]\n"
            "      表示\"光学[中继]\"的前置节点是\"root\"，后继节点是\"refraction\"和\"reflection\"\n\n"
            "【parent_ids 说明】\n"
            "parent_ids 是层级父节点列表——新节点挂在谁下面。\n"
            "例如新节点「牛顿第二定律」的 parent_ids 应该是[\"力学[中继]\"]或直接父节点ID。\n"
            "如果新节点无法确定父节点，parent_ids 填根节点ID（如[\"root\"]）。\n"
            "如果新节点是某个已有节点的细分知识，parent_ids 填那个已有节点的ID。\n\n"
            "【prerequisite_for_ids 说明】\n"
            "prerequisite_for_ids 表示哪些已有节点需要先学了这个新节点才能学。\n"
            "例如新节点「欧姆定律」→ prerequisite_for_ids=[\"串联电路规律\"]\n"
            "    表示学习串联电路规律之前必须先学会欧姆定律。\n"
            "如果没有合适的后置节点，填空数组[]。\n\n"
            "【中继节点说明】\n"
            "如果 3 个以上新节点可被共同概念归纳，创建一个中继节点。\n"
            "中继节点标题必须以[中继]结尾，如\"牛顿运动定律[中继]\"。\n"
            "children 列表填这些新节点的标题（字符串），不是ID。\n\n"
            f"【当前学科】{self._subject}\n"
            "返回严格 JSON: {\"relay_nodes\":[{\"title\":\"XX[中继]\",\"children\":[\"子节点标题1\",\"子节点标题2\"]}],"
            "\"placements\":{\"新节点标题\":{\"parent_ids\":[\"父节点ID\"],\"prerequisite_for_ids\":[\"后置节点ID\"],\"reason\":\"简短理由\"}}}"
        )
        user = (
            f"=== 现有图结构 ===\n{graph_snapshot}\n\n"
            f"=== 待安排的新节点 ===\n{topics_json}\n\n"
            "请为每个新节点填入层级归属(parent_ids)和前置关系(prerequisite_for_ids)。"
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3, timeout=120.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {"placements": {}, "relay_nodes": []}
            result = {
                "placements": {
                    k: v for k, v in (data.get("placements") or {}).items()
                    if isinstance(v, dict)
                },
                "relay_nodes": _normalize_relay_nodes(data.get("relay_nodes") or []),
            }
            return result
        except Exception:
            return {"placements": {}, "relay_nodes": []}

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
