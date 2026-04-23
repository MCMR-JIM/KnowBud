from __future__ import annotations

import re

from src.agent.models import TopicMatch, TopicRoutingResult
from src.core.models import TopicNode


class TopicRouter:
    def __init__(self, *, inertia_bonus: float = 0.12, switch_margin: float = 0.2, min_score: float = 0.28) -> None:
        self.inertia_bonus = inertia_bonus
        self.switch_margin = switch_margin
        self.min_score = min_score

    def route(self, *, user_text: str, current_topic_id: str | None, topics: list[TopicNode]) -> TopicRoutingResult:
        if not topics:
            return TopicRoutingResult(
                current_topic_id=current_topic_id,
                target_topic_id=None,
                switched=False,
                off_topic=True,
                trace="no topics available",
            )

        matches: list[TopicMatch] = []
        for topic in topics:
            score = self._score_topic(user_text, topic.title)
            if topic.topic_id == current_topic_id:
                score = min(1.0, score + self.inertia_bonus)
            matches.append(TopicMatch(node_id=topic.topic_id, title=topic.title, score=score))

        matches.sort(key=lambda m: m.score, reverse=True)
        best = matches[0]
        second = matches[1] if len(matches) > 1 else None

        if best.score < self.min_score:
            return TopicRoutingResult(
                current_topic_id=current_topic_id,
                target_topic_id=current_topic_id,
                switched=False,
                off_topic=True,
                candidates=matches[:3],
                trace=f"best score below threshold: {best.score:.2f}",
            )

        switched = False
        if current_topic_id and best.node_id != current_topic_id:
            margin = best.score - (second.score if second else 0.0)
            switched = margin >= self.switch_margin

        target_topic_id = best.node_id if (not current_topic_id or switched) else current_topic_id
        return TopicRoutingResult(
            current_topic_id=current_topic_id,
            target_topic_id=target_topic_id,
            switched=switched,
            off_topic=False,
            candidates=matches[:3],
            trace=f"best={best.node_id}:{best.score:.2f}",
        )

    @staticmethod
    def _score_topic(user_text: str, topic_title: str) -> float:
        text_tokens = TopicRouter._tokens(user_text)
        topic_tokens = TopicRouter._tokens(topic_title)
        if not text_tokens or not topic_tokens:
            return 0.0

        inter = text_tokens.intersection(topic_tokens)
        return len(inter) / max(1, len(topic_tokens))

    @staticmethod
    def _tokens(text: str) -> set[str]:
        clean = re.sub(r"[\s\W_]+", "", text.lower())
        if not clean:
            return set()

        return {clean[i : i + 2] for i in range(max(1, len(clean) - 1))}
