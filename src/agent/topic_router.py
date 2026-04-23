from __future__ import annotations

import re

from src.agent.models import TopicMatch, TopicRoutingResult
from src.core.models import NodeMastery, TopicNode


class TopicRouter:
    _FORCE_SWITCH_CUES = (
        "换个话题",
        "换到",
        "切到",
        "讲讲",
        "说说",
        "我想问",
        "我想学",
        "我们聊",
    )

    def __init__(
        self,
        *,
        inertia_bonus: float = 0.12,
        switch_margin: float = 0.2,
        min_score: float = 0.28,
        unlock_depth_threshold: int = 1,
        locked_topic_penalty: float = 0.35,
    ) -> None:
        self.inertia_bonus = inertia_bonus
        self.switch_margin = switch_margin
        self.min_score = min_score
        self.unlock_depth_threshold = max(0, unlock_depth_threshold)
        self.locked_topic_penalty = max(0.0, min(1.0, locked_topic_penalty))

    def route(
        self,
        *,
        user_text: str,
        current_topic_id: str | None,
        topics: list[TopicNode],
        mastery_map: dict[str, NodeMastery] | None = None,
    ) -> TopicRoutingResult:
        if not topics:
            return TopicRoutingResult(
                current_topic_id=current_topic_id,
                target_topic_id=None,
                switched=False,
                off_topic=True,
                trace="no topics available",
            )

        mastery = mastery_map or {}
        forced_target = self._detect_forced_target(user_text=user_text, topics=topics)
        if forced_target is not None:
            forced_topic = next((topic for topic in topics if topic.topic_id == forced_target), None)
            if forced_topic is not None and not self._is_unlocked(forced_topic, mastery):
                return TopicRoutingResult(
                    current_topic_id=current_topic_id,
                    target_topic_id=current_topic_id,
                    switched=False,
                    off_topic=True,
                    trace=f"forced switch blocked by prerequisites: {forced_target}",
                )

            switched = bool(current_topic_id and forced_target != current_topic_id)
            return TopicRoutingResult(
                current_topic_id=current_topic_id,
                target_topic_id=forced_target,
                switched=switched,
                off_topic=False,
                trace=f"forced switch to {forced_target}",
            )

        matches: list[TopicMatch] = []
        for topic in topics:
            score = self._score_topic(user_text, topic)
            if not self._is_unlocked(topic, mastery):
                score *= self.locked_topic_penalty
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

    def _is_unlocked(self, topic: TopicNode, mastery_map: dict[str, NodeMastery]) -> bool:
        if not topic.prerequisite_ids:
            return True

        for pre_id in topic.prerequisite_ids:
            mastery = mastery_map.get(pre_id)
            if mastery is None:
                return False
            if mastery.depth_level < self.unlock_depth_threshold:
                return False
        return True

    def _score_topic(self, user_text: str, topic: TopicNode) -> float:
        topic_title = topic.title
        clean_user = self._normalize(user_text)
        clean_topic = self._normalize(topic_title)
        text_tokens = TopicRouter._tokens(user_text)
        topic_tokens = TopicRouter._tokens(topic_title)
        if not text_tokens or not topic_tokens:
            return 0.0

        inter = text_tokens.intersection(topic_tokens)
        score = len(inter) / max(1, len(topic_tokens))

        if clean_topic and clean_topic in clean_user:
            score = max(score, 0.9)
        elif clean_user and len(clean_user) >= 4 and clean_user in clean_topic:
            score = max(score, 0.65)

        tag_tokens = self._topic_tag_tokens(topic)
        if tag_tokens:
            tag_overlap = len(text_tokens.intersection(tag_tokens)) / max(1, len(tag_tokens))
            score += min(0.2, tag_overlap * 0.2)

        return min(1.0, score)

    def _detect_forced_target(self, *, user_text: str, topics: list[TopicNode]) -> str | None:
        clean_text = self._normalize(user_text)
        if not clean_text:
            return None

        if not any(cue in clean_text for cue in self._FORCE_SWITCH_CUES):
            return None

        best_topic_id: str | None = None
        best_score = 0.0
        for topic in topics:
            if not self._topic_mentioned(clean_text, topic):
                continue
            score = self._score_topic(user_text, topic)
            if score > best_score:
                best_score = score
                best_topic_id = topic.topic_id

        return best_topic_id

    def _topic_mentioned(self, clean_text: str, topic: TopicNode) -> bool:
        clean_topic = self._normalize(topic.title)
        if clean_topic and clean_topic in clean_text:
            return True

        for token in self._topic_tag_tokens(topic):
            if len(token) < 2:
                continue
            if token in clean_text:
                return True
        return False

    @staticmethod
    def _topic_tag_tokens(topic: TopicNode) -> set[str]:
        tokens: set[str] = set()
        for tag in topic.tags:
            clean = TopicRouter._normalize(tag)
            if clean:
                tokens.update(TopicRouter._tokens(clean))

            if ":" in tag:
                _, suffix = tag.split(":", 1)
                suffix_clean = TopicRouter._normalize(suffix)
                if suffix_clean:
                    tokens.update(TopicRouter._tokens(suffix_clean))
        return tokens

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[\s\W_]+", "", text.lower())

    @staticmethod
    def _tokens(text: str) -> set[str]:
        clean = TopicRouter._normalize(text)
        if not clean:
            return set()

        return {clean[i : i + 2] for i in range(max(1, len(clean) - 1))}
