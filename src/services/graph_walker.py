from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend
    from src.core.models import TopicNode, GraphProposalRecord

ROOT_MARKER_TAGS = {"facet:root", "subject_root", "graph:root"}
MAX_WALK_DEPTH = 10

_SUBJECT_ROOT_TITLES: dict[str, str] = {
    "language": "语言",
    "math": "数学",
    "science": "科学",
    "physics": "物理",
    "chemistry": "化学",
    "biology": "生物",
    "history": "历史",
    "geography": "地理",
    "general": "通用",
}

_LANG_ROOT_TITLES: dict[str, str] = {
    "english": "英语",
    "chinese": "语文",
}


@dataclass
class WalkResult:
    action: str  # insert_as_child | insert_before | insert_after | link_existing | no_match
    anchor_topic_id: str | None = None
    relation: str = "part_of"
    parent_node_ids: list[str] = field(default_factory=list)
    prerequisite_node_ids: list[str] = field(default_factory=list)
    reason: str = ""


class GraphWalker:
    def __init__(self, backend: "SessionBackend", subject: str, language_id: str | None = None):
        self._backend = backend
        self._subject = subject
        self._language_id = language_id
        self._topics_cache: list[TopicNode] | None = None
        self._proposals_cache: list[GraphProposalRecord] | None = None

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
            self._proposals_cache = list(state.learning.graph_proposals)
        return self._topics_cache

    @property
    def _proposals(self) -> list["GraphProposalRecord"]:
        if self._proposals_cache is None:
            self._topics  # trigger cache load
        return self._proposals_cache  # type: ignore[return-value]

    def _topic_map(self) -> dict[str, "TopicNode"]:
        return {t.topic_id: t for t in self._topics}

    def walk_and_insert(
        self, topic_title: str, topic_description: str = ""
    ) -> WalkResult:
        root = self._find_subject_root()
        if root is None:
            return WalkResult(
                action="insert_as_child",
                reason="no subject root found",
            )

        current = root
        for depth in range(MAX_WALK_DEPTH):
            successors = self._direct_successors(current.topic_id)
            if not successors:
                return self._decide_at_leaf(
                    current=current, topic_title=topic_title,
                    topic_description=topic_description,
                )

            decision = self._llm_walk_step(
                current=current, successors=successors,
                topic_title=topic_title, topic_description=topic_description,
            )

            if decision.get("action") == "go_deeper":
                next_id = decision.get("next_node_id", "")
                if next_id:
                    next_node = self._topic_map().get(next_id)
                    if next_node is None:
                        # Fallback: match by title
                        for s in successors:
                            if s.get("topic_id") == next_id or s.get("title") == next_id:
                                next_node = self._topic_map().get(s["topic_id"])
                                break
                    if next_node is not None:
                        current = next_node
                        continue
                return WalkResult(
                    action="insert_after",
                    anchor_topic_id=current.topic_id,
                    parent_node_ids=[current.topic_id],
                    reason="go_deeper target not found, inserting as child",
                )

            if decision.get("action") == "insert_before":
                before_id = decision.get("before_node_id", "")
                if before_id and not self._topic_map().get(before_id):
                    for s in successors:
                        if s.get("topic_id") == before_id or s.get("title") == before_id:
                            before_id = s["topic_id"]
                            break
                return WalkResult(
                    action="insert_before",
                    anchor_topic_id=before_id or current.topic_id,
                    parent_node_ids=[current.topic_id],
                    prerequisite_node_ids=[before_id] if before_id else [],
                    relation="requires",
                    reason=decision.get("reason", "new topic is a prerequisite"),
                )

            if decision.get("action") == "insert_after":
                return WalkResult(
                    action="insert_after",
                    anchor_topic_id=current.topic_id,
                    parent_node_ids=[current.topic_id],
                    reason=decision.get("reason", "new topic is a child"),
                )

            if decision.get("action") == "link_existing":
                return WalkResult(
                    action="link_existing",
                    anchor_topic_id=decision.get("matched_topic_id", ""),
                    reason="concept already exists",
                )

            # no_match or unknown: insert at current level
            return WalkResult(
                action="insert_after",
                anchor_topic_id=current.topic_id,
                parent_node_ids=[current.topic_id],
                reason="no further match, inserting as child",
            )

        return WalkResult(
            action="insert_after",
            anchor_topic_id=current.topic_id if current is not None else None,
            parent_node_ids=[current.topic_id] if current is not None else [],
            reason=f"max depth {MAX_WALK_DEPTH} reached",
        )

    def _find_subject_root(self) -> "TopicNode | None":
        root_title = self._root_title().lower()
        for topic in self._topics:
            tags = getattr(topic, "tags", [])
            if topic.title.strip().lower() == root_title:
                return topic
            if any(tag in ROOT_MARKER_TAGS for tag in tags):
                subj = self._tag_value(tags, "subject:")
                if subj and self._canonical_subject(subj) == self._subject:
                    lang = self._tag_value(tags, "language:")
                    if lang is None or lang == self._language_id:
                        return topic
        return None

    def _direct_successors(self, topic_id: str) -> list[dict]:
        successors: list[dict] = []
        for topic in self._topics:
            if topic_id in topic.parent_ids or topic_id in topic.prerequisite_ids:
                successors.append(
                    {
                        "topic_id": topic.topic_id,
                        "title": topic.title,
                        "tags": topic.tags,
                        "difficulty": topic.difficulty,
                    }
                )
        for proposal in self._proposals:
            status = getattr(proposal, "status", "")
            if status in {"rejected"}:
                continue
            parent_ids = getattr(proposal, "parent_node_ids", [])
            if topic_id in parent_ids:
                successors.append(
                    {
                        "topic_id": proposal.proposal_id,
                        "title": proposal.title,
                        "tags": getattr(proposal, "tags", []),
                        "difficulty": 1,
                    }
                )
        return successors

    def _decide_at_leaf(
        self, *, current: "TopicNode", topic_title: str, topic_description: str
    ) -> WalkResult:
        if self._subject == "language":
            return WalkResult(
                action="insert_after",
                anchor_topic_id=current.topic_id,
                parent_node_ids=[current.topic_id],
                reason="language subject routes by facet",
            )
        system = (
            "你是知识图谱策展助手。当前节点已是叶子节点（无子节点），"
            "判断新 topic 应如何添加到图中。\n"
        )
        user = (
            f"当前叶子节点: {current.title}\n"
            f"新 topic: {topic_title}\n"
            f"描述: {topic_description[:500]}\n\n"
            "选项: child（子节点，新概念从此节点延伸）、prereq（前置，新概念是当前节点的前置知识）\n"
            '返回 JSON: {"action":"child|prereq"}'
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3, timeout=30.0,
            )
            raw = self._parse_llm_json(response.choices[0].message.content or "")
            action = raw.get("action", "") if isinstance(raw, dict) else ""
            if action == "prereq":
                return WalkResult(
                    action="insert_before",
                    anchor_topic_id=current.topic_id,
                    parent_node_ids=[current.topic_id],
                    prerequisite_node_ids=[current.topic_id],
                    reason="new topic is prerequisite of leaf node",
                )
        except Exception:
            pass
        return WalkResult(
            action="insert_after",
            anchor_topic_id=current.topic_id,
            parent_node_ids=[current.topic_id],
            reason="leaf node, inserting as child",
        )

    def _llm_walk_step(
        self,
        *,
        current: "TopicNode",
        successors: list[dict],
        topic_title: str,
        topic_description: str,
    ) -> dict:
        if self._subject == "language":
            return self._language_walk_step(
                current=current, successors=successors,
                topic_title=topic_title, topic_description=topic_description,
            )

        successor_text = "\n".join(
            f"  - id={s['topic_id']} title={s['title']} (tags: {s.get('tags', [])})"
            for s in successors[:20]
        )
        system = (
            "你是知识图谱遍历助手。给定当前节点和新的 topic，决定新 topic 在图中的位置。\n"
            "可能的决定：\n"
            "- go_deeper: 新 topic 是某个后继的子概念或细分知识点，应继续向下遍历\n"
            "- insert_before: 新 topic 是某个后继的前置知识（需要先学会新 topic 才能学该后继）\n"
            "- insert_after: 新 topic 与后继们平级，作为当前节点的新子节点\n"
            "- link_existing: 新 topic 与某个后继是同一概念（仅标题表述不同），不要创建重复\n"
            "- no_match: 无法判断，插入为当前节点的新子节点\n\n"
            "【层级判断规则】\n"
            "- 如果新 topic 是某个后继的更细粒度版本（如「凸透镜」是「透镜」的子类），选 go_deeper\n"
            "- 如果新 topic 和后继是不同的同级知识点（如「加法」和「乘法」都是「算术」的子节点），选 insert_after\n"
            "- 如果新 topic 是学习某个后继之前必须先掌握的（如「数数」是「加法」的前置），选 insert_before\n\n"
            f"学科: {self._subject}\n"
        )
        user = (
            f"当前节点: {current.title} (tags: {current.tags})\n"
            f"新 topic: {topic_title}\n"
            f"新 topic 描述: {topic_description[:500]}\n\n"
            f"当前节点的直接后继:\n{successor_text}\n\n"
            "决定:\n"
            '返回 JSON: {"action":"go_deeper|insert_before|insert_after|link_existing|no_match",'
            '"next_node_id":"...", "before_node_id":"...", "matched_topic_id":"...",'
            '"reason":"..."}'
        )
        return self._call_llm(system, user)

    def _language_walk_step(
        self,
        *,
        current: "TopicNode",
        successors: list[dict],
        topic_title: str,
        topic_description: str,
    ) -> dict:
        successor_text = "\n".join(
            f"  - id={s['topic_id']} title={s['title']} (tags: {s.get('tags', [])})"
            for s in successors[:20]
        )
        system = (
            "你是语言学科知识图谱遍历助手。语言学科按 facet（能力维度）组织层级：\n"
            "grammar / vocabulary / reading / writing / functional_expression / pronunciation\n"
            "不是按概念深度，而是按能力分支。判断新 topic 属于哪个 facet 分支。\n"
            '返回 JSON: {"action":"go_deeper|insert_after|link_existing|no_match",'
            '"next_node_id":"...", "reason":"..."}'
        )
        user = (
            f"当前节点: {current.title} (tags: {current.tags})\n"
            f"新 topic: {topic_title}\n"
            f"新 topic 描述: {topic_description[:500]}\n\n"
            f"当前节点的直接后继:\n{successor_text}\n\n"
            "决定:"
        )
        return self._call_llm(system, user)

    def _call_llm(self, system: str, user: str) -> dict:
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3, timeout=30.0,
            )
            return self._parse_llm_json(response.choices[0].message.content or "")
        except Exception:
            return {"action": "no_match"}

    @staticmethod
    def _parse_llm_json(raw: str) -> dict:
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _root_title(self) -> str:
        if self._subject == "language" and self._language_id:
            return _LANG_ROOT_TITLES.get(self._language_id, "语言")
        return _SUBJECT_ROOT_TITLES.get(self._subject, "通用")

    @staticmethod
    def _tag_value(tags: list[str], prefix: str) -> str | None:
        for tag in tags:
            if tag.startswith(prefix):
                return tag.split(":", 1)[1]
        return None

    @staticmethod
    def _canonical_subject(subj: str) -> str:
        if subj in {"english", "chinese", "语文", "中文"}:
            return "language"
        return subj
