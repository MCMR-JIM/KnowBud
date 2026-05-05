from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EdgeType(str, Enum):
    REQUIRES = "requires"
    SUPPORTS = "supports"
    RELATED = "related"
    PART_OF = "part_of"
    DERIVED_FROM = "derived_from"
    DEFINES = "defines"
    EXPLAINS = "explains"
    EVIDENCE_FOR = "evidence_for"
    CAUSES = "causes"
    USES = "uses"
    FORMULA_USES_QUANTITY = "formula_uses_quantity"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    SHADOW = "shadow"
    ACTIVE = "active"
    REJECTED = "rejected"


class TopicMatch(BaseModel):
    node_id: str
    title: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class TopicRoutingResult(BaseModel):
    current_topic_id: Optional[str] = None
    target_topic_id: Optional[str] = None
    switched: bool = False
    off_topic: bool = False
    candidates: list[TopicMatch] = Field(default_factory=list)
    trace: str = ""


class GraphMutationProposal(BaseModel):
    proposal_id: str
    trigger: str
    title: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    parent_node_ids: list[str] = Field(default_factory=list)
    prerequisite_node_ids: list[str] = Field(default_factory=list)
    pending_parent_proposal_ids: list[str] = Field(default_factory=list)
    edge_type: EdgeType = EdgeType.REQUIRES
    status: ProposalStatus = ProposalStatus.PROPOSED
    reason: str = ""
    created_topic_id: Optional[str] = None


class AgentTurnDecision(BaseModel):
    routing: TopicRoutingResult
    reply_hint: str = ""
    earned_points: int = 0
    should_answer_directly: bool = False
    proposal: Optional[GraphMutationProposal] = None
    explore_window_active: bool = False
    transition_from_topic_id: Optional[str] = None
    transition_to_topic_id: Optional[str] = None
