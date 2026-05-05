from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.core.enums import LearningPhase
from src.core.models import TopicNode
from src.services.graph_search import GraphSearchAgent, SearchResult
from src.services.session_backend import SessionBackend


def _build_search_backend(tmp_path: Path) -> SessionBackend:
    backend = SessionBackend()
    backend.state_file = tmp_path / "state.json"
    backend.state_db_file = str(tmp_path / "state.db")
    backend.log_file = tmp_path / "decision_trace.jsonl"

    state = backend.load_app_state()
    state.learning.current_phase = LearningPhase.LEARNING
    state.curriculum.topics = [
        TopicNode(
            topic_id="eng_present_continuous",
            title="现在进行时",
            difficulty=1,
            tags=["subject:language", "facet:grammar", "language:english"],
        ),
        TopicNode(
            topic_id="eng_simple_past",
            title="一般过去时",
            difficulty=1,
            tags=["subject:language", "facet:grammar", "language:english"],
        ),
        TopicNode(
            topic_id="chi_reading",
            title="阅读理解",
            difficulty=2,
            tags=["subject:language", "facet:reading", "language:chinese"],
        ),
        TopicNode(
            topic_id="eng_reading",
            title="Reading Comprehension",
            difficulty=2,
            tags=["subject:language", "facet:reading", "language:english"],
        ),
        TopicNode(
            topic_id="math_addition",
            title="一位数加法",
            difficulty=1,
            tags=["subject:math", "facet:operation"],
        ),
    ]
    backend.save_app_state(state)
    return backend


def _make_mock_response(finish_reason, *, content=None, tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    if tool_calls:
        msg.model_dump.return_value = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        }
    else:
        msg.model_dump.return_value = {"role": "assistant", "content": content}
    choice = SimpleNamespace(finish_reason=finish_reason, message=msg)
    return SimpleNamespace(choices=[choice])


def _make_tool_call(call_id, name, arguments):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


class TestToolFunctions:
    def test_list_topics_by_subject_facet_filters_by_language(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "english")
        topics = agent._list_topics_by_subject_facet()
        titles = {t["title"] for t in topics}
        assert "现在进行时" in titles
        assert "一般过去时" in titles
        assert "Reading Comprehension" in titles

    def test_list_topics_by_subject_facet_filters_chinese(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "chinese")
        topics = agent._list_topics_by_subject_facet()
        titles = {t["title"] for t in topics}
        assert "阅读理解" in titles
        assert "现在进行时" not in titles

    def test_list_topics_by_subject_facet_with_facet(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "english")
        topics = agent._list_topics_by_subject_facet(facet="grammar")
        titles = {t["title"] for t in topics}
        assert "现在进行时" in titles
        assert "一般过去时" in titles
        assert "Reading Comprehension" not in titles

    def test_list_topics_by_math_subject(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "math")
        topics = agent._list_topics_by_subject_facet()
        titles = {t["title"] for t in topics}
        assert "一位数加法" in titles

    def test_search_topics_by_title_exact_chinese(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "english")
        results = agent._search_topics_by_title("现在进行时")
        assert len(results) > 0
        assert results[0]["topic_id"] == "eng_present_continuous"

    def test_search_topics_by_title_english_substring(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "english")
        results = agent._search_topics_by_title("Reading")
        assert len(results) > 0
        assert results[0]["topic_id"] == "eng_reading"

    def test_search_topics_by_title_no_match(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "english")
        results = agent._search_topics_by_title("黑洞蒸发")
        assert len(results) == 0

    def test_search_topics_by_title_cross_language(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "chinese")
        results = agent._search_topics_by_title("Reading Comprehension")
        assert len(results) > 0
        assert results[0]["topic_id"] == "eng_reading"

    def test_get_topic_detail(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "english")
        detail = agent._get_topic_detail("eng_present_continuous")
        assert detail is not None
        assert detail["title"] == "现在进行时"
        assert "subject:language" in detail["tags"]

    def test_get_topic_detail_missing(self, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        agent = GraphSearchAgent(backend, "language", "english")
        detail = agent._get_topic_detail("nonexistent")
        assert detail is None


class TestSearchResultParsing:
    def test_parse_link(self):
        agent = GraphSearchAgent.__new__(GraphSearchAgent)
        raw = '{"decision":"link","matched_topic_id":"eng_present_continuous","matched_title":"现在进行时","parent_node_ids":[],"confidence":0.95,"reason":"精确匹配","proposed_title":null}'
        result = agent._parse_search_result(raw)
        assert result.decision == "link"
        assert result.matched_topic_id == "eng_present_continuous"
        assert result.confidence == 0.95

    def test_parse_propose(self):
        agent = GraphSearchAgent.__new__(GraphSearchAgent)
        raw = '{"decision":"propose","matched_topic_id":null,"matched_title":null,"parent_node_ids":["eng_root"],"confidence":0.8,"reason":"新概念","proposed_title":"黑洞蒸发"}'
        result = agent._parse_search_result(raw)
        assert result.decision == "propose"
        assert result.proposed_title == "黑洞蒸发"
        assert result.parent_node_ids == ["eng_root"]

    def test_parse_with_markdown_wrapper(self):
        agent = GraphSearchAgent.__new__(GraphSearchAgent)
        raw = '```json\n{"decision":"ambiguous","matched_topic_id":null,"matched_title":null,"parent_node_ids":[],"confidence":0.5,"reason":"模糊","proposed_title":null}\n```'
        result = agent._parse_search_result(raw)
        assert result.decision == "ambiguous"

    def test_parse_invalid_json(self):
        agent = GraphSearchAgent.__new__(GraphSearchAgent)
        result = agent._parse_search_result("not json")
        assert result.decision == "ambiguous"

    def test_parse_rerank(self):
        agent = GraphSearchAgent.__new__(GraphSearchAgent)
        raw = '[{"topic_id":"a","relevance":"high"},{"topic_id":"b","relevance":"low"}]'
        result = agent._parse_rerank_result(raw)
        assert len(result) == 2
        assert result[0]["relevance"] == "high"


class TestSearchAgentE2E:
    def test_exact_match_returns_link(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        call_log = []

        def mock_create(**kwargs):
            call_log.append(kwargs.get("tools") is not None)
            if len(call_log) == 1:
                tc = _make_tool_call("call_1", "search_topics_by_title", {"query": "现在进行时"})
                return _make_mock_response("tool_calls", tool_calls=[tc])
            return _make_mock_response(
                "stop",
                content='{"decision":"link","matched_topic_id":"eng_present_continuous","matched_title":"现在进行时","parent_node_ids":[],"confidence":0.95,"reason":"exact title match","proposed_title":null}',
            )

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "language", "english")
        result = agent.search("现在进行时")
        assert result.decision == "link"
        assert result.matched_topic_id == "eng_present_continuous"
        assert result.confidence >= 0.55

    def test_alias_match_returns_link(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        call_log = []

        def mock_create(**kwargs):
            call_log.append(kwargs.get("tools") is not None)
            if len(call_log) == 1:
                tc = _make_tool_call("call_1", "search_topics_by_title", {"query": "present continuous"})
                return _make_mock_response("tool_calls", tool_calls=[tc])
            return _make_mock_response(
                "stop",
                content='{"decision":"link","matched_topic_id":"eng_present_continuous","matched_title":"现在进行时","parent_node_ids":[],"confidence":0.88,"reason":"alias match via search and rerank","proposed_title":null}',
            )

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "language", "english")
        result = agent.search("present continuous is used for ongoing actions")
        assert result.decision == "link"
        assert result.matched_topic_id == "eng_present_continuous"

    def test_no_match_returns_propose(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        call_log = []

        def mock_create(**kwargs):
            call_log.append(kwargs.get("tools") is not None)
            if len(call_log) == 1:
                tc = _make_tool_call("call_1", "search_topics_by_title", {"query": "黑洞蒸发"})
                return _make_mock_response("tool_calls", tool_calls=[tc])
            return _make_mock_response(
                "stop",
                content='{"decision":"propose","matched_topic_id":null,"matched_title":null,"parent_node_ids":[],"confidence":0.85,"reason":"no existing topic for this concept","proposed_title":"黑洞蒸发"}',
            )

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "language", "english")
        result = agent.search("黑洞蒸发是霍金提出的理论")
        assert result.decision == "propose"
        assert result.proposed_title == "黑洞蒸发"

    def test_cross_language_no_link(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        call_log = []

        def mock_create(**kwargs):
            call_log.append(kwargs.get("tools") is not None)
            if len(call_log) == 1:
                tc = _make_tool_call("call_1", "search_topics_by_title", {"query": "阅读理解"})
                return _make_mock_response("tool_calls", tool_calls=[tc])
            return _make_mock_response(
                "stop",
                content='{"decision":"propose","matched_topic_id":null,"matched_title":null,"parent_node_ids":[],"confidence":0.8,"reason":"english reading is a different concept","proposed_title":"阅读理解"}',
            )

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "language", "english")
        result = agent.search("阅读理解")
        assert result.decision == "propose"

    def test_search_handles_error_gracefully(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)

        def mock_create(**kwargs):
            raise RuntimeError("API error")

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "language", "english")
        result = agent.search("现在进行时")
        assert result.decision == "propose"
        assert "error" in result.reason


class TestDeduplicateCandidateTitle:
    def test_exact_synonym_merge(self, monkeypatch, tmp_path: Path):
        from src.services.resource_graph_curation import deduplicate_candidate_title

        backend = _build_search_backend(tmp_path)
        existing = [
            {"topic_id": "math_01", "title": "实数完备性", "subject": "math", "facet": "concept", "language_id": None, "tags": ["subject:math"]},
        ]

        def mock_create(**kwargs):
            msg = MagicMock()
            msg.content = '{"matched_topic_id": "math_01"}'
            choice = SimpleNamespace(message=msg)
            return SimpleNamespace(choices=[choice])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        result = deduplicate_candidate_title(
            backend=backend,
            candidate_title="实数的完备性",
            candidate_subject="math",
            candidate_facet="concept",
            candidate_text="实数的完备性讲解",
            existing_nodes=existing,
        )
        assert result == "math_01"

    def test_cross_language_grammar_merge(self, monkeypatch, tmp_path: Path):
        from src.services.resource_graph_curation import deduplicate_candidate_title

        backend = _build_search_backend(tmp_path)
        existing = [
            {"topic_id": "eng_grammar_01", "title": "现在进行时", "subject": "language", "facet": "grammar", "language_id": "english", "tags": ["subject:language", "language:english"]},
        ]

        def mock_create(**kwargs):
            msg = MagicMock()
            msg.content = '{"matched_topic_id": "eng_grammar_01"}'
            choice = SimpleNamespace(message=msg)
            return SimpleNamespace(choices=[choice])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        result = deduplicate_candidate_title(
            backend=backend,
            candidate_title="Present Continuous",
            candidate_subject="language",
            candidate_facet="grammar",
            candidate_text="Present Continuous describes ongoing actions",
            candidate_language_id="english",
            existing_nodes=existing,
        )
        assert result == "eng_grammar_01"

    def test_different_concepts_no_merge(self, monkeypatch, tmp_path: Path):
        from src.services.resource_graph_curation import deduplicate_candidate_title

        backend = _build_search_backend(tmp_path)
        existing = [
            {"topic_id": "math_01", "title": "介值性定理", "subject": "math", "facet": "concept", "language_id": None, "tags": ["subject:math"]},
        ]

        def mock_create(**kwargs):
            msg = MagicMock()
            msg.content = '{"matched_topic_id": null}'
            choice = SimpleNamespace(message=msg)
            return SimpleNamespace(choices=[choice])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        result = deduplicate_candidate_title(
            backend=backend,
            candidate_title="零点定理",
            candidate_subject="math",
            candidate_facet="concept",
            candidate_text="零点定理是数学分析中的重要定理",
            existing_nodes=existing,
        )
        assert result is None

    def test_cross_language_no_merge(self, monkeypatch, tmp_path: Path):
        from src.services.resource_graph_curation import deduplicate_candidate_title

        backend = _build_search_backend(tmp_path)
        existing = [
            {"topic_id": "eng_reading", "title": "阅读理解", "subject": "language", "facet": "reading", "language_id": "english", "tags": ["subject:language", "language:english"]},
        ]

        def mock_create(**kwargs):
            msg = MagicMock()
            msg.content = '{"matched_topic_id": null}'
            choice = SimpleNamespace(message=msg)
            return SimpleNamespace(choices=[choice])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        result = deduplicate_candidate_title(
            backend=backend,
            candidate_title="阅读理解",
            candidate_subject="language",
            candidate_facet="reading",
            candidate_text="分析文章结构，回答课后问题",
            candidate_language_id="chinese",
            existing_nodes=existing,
        )
        assert result is None

    def test_same_title_different_domain_no_merge(self, monkeypatch, tmp_path: Path):
        from src.services.resource_graph_curation import deduplicate_candidate_title

        backend = _build_search_backend(tmp_path)
        existing = [
            {"topic_id": "eng_writing", "title": "英语写作", "subject": "language", "facet": "writing", "language_id": "english", "tags": ["subject:language", "language:english"]},
        ]

        def mock_create(**kwargs):
            msg = MagicMock()
            msg.content = '{"matched_topic_id": null}'
            choice = SimpleNamespace(message=msg)
            return SimpleNamespace(choices=[choice])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        result = deduplicate_candidate_title(
            backend=backend,
            candidate_title="语文写作",
            candidate_subject="language",
            candidate_facet="writing",
            candidate_text="学习写记叙文和议论文",
            candidate_language_id="chinese",
            existing_nodes=existing,
        )
        assert result is None

    def test_empty_candidates_returns_none(self, monkeypatch, tmp_path: Path):
        from src.services.resource_graph_curation import deduplicate_candidate_title

        backend = _build_search_backend(tmp_path)
        result = deduplicate_candidate_title(
            backend=backend,
            candidate_title="新概念",
            candidate_subject="math",
            candidate_facet="concept",
            candidate_text="text",
            existing_nodes=[],
        )
        assert result is None


class TestInferPrerequisites:
    def test_simple_prereq_chain(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        state = backend.load_app_state(include_history=False)
        state.curriculum.topics.append(
            TopicNode(
                topic_id="math_count", title="数数", difficulty=1,
                prerequisite_ids=[], tags=["subject:math", "facet:concept"],
            )
        )
        backend.save_app_state(state)

        responses: list[list[dict]] = [
            [{"keyword": "数数", "priority": "direct"}],
            [],
        ]

        def mock_create(**kwargs):
            data = responses.pop(0) if responses else []
            msg = MagicMock()
            msg.content = json.dumps(data)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "math")
        result = agent.infer_prerequisites("加法", "学习加法运算", max_depth=2)
        assert len(result) == 1
        assert result[0]["topic_id"] == "math_count"
        assert result[0]["depth"] == 1
        assert result[0]["relation"] == "requires"

    def test_multi_step_prereq_chain(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        state = backend.load_app_state(include_history=False)
        state.curriculum.topics.append(
            TopicNode(
                topic_id="math_add", title="加法运算", difficulty=1,
                prerequisite_ids=[], tags=["subject:math", "facet:operation"],
            )
        )
        state.curriculum.topics.append(
            TopicNode(
                topic_id="math_count", title="数数基础", difficulty=1,
                prerequisite_ids=[], tags=["subject:math", "facet:concept"],
            )
        )
        backend.save_app_state(state)

        responses: list[list[dict]] = [
            [{"keyword": "加法运算", "priority": "direct"}, {"keyword": "重复加", "priority": "direct"}],
            [{"keyword": "数数基础", "priority": "direct"}],
            [],
        ]

        def mock_create(**kwargs):
            data = responses.pop(0) if responses else []
            msg = MagicMock()
            msg.content = json.dumps(data)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "math")
        result = agent.infer_prerequisites("乘法", "乘法是基于重复加的运算", max_depth=2)
        tids = {r["topic_id"] for r in result}
        assert "math_add" in tids
        assert "math_count" in tids
        assert any(r["depth"] == 1 and r["topic_id"] == "math_add" for r in result)
        assert any(r["depth"] == 2 and r["topic_id"] == "math_count" for r in result)

    def test_prereq_not_found_returns_empty(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)

        responses: list[list[dict]] = [
            [{"keyword": "黎曼几何", "priority": "direct"}, {"keyword": "张量分析", "priority": "direct"}],
        ]

        def mock_create(**kwargs):
            data = responses.pop(0) if responses else []
            msg = MagicMock()
            msg.content = json.dumps(data)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "physics")
        result = agent.infer_prerequisites("广义相对论", "广义相对论是爱因斯坦的引力理论", max_depth=2)
        assert result == []

    def test_language_grammar_prereqs(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        state = backend.load_app_state(include_history=False)
        state.curriculum.topics.append(
            TopicNode(
                topic_id="eng_simple_present", title="一般现在时", difficulty=1,
                prerequisite_ids=[], tags=["subject:language", "facet:grammar", "language:english"],
            )
        )
        state.curriculum.topics.append(
            TopicNode(
                topic_id="eng_be_verb", title="be动词", difficulty=1,
                prerequisite_ids=[], tags=["subject:language", "facet:grammar", "language:english"],
            )
        )
        backend.save_app_state(state)

        responses: list[list[dict]] = [
            [{"keyword": "一般现在时", "priority": "direct"}, {"keyword": "be动词", "priority": "direct"}],
            [],
            [],
        ]

        def mock_create(**kwargs):
            data = responses.pop(0) if responses else []
            msg = MagicMock()
            msg.content = json.dumps(data)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "language", "english")
        result = agent.infer_prerequisites("现在进行时", "现在进行时描述正在发生的动作", max_depth=2)
        tids = {r["topic_id"] for r in result}
        assert "eng_simple_present" in tids
        assert "eng_be_verb" in tids

    def test_cross_subject_no_inference(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        state = backend.load_app_state(include_history=False)
        state.curriculum.topics.append(
            TopicNode(
                topic_id="eng_grammar_01", title="现在进行时", difficulty=1,
                prerequisite_ids=[], tags=["subject:language", "facet:grammar", "language:english"],
            )
        )
        state.curriculum.topics.append(
            TopicNode(
                topic_id="physics_velocity", title="速度", difficulty=1,
                prerequisite_ids=[], tags=["subject:physics", "facet:quantity"],
            )
        )
        backend.save_app_state(state)

        responses: list[list[dict]] = [
            [{"keyword": "速度", "priority": "direct"}, {"keyword": "距离", "priority": "direct"}],
        ]

        def mock_create(**kwargs):
            data = responses.pop(0) if responses else []
            msg = MagicMock()
            msg.content = json.dumps(data)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "physics")
        result = agent.infer_prerequisites("速度公式", "速度公式 v=d/t", max_depth=2)
        tids = {r["topic_id"] for r in result}
        assert "eng_grammar_01" not in tids
        if "physics_velocity" in tids:
            assert len(result) >= 1

    def test_depth_truncation(self, monkeypatch, tmp_path: Path):
        backend = _build_search_backend(tmp_path)
        state = backend.load_app_state(include_history=False)
        state.curriculum.topics.extend(
            [
                TopicNode(
                    topic_id="math_a", title="A概念", difficulty=1,
                    prerequisite_ids=[], tags=["subject:math", "facet:concept"],
                ),
                TopicNode(
                    topic_id="math_b", title="B概念", difficulty=1,
                    prerequisite_ids=[], tags=["subject:math", "facet:concept"],
                ),
                TopicNode(
                    topic_id="math_c", title="C概念", difficulty=1,
                    prerequisite_ids=[], tags=["subject:math", "facet:concept"],
                ),
            ]
        )
        backend.save_app_state(state)

        responses: list[list[dict]] = [
            [{"keyword": "A概念", "priority": "direct"}],
            [{"keyword": "B概念", "priority": "direct"}],
            [{"keyword": "C概念", "priority": "direct"}],
        ]

        def mock_create(**kwargs):
            data = responses.pop(0) if responses else []
            msg = MagicMock()
            msg.content = json.dumps(data)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        agent = GraphSearchAgent(backend, "math")
        result = agent.infer_prerequisites("根概念", "根概念描述", max_depth=2)
        assert all(r["depth"] <= 2 for r in result)
        depths = {r["depth"] for r in result}
        assert 1 in depths
        assert 3 not in depths

    def test_coarse_filter_skips_wrong_subject(self, monkeypatch, tmp_path: Path):
        from src.services.resource_graph_curation import deduplicate_candidate_title

        backend = _build_search_backend(tmp_path)
        existing = [
            {"topic_id": "eng_01", "title": "现在进行时", "subject": "language", "facet": "grammar", "language_id": "english", "tags": []},
        ]

        result = deduplicate_candidate_title(
            backend=backend,
            candidate_title="现在进行时",
            candidate_subject="math",
            candidate_facet="concept",
            candidate_text="text",
            existing_nodes=existing,
        )
        assert result is None

    def test_llm_error_returns_none(self, monkeypatch, tmp_path: Path):
        from src.services.resource_graph_curation import deduplicate_candidate_title

        backend = _build_search_backend(tmp_path)
        existing = [
            {"topic_id": "math_01", "title": "实数完备性", "subject": "math", "facet": "concept", "language_id": None, "tags": []},
        ]

        def mock_create(**kwargs):
            raise RuntimeError("API error")

        monkeypatch.setattr(backend.llm_skill.client.chat.completions, "create", mock_create)
        result = deduplicate_candidate_title(
            backend=backend,
            candidate_title="实数的完备性",
            candidate_subject="math",
            candidate_facet="concept",
            candidate_text="text",
            existing_nodes=existing,
        )
        assert result is None
