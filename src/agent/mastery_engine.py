from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.core.models import LearningState, NodeMastery


@dataclass
class MasteryUpdate:
    mastered_now: bool
    true_mastered_now: bool
    should_open_explore_window: bool
    topic_id: str


class MasteryEngine:
    def __init__(self, *, spaced_gap_hours: int = 12) -> None:
        self.spaced_gap = timedelta(hours=max(1, spaced_gap_hours))

    def update_from_answer(self, *, state: LearningState, topic_id: str, user_text: str, is_correct: bool) -> MasteryUpdate:
        node = state.mastery_map.get(topic_id) or NodeMastery()
        prev_mastered = self._is_mastered(node)
        prev_true_mastered = self._is_true_mastered(node)
        now = datetime.now(timezone.utc)

        if is_correct:
            depth = self._infer_depth(user_text)
            node.depth_level = max(node.depth_level, depth)
            node.success_count += 1
            node.success_streak += 1

            if node.last_success_ts:
                try:
                    last = datetime.fromisoformat(node.last_success_ts)
                    if now - last >= self.spaced_gap:
                        node.spaced_success_count += 1
                except Exception:
                    pass
            node.last_success_ts = now.isoformat()
        else:
            node.success_streak = 0

        node.stability_level = self._infer_stability(node)
        node.mastery_state = self._infer_mastery_state(node, now=now)
        node.last_state_ts = now.isoformat()
        state.mastery_map[topic_id] = node

        mastered_now = self._is_mastered(node) and not prev_mastered
        true_mastered_now = self._is_true_mastered(node) and not prev_true_mastered
        should_open_explore_window = true_mastered_now and not node.reward_window_granted
        if should_open_explore_window:
            node.reward_window_granted = True

        return MasteryUpdate(
            mastered_now=mastered_now,
            true_mastered_now=true_mastered_now,
            should_open_explore_window=should_open_explore_window,
            topic_id=topic_id,
        )

    @staticmethod
    def _infer_depth(user_text: str) -> int:
        text = user_text.strip()
        if not text:
            return 0

        depth = 1 if len(text) >= 6 else 0
        cues = ["因为", "所以", "比如", "例如", "如果", "应用", "结合", "推导", "因此"]
        hit_count = sum(1 for cue in cues if cue in text)
        if hit_count >= 1:
            depth = max(depth, 2)
        if hit_count >= 2 or len(text) >= 22:
            depth = max(depth, 3)
        return depth

    @staticmethod
    def _infer_stability(node: NodeMastery) -> int:
        if node.spaced_success_count >= 2:
            return 2
        if node.success_streak >= 2 or node.success_count >= 3:
            return 1
        if node.success_count >= 1:
            return 0
        return 0

    @staticmethod
    def _is_mastered(node: NodeMastery) -> bool:
        return node.depth_level >= 2 and node.success_count >= 1

    @staticmethod
    def _is_true_mastered(node: NodeMastery) -> bool:
        return node.depth_level >= 2 and node.stability_level >= 1

    def _infer_mastery_state(self, node: NodeMastery, *, now: datetime) -> str:
        if node.success_count == 0 and node.depth_level == 0:
            return "unknown"

        if node.depth_level < 2:
            return "introduced"

        if node.last_success_ts:
            try:
                last = datetime.fromisoformat(node.last_success_ts)
                if now - last >= (self.spaced_gap * 4):
                    return "decaying"
            except Exception:
                pass

        if node.stability_level >= 2:
            return "mastered"

        if node.stability_level >= 1:
            return "reinforced"

        return "practicing"
