from __future__ import annotations

import re
from uuid import uuid4

from src.agent.models import EdgeType, GraphMutationProposal, ProposalStatus
from src.core.models import CurriculumConfig, NodeMastery, TopicNode


class GraphCurator:
    _ALLOWED_PROPOSAL_TRANSITIONS: dict[ProposalStatus, set[ProposalStatus]] = {
        ProposalStatus.PROPOSED: {ProposalStatus.VALIDATED, ProposalStatus.REJECTED},
        ProposalStatus.VALIDATED: {ProposalStatus.SHADOW, ProposalStatus.REJECTED},
        ProposalStatus.SHADOW: {ProposalStatus.ACTIVE, ProposalStatus.REJECTED},
        ProposalStatus.ACTIVE: set(),
        ProposalStatus.REJECTED: set(),
    }

    def __init__(
        self,
        *,
        shadow_promote_depth: int = 2,
        shadow_promote_success_count: int = 2,
        shadow_promote_stability: int = 1,
        allow_cross_subject_requires: bool = False,
    ) -> None:
        self.shadow_promote_depth = max(0, shadow_promote_depth)
        self.shadow_promote_success_count = max(1, shadow_promote_success_count)
        self.shadow_promote_stability = max(0, shadow_promote_stability)
        self.allow_cross_subject_requires = allow_cross_subject_requires

    def propose_from_question(
        self,
        *,
        question_text: str,
        current_topic_id: str | None,
        topics: list[TopicNode] | None = None,
    ) -> GraphMutationProposal:
        title = self._summarize_title(question_text)
        parent_ids = self._pick_parent_ids(
            question_text=question_text,
            current_topic_id=current_topic_id,
            topics=topics or [],
        )
        return GraphMutationProposal(
            proposal_id=uuid4().hex,
            trigger="unknown_question",
            title=title,
            summary=question_text[:120],
            parent_node_ids=parent_ids,
            edge_type=EdgeType.REQUIRES,
            status=ProposalStatus.PROPOSED,
            reason="question cannot be mapped to existing topic with high confidence",
        )

    def propose_mastery_followups(
        self,
        *,
        topic: TopicNode,
        curriculum: CurriculumConfig,
        limit: int = 1,
    ) -> list[GraphMutationProposal]:
        if limit <= 0:
            return []

        variants = [
            f"{topic.title}进阶应用",
            f"{topic.title}综合迁移",
            f"{topic.title}关联拓展",
        ]
        proposals: list[GraphMutationProposal] = []
        for variant in variants:
            if len(proposals) >= limit:
                break
            if self._is_exact_duplicate_title(variant, curriculum.topics):
                continue
            proposals.append(
                GraphMutationProposal(
                    proposal_id=uuid4().hex,
                    trigger="mastery_expand",
                    title=variant,
                    summary=f"auto expand from mastered topic: {topic.title}",
                    parent_node_ids=[topic.topic_id],
                    edge_type=EdgeType.REQUIRES,
                    status=ProposalStatus.PROPOSED,
                    reason="topic reached true mastery; propose advanced branch",
                )
            )
        return proposals

    def auto_review_and_apply(self, *, proposal: GraphMutationProposal, curriculum: CurriculumConfig) -> tuple[bool, str | None]:
        if proposal.status != ProposalStatus.PROPOSED:
            return False, None

        if not self._passes_granularity(proposal.title):
            self._transition_proposal(proposal, to_status=ProposalStatus.REJECTED, reason="invalid topic granularity")
            return False, None

        duplicate_checker = self._is_exact_duplicate_title if proposal.trigger == "mastery_expand" else self._is_duplicate_title
        if duplicate_checker(proposal.title, curriculum.topics):
            self._transition_proposal(proposal, to_status=ProposalStatus.REJECTED, reason="duplicated title")
            return False, None

        if not self._parents_exist(proposal.parent_node_ids, curriculum.topics):
            self._transition_proposal(proposal, to_status=ProposalStatus.REJECTED, reason="parent topic does not exist")
            return False, None

        new_topic_id = self._new_topic_id(curriculum, proposal.title)
        if new_topic_id in proposal.parent_node_ids:
            self._transition_proposal(proposal, to_status=ProposalStatus.REJECTED, reason="self dependency")
            return False, None

        prerequisite_ids = proposal.parent_node_ids if proposal.edge_type == EdgeType.REQUIRES else []
        if self._would_introduce_cycle(
            curriculum=curriculum,
            new_topic_id=new_topic_id,
            prerequisite_ids=prerequisite_ids,
        ):
            self._transition_proposal(proposal, to_status=ProposalStatus.REJECTED, reason="cycle detected")
            return False, None

        if not self._is_subject_links_allowed(proposal.parent_node_ids, curriculum.topics):
            self._transition_proposal(
                proposal,
                to_status=ProposalStatus.REJECTED,
                reason="cross-subject requires relation is not allowed",
            )
            return False, None

        self._transition_proposal(proposal, to_status=ProposalStatus.VALIDATED, reason="validation passed")

        curriculum.topics.append(
            TopicNode(
                topic_id=new_topic_id,
                title=proposal.title,
                difficulty=1,
                prerequisite_ids=prerequisite_ids,
                tags=["auto-proposed", "shadow"],
            )
        )
        proposal.created_topic_id = new_topic_id
        self._transition_proposal(
            proposal,
            to_status=ProposalStatus.SHADOW,
            reason="validated and inserted as shadow node",
        )
        return True, new_topic_id

    def promote_shadow_topic(
        self,
        *,
        topic_id: str,
        curriculum: CurriculumConfig,
        mastery_map: dict[str, NodeMastery],
    ) -> bool:
        topic = next((t for t in curriculum.topics if t.topic_id == topic_id), None)
        if topic is None:
            return False
        if "shadow" not in topic.tags:
            return False

        mastery = mastery_map.get(topic_id)
        if mastery is None:
            return False

        if mastery.depth_level < self.shadow_promote_depth:
            return False
        if (
            mastery.success_count < self.shadow_promote_success_count
            and mastery.stability_level < self.shadow_promote_stability
        ):
            return False

        topic.tags = [tag for tag in topic.tags if tag != "shadow"]
        if "active" not in topic.tags:
            topic.tags.append("active")
        return True

    def _transition_proposal(self, proposal: GraphMutationProposal, *, to_status: ProposalStatus, reason: str) -> bool:
        if proposal.status == to_status:
            proposal.reason = reason
            return True

        allowed = self._ALLOWED_PROPOSAL_TRANSITIONS.get(proposal.status, set())
        if to_status not in allowed:
            return False

        proposal.status = to_status
        proposal.reason = reason
        return True

    @staticmethod
    def _summarize_title(question_text: str) -> str:
        text = question_text.strip()
        if not text:
            return "新知识点"
        return text[:18]

    def _pick_parent_ids(
        self,
        *,
        question_text: str,
        current_topic_id: str | None,
        topics: list[TopicNode],
    ) -> list[str]:
        if not topics:
            return [current_topic_id] if current_topic_id else []

        candidates: list[tuple[str, float]] = []
        for topic in topics:
            score = self._topic_overlap_score(question_text, topic.title)
            if score <= 0:
                continue
            candidates.append((topic.topic_id, score))

        candidates.sort(key=lambda item: item[1], reverse=True)
        picked: list[str] = []
        if current_topic_id:
            picked.append(current_topic_id)

        for topic_id, score in candidates:
            if score < 0.2:
                continue
            if topic_id in picked:
                continue
            picked.append(topic_id)
            if len(picked) >= 2:
                break

        return picked

    @staticmethod
    def _new_topic_id(curriculum: CurriculumConfig, title: str) -> str:
        base = GraphCurator._slugify(title)
        candidate = f"auto_{base}" if base else "auto_topic"
        existing = {t.topic_id for t in curriculum.topics}
        if candidate not in existing:
            return candidate

        idx = 2
        while f"{candidate}_{idx}" in existing:
            idx += 1
        return f"{candidate}_{idx}"

    @staticmethod
    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", text).strip("_").lower()
        return slug[:32]

    @staticmethod
    def _normalize_title(text: str) -> str:
        return re.sub(r"\s+", "", text).lower()

    @staticmethod
    def _topic_subject(topic: TopicNode) -> str:
        for tag in topic.tags:
            if tag.startswith("subject:"):
                return tag.split(":", 1)[1]
        return "general"

    def _is_subject_links_allowed(self, parent_node_ids: list[str], topics: list[TopicNode]) -> bool:
        if self.allow_cross_subject_requires:
            return True

        if len(parent_node_ids) <= 1:
            return True

        topic_map = {topic.topic_id: topic for topic in topics}
        subjects = {
            self._topic_subject(topic_map[parent_id])
            for parent_id in parent_node_ids
            if parent_id in topic_map
        }
        return len(subjects) <= 1

    @staticmethod
    def _topic_overlap_score(question_text: str, topic_title: str) -> float:
        question = GraphCurator._normalize_title(question_text)
        topic = GraphCurator._normalize_title(topic_title)
        if not question or not topic:
            return 0.0

        qgrams = {question[i : i + 2] for i in range(max(1, len(question) - 1))}
        tgrams = {topic[i : i + 2] for i in range(max(1, len(topic) - 1))}
        inter = len(qgrams.intersection(tgrams))
        return inter / max(1, len(tgrams))

    @staticmethod
    def _parents_exist(parent_node_ids: list[str], topics: list[TopicNode]) -> bool:
        if not parent_node_ids:
            return True
        existing = {topic.topic_id for topic in topics}
        return all(parent_id in existing for parent_id in parent_node_ids)

    @staticmethod
    def _passes_granularity(title: str) -> bool:
        normalized = GraphCurator._normalize_title(title)
        if len(normalized) < 4:
            return False
        if len(title.strip()) > 32:
            return False
        return True

    @classmethod
    def _would_introduce_cycle(
        cls,
        *,
        curriculum: CurriculumConfig,
        new_topic_id: str,
        prerequisite_ids: list[str],
    ) -> bool:
        graph: dict[str, list[str]] = {
            topic.topic_id: list(topic.prerequisite_ids)
            for topic in curriculum.topics
        }
        graph[new_topic_id] = list(prerequisite_ids)

        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node_id: str) -> bool:
            if node_id in visited:
                return False
            if node_id in visiting:
                return True

            visiting.add(node_id)
            for pre_id in graph.get(node_id, []):
                if pre_id not in graph:
                    continue
                if dfs(pre_id):
                    return True
            visiting.remove(node_id)
            visited.add(node_id)
            return False

        for node_id in graph:
            if dfs(node_id):
                return True
        return False

    @classmethod
    def _is_duplicate_title(cls, title: str, topics: list[TopicNode]) -> bool:
        normalized = cls._normalize_title(title)
        if not normalized:
            return True

        for topic in topics:
            existing = cls._normalize_title(topic.title)
            if normalized == existing:
                return True

            if len(normalized) >= 4 and len(existing) >= 4:
                if normalized in existing or existing in normalized:
                    return True

        return False

    @classmethod
    def _is_exact_duplicate_title(cls, title: str, topics: list[TopicNode]) -> bool:
        normalized = cls._normalize_title(title)
        if not normalized:
            return True
        return any(normalized == cls._normalize_title(topic.title) for topic in topics)
