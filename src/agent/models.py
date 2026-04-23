from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EdgeType(str, Enum):
    REQUIRES = "requires"
    SUPPORTS = "supports"
    RELATED = "related"


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
    current_topic_id: str | None = None
    target_topic_id: str | None = None
    switched: bool = False
    off_topic: bool = False
    candidates: list[TopicMatch] = Field(default_factory=list)
    trace: str = ""


class GraphMutationProposal(BaseModel):
    trigger: str
    title: str
    summary: str
    parent_node_ids: list[str] = Field(default_factory=list)
    edge_type: EdgeType = EdgeType.REQUIRES
    status: ProposalStatus = ProposalStatus.PROPOSED
    reason: str = ""


class AgentTurnDecision(BaseModel):
    routing: TopicRoutingResult
    reply_hint: str = ""
    earned_points: int = 0
    should_answer_directly: bool = False
    proposal: GraphMutationProposal | None = None
    explore_window_active: bool = False
    transition_from_topic_id: str | None = None
    transition_to_topic_id: str | None = None
