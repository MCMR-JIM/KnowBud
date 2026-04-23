from __future__ import annotations

import re

from src.agent.models import EdgeType, GraphMutationProposal, ProposalStatus
from src.core.models import CurriculumConfig, TopicNode


class GraphCurator:
    def propose_from_question(self, *, question_text: str, current_topic_id: str | None) -> GraphMutationProposal:
        title = self._summarize_title(question_text)
        parent_ids = [current_topic_id] if current_topic_id else []
        return GraphMutationProposal(
            trigger="unknown_question",
            title=title,
            summary=question_text[:120],
            parent_node_ids=parent_ids,
            edge_type=EdgeType.REQUIRES,
            status=ProposalStatus.PROPOSED,
            reason="question cannot be mapped to existing topic with high confidence",
        )

    def auto_review_and_apply(self, *, proposal: GraphMutationProposal, curriculum: CurriculumConfig) -> tuple[bool, str | None]:
        if proposal.status != ProposalStatus.PROPOSED:
            return False, None

        if self._is_duplicate_title(proposal.title, curriculum.topics):
            proposal.status = ProposalStatus.REJECTED
            proposal.reason = "duplicated title"
            return False, None

        new_topic_id = self._new_topic_id(curriculum, proposal.title)
        if new_topic_id in proposal.parent_node_ids:
            proposal.status = ProposalStatus.REJECTED
            proposal.reason = "self dependency"
            return False, None

        prerequisite_ids = proposal.parent_node_ids if proposal.edge_type == EdgeType.REQUIRES else []
        curriculum.topics.append(
            TopicNode(
                topic_id=new_topic_id,
                title=proposal.title,
                difficulty=1,
                prerequisite_ids=prerequisite_ids,
                tags=["auto-proposed"],
            )
        )
        proposal.status = ProposalStatus.ACTIVE
        return True, new_topic_id

    @staticmethod
    def _summarize_title(question_text: str) -> str:
        text = question_text.strip()
        if not text:
            return "新知识点"
        return text[:18]

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
