from __future__ import annotations

from datetime import datetime, timezone

from src.agent.graph_curator import GraphCurator
from src.agent.models import AgentTurnDecision
from src.agent.topic_router import TopicRouter
from src.core.models import AppState


class AgentOrchestrator:
    def __init__(self, *, unlock_depth_threshold: int = 1) -> None:
        self.router = TopicRouter(unlock_depth_threshold=unlock_depth_threshold)
        self.curator = GraphCurator()

    def process_turn(self, *, state: AppState, user_text: str) -> AgentTurnDecision:
        explore_active = self._is_explore_window_active(state.learning.explore_window_until)
        from_topic_id = state.learning.current_topic_id
        routing = self.router.route(
            user_text=user_text,
            current_topic_id=state.learning.current_topic_id,
            topics=state.curriculum.topics,
            mastery_map=state.learning.mastery_map,
        )

        if routing.target_topic_id and routing.target_topic_id != state.learning.current_topic_id:
            state.learning.current_topic_id = routing.target_topic_id

        if routing.off_topic:
            if explore_active:
                return AgentTurnDecision(
                    routing=routing,
                    reply_hint="现在是探索时间，你可以自由提问，我会尽量回答并帮你串联知识。",
                    earned_points=1,
                    should_answer_directly=True,
                    proposal=None,
                    explore_window_active=True,
                    transition_from_topic_id=from_topic_id,
                    transition_to_topic_id=state.learning.current_topic_id,
                )

            proposal = self.curator.propose_from_question(
                question_text=user_text,
                current_topic_id=state.learning.current_topic_id,
            )
            applied, new_topic_id = self.curator.auto_review_and_apply(proposal=proposal, curriculum=state.curriculum)
            hint = "这个问题很棒。我先记入知识网，等获得探索时间后我们深入聊。"
            if applied and new_topic_id:
                hint = f"这个问题很好，我已经把它加入学习网节点：{proposal.title}。"

            return AgentTurnDecision(
                routing=routing,
                reply_hint=hint,
                earned_points=2,
                should_answer_directly=True,
                proposal=proposal,
                explore_window_active=False,
                transition_from_topic_id=from_topic_id,
                transition_to_topic_id=state.learning.current_topic_id,
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
            explore_window_active=explore_active,
            transition_from_topic_id=from_topic_id,
            transition_to_topic_id=state.learning.current_topic_id,
        )

    @staticmethod
    def _is_explore_window_active(explore_window_until: str | None) -> bool:
        if not explore_window_until:
            return False

        try:
            until = datetime.fromisoformat(explore_window_until)
        except Exception:
            return False

        return until > datetime.now(timezone.utc)
