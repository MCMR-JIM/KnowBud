from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.core.enums import LearningPhase
from src.core.models import TopicNode
from src.services.graph_locator import GraphLocator, GraphPosition
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


def _llm_resp(data):
    msg = MagicMock()
    msg.content = json.dumps(data)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class TestGraphLocator:
    def test_existing_node_returns_exists_true(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        state = backend.load_app_state(include_history=False)
        state.curriculum.topics = [
            TopicNode(topic_id="refraction", title="光的折射规律", difficulty=1, prerequisite_ids=[], tags=["subject:physics"]),
        ]
        backend.save_app_state(state)

        def mock_create(**kwargs):
            return _llm_resp({
                "exists": True, "node_id": "refraction", "parent_ids": [], "successor_ids": [],
                "reason": "title exact match",
            })

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create

        try:
            locator = GraphLocator(backend, "physics")
            pos = locator.locate("光的折射规律", "光从一种介质进入另一种介质时改变方向")
            assert pos.exists is True
            assert pos.node_id == "refraction"
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_new_node_returns_correct_parents(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        state = backend.load_app_state(include_history=False)
        state.curriculum.topics = [
            TopicNode(topic_id="root", title="科学", difficulty=1, prerequisite_ids=[], tags=["subject:science", "facet:root"]),
            TopicNode(topic_id="light", title="光学[中继]", difficulty=1, parent_ids=["root"], prerequisite_ids=["root"], tags=["subject:science"]),
            TopicNode(topic_id="refraction", title="光的折射规律", difficulty=2, parent_ids=["light"], prerequisite_ids=["light"], tags=["subject:science"]),
        ]
        backend.save_app_state(state)

        def mock_create(**kwargs):
            return _llm_resp({
                "exists": False, "node_id": None,
                "parent_ids": ["refraction"], "successor_ids": [],
                "reason": "三条特殊光线是凸透镜成像的子知识点，应从属于折射规律",
            })

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create

        try:
            locator = GraphLocator(backend, "science")
            pos = locator.locate("凸透镜三条特殊光线", "通过光心/焦点/平行主轴三条作图光线")
            assert pos.exists is False
            assert "refraction" in pos.parent_ids
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_new_node_returns_correct_successors(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        state = backend.load_app_state(include_history=False)
        state.curriculum.topics = [
            TopicNode(topic_id="root", title="科学", difficulty=1, prerequisite_ids=[], tags=["subject:science", "facet:root"]),
            TopicNode(topic_id="lens", title="凸透镜成像规律", difficulty=2, parent_ids=["root"], prerequisite_ids=["refraction"], tags=["subject:science"]),
        ]
        backend.save_app_state(state)

        def mock_create(**kwargs):
            return _llm_resp({
                "exists": False, "node_id": None,
                "parent_ids": ["root"], "successor_ids": ["lens"],
                "reason": "光的折射规律是凸透镜成像的前置知识",
            })

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create

        try:
            locator = GraphLocator(backend, "science")
            pos = locator.locate("光的折射规律", "光从一种介质进入另一种介质")
            assert pos.exists is False
            assert "lens" in pos.successor_ids
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig

    def test_empty_graph_returns_no_match(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        state = backend.load_app_state(include_history=False)
        state.curriculum.topics = []
        backend.save_app_state(state)

        locator = GraphLocator(backend, "math")
        pos = locator.locate("加法", "基本运算")
        assert pos.exists is False
        assert pos.parent_ids == []
        assert pos.reason == "empty graph"

    def test_full_graph_snapshot_sent_to_llm(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        state = backend.load_app_state(include_history=False)
        state.curriculum.topics = [
            TopicNode(topic_id="root", title="科学", difficulty=1, prerequisite_ids=[], tags=["subject:science"]),
            TopicNode(topic_id="light", title="光学", difficulty=1, parent_ids=["root"], prerequisite_ids=["root"], tags=["subject:science"]),
            TopicNode(topic_id="lens", title="凸透镜", difficulty=2, parent_ids=["light"], prerequisite_ids=["light"], tags=["subject:science"]),
        ]
        backend.save_app_state(state)

        captured_prompt = []

        def mock_create(**kwargs):
            messages = kwargs.get("messages", [])
            user_msg = messages[-1]["content"] if messages else ""
            captured_prompt.append(user_msg)
            return _llm_resp({"exists": False, "node_id": None, "parent_ids": ["light"], "successor_ids": [], "reason": "ok"})

        backend.llm_skill._orig = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create

        try:
            locator = GraphLocator(backend, "science")
            locator.locate("光的色散", "白光分解为七色光")
            assert len(captured_prompt) == 1
            assert '"root"' in captured_prompt[0]
            assert '"light"' in captured_prompt[0]
            assert '"lens"' in captured_prompt[0]
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig
