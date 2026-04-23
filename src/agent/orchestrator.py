from __future__ import annotations

from src.agent.graph_curator import GraphCurator
from src.agent.models import AgentTurnDecision
from src.agent.topic_router import TopicRouter
from src.core.models import AppState


class AgentOrchestrator:
    def __init__(self) -> None:
        self.router = TopicRouter()
        self.curator = GraphCurator()

    def process_turn(self, *, state: AppState, user_text: str) -> AgentTurnDecision:
        routing = self.router.route(
            user_text=user_text,
            current_topic_id=state.learning.current_topic_id,
            topics=state.curriculum.topics,
        )

        if routing.target_topic_id and routing.target_topic_id != state.learning.current_topic_id:
            state.learning.current_topic_id = routing.target_topic_id

        if routing.off_topic:
            proposal = self.curator.propose_from_question(
                question_text=user_text,
                current_topic_id=state.learning.current_topic_id,
            )
            applied, new_topic_id = self.curator.auto_review_and_apply(proposal=proposal, curriculum=state.curriculum)
            hint = "这个问题很有意思，我先给你一个简短提示，再一起回到主线学习。"
            if applied and new_topic_id:
                hint = f"这个问题很好，我已经把它加入学习网节点：{proposal.title}。"

            return AgentTurnDecision(
                routing=routing,
                reply_hint=hint,
                earned_points=2,
                should_answer_directly=True,
                proposal=proposal,
            )

        if routing.switched:
            hint = "我们先顺着你刚刚的问题，切到相关知识点继续讲。"
        else:
            hint = ""

        return AgentTurnDecision(
            routing=routing,
            reply_hint=hint,
            earned_points=0,
            should_answer_directly=False,
            proposal=None,
        )
