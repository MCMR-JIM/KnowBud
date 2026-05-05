from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.core.enums import LearningPhase
from src.core.models import TopicNode
from src.services.graph_walker import (
    GraphWalker,
    WalkResult,
    MAX_WALK_DEPTH,
)
from src.services.session_backend import SessionBackend


def _build_backend(tmp_path: Path) -> SessionBackend:
    backend = SessionBackend()
    backend.state_file = tmp_path / "state.json"
    backend.state_db_file = str(tmp_path / "state.db")
    backend.log_file = tmp_path / "decision_trace.jsonl"
    state = backend.load_app_state()
    state.learning.current_phase = LearningPhase.LEARNING
    backend.save_app_state(state)
    return backend


def _make_llm_response(content: str) -> object:
    msg = MagicMock()
    msg.content = content
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _add_topics(backend: SessionBackend, topics: list[TopicNode]) -> None:
    state = backend.load_app_state(include_history=False)
    state.curriculum.topics = list(topics)
    backend.save_app_state(state)


def _get_topics(backend: SessionBackend) -> list[TopicNode]:
    return backend.load_app_state(include_history=False).curriculum.topics


class TestGraphWalker:
    def test_empty_graph_no_root(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"
        walker = GraphWalker(backend, "math")
        result = walker.walk_and_insert("确界原理", "确界原理描述")
        assert result.action == "insert_as_child"
        assert result.reason == "no subject root found"
        assert result.parent_node_ids == []

    def test_root_no_successors_insert_as_child(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"
        _add_topics(
            backend,
            [TopicNode(topic_id="math_root", title="数学", difficulty=1, prerequisite_ids=[], tags=["subject:math", "facet:root"])],
        )
        walker = GraphWalker(backend, "math")
        # Mock LLM to say "child"
        def mock_create(**kwargs):
            return _make_llm_response('{"action":"child"}')
        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create
        try:
            result = walker.walk_and_insert("确界原理", "确界原理描述")
            assert result.action == "insert_after"
            assert result.parent_node_ids == ["math_root"]
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_has_successors_go_deeper(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"
        _add_topics(
            backend,
            [
                TopicNode(topic_id="math_root", title="数学", difficulty=1, prerequisite_ids=[], tags=["subject:math", "facet:root"]),
                TopicNode(topic_id="real_complete", title="实数完备性定理", difficulty=2, parent_ids=["math_root"], prerequisite_ids=[], tags=["subject:math", "facet:theorem_or_rule"]),
                TopicNode(topic_id="finite_cover", title="有限覆盖定理", difficulty=3, parent_ids=["real_complete"], prerequisite_ids=[], tags=["subject:math", "facet:theorem_or_rule"]),
            ],
        )
        call_count = [0]

        def mock_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_response('{"action":"go_deeper","next_node_id":"real_complete"}')
            return _make_llm_response('{"action":"insert_after"}')

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create
        try:
            walker = GraphWalker(backend, "math")
            result = walker.walk_and_insert("区间套定理", "区间套定理是实数完备性的一环")
            assert result.action == "insert_after"
            assert result.parent_node_ids == ["real_complete"]
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_insert_before_prerequisite(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"
        _add_topics(
            backend,
            [
                TopicNode(topic_id="math_root", title="数学", difficulty=1, prerequisite_ids=[], tags=["subject:math", "facet:root"]),
                TopicNode(topic_id="finite_cover", title="有限覆盖定理", difficulty=2, parent_ids=["math_root"], prerequisite_ids=["real_complete"], tags=["subject:math", "facet:theorem_or_rule"]),
                TopicNode(topic_id="real_complete", title="实数完备性定理", difficulty=2, parent_ids=["math_root"], prerequisite_ids=[], tags=["subject:math", "facet:theorem_or_rule"]),
            ],
        )

        def mock_create(**kwargs):
            return _make_llm_response('{"action":"insert_before","before_node_id":"finite_cover"}')

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create
        try:
            walker = GraphWalker(backend, "math")
            result = walker.walk_and_insert("确界原理", "确界原理是有限覆盖定理的前置")
            assert result.action == "insert_before"
            assert result.anchor_topic_id == "finite_cover"
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_leaf_node_insert_as_child(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"
        _add_topics(
            backend,
            [
                TopicNode(topic_id="math_root", title="数学", difficulty=1, prerequisite_ids=[], tags=["subject:math", "facet:root"]),
                TopicNode(topic_id="finite_cover", title="有限覆盖定理", difficulty=3, parent_ids=["math_root"], prerequisite_ids=[], tags=["subject:math", "facet:theorem_or_rule"]),
            ],
        )

        call_count = [0]

        def mock_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_response('{"action":"go_deeper","next_node_id":"finite_cover"}')
            return _make_llm_response('{"action":"child"}')

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create
        try:
            walker = GraphWalker(backend, "math")
            result = walker.walk_and_insert("有限覆盖定理的应用", "有限覆盖定理在分析中的应用")
            assert result.action == "insert_after"
            assert result.parent_node_ids == ["finite_cover"]
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_depth_truncation(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        topics = [TopicNode(topic_id="math_root", title="数学", difficulty=1, prerequisite_ids=[], tags=["subject:math", "facet:root"])]
        for i in range(MAX_WALK_DEPTH + 2):
            tid = f"node_{i}"
            parent = ["math_root"] if i == 0 else [f"node_{i-1}"]
            topics.append(TopicNode(topic_id=tid, title=f"层{i}", difficulty=1, parent_ids=parent, prerequisite_ids=[], tags=["subject:math"]))
        _add_topics(backend, topics)

        call_count = [0]

        def mock_create(**kwargs):
            call_count[0] += 1
            return _make_llm_response(f'{{"action":"go_deeper","next_node_id":"node_{call_count[0]-1}"}}')

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create
        try:
            walker = GraphWalker(backend, "math")
            result = walker.walk_and_insert("深层概念", "深层概念描述")
            assert MAX_WALK_DEPTH >= 5  # sanity
            assert result.action in {"insert_after", "insert_as_child"}
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_language_routes_by_facet(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"
        _add_topics(
            backend,
            [
                TopicNode(topic_id="eng_root", title="英语", difficulty=1, prerequisite_ids=[], tags=["subject:language", "facet:root", "language:english"]),
                TopicNode(topic_id="eng_grammar", title="英语语法", difficulty=1, parent_ids=["eng_root"], prerequisite_ids=[], tags=["subject:language", "facet:grammar", "language:english"]),
            ],
        )

        def mock_create(**kwargs):
            return _make_llm_response('{"action":"go_deeper","next_node_id":"eng_grammar"}')

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create
        try:
            walker = GraphWalker(backend, "language", "english")
            result = walker.walk_and_insert("过去完成时", "过去完成时的用法")
            assert result.action == "insert_after"
            assert result.parent_node_ids == ["eng_grammar"]
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_invalid_llm_response_degradation(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"
        _add_topics(
            backend,
            [
                TopicNode(topic_id="math_root", title="数学", difficulty=1, prerequisite_ids=[], tags=["subject:math", "facet:root"]),
                TopicNode(topic_id="child", title="子概念", difficulty=2, parent_ids=["math_root"], prerequisite_ids=[], tags=["subject:math"]),
            ],
        )

        def mock_create(**kwargs):
            return _make_llm_response("not valid json at all {{{")

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create
        try:
            walker = GraphWalker(backend, "math")
            result = walker.walk_and_insert("新概念", "新概念描述")
            assert result.action in {"insert_after", "no_match"}
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig
