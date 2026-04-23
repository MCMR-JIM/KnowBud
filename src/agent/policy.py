from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPolicyConfig:
    inertia_bonus: float = 0.12
    switch_margin: float = 0.2
    min_score: float = 0.28
    unlock_depth_threshold: int = 1
    locked_topic_penalty: float = 0.35
    explore_window_minutes: int = 5
    shadow_promote_depth: int = 2
    shadow_promote_success_count: int = 2
    shadow_promote_stability: int = 1
    allow_cross_subject_requires: bool = False

    @classmethod
    def from_env(cls) -> "AgentPolicyConfig":
        return cls(
            inertia_bonus=_env_float("TOPIC_INERTIA_BONUS", 0.12),
            switch_margin=_env_float("TOPIC_SWITCH_MARGIN", 0.2),
            min_score=_env_float("TOPIC_MIN_SCORE", 0.28),
            unlock_depth_threshold=_env_int("PREREQ_UNLOCK_DEPTH", 1),
            locked_topic_penalty=_env_float("LOCKED_TOPIC_PENALTY", 0.35),
            explore_window_minutes=_env_int("EXPLORE_WINDOW_MINUTES", 5),
            shadow_promote_depth=_env_int("SHADOW_PROMOTE_DEPTH", 2),
            shadow_promote_success_count=_env_int("SHADOW_PROMOTE_SUCCESS_COUNT", 2),
            shadow_promote_stability=_env_int("SHADOW_PROMOTE_STABILITY", 1),
            allow_cross_subject_requires=_env_bool("ALLOW_CROSS_SUBJECT_REQUIRES", False),
        )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
