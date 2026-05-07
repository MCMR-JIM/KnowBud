from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.services.document_analyzer import (
    SectionTopic,
    analyze_document_structure,
    _build_full_text,
    MAX_DOC_CHARS,
)
from src.services.session_backend import SessionBackend


@dataclass
class _FakeChunk:
    text: str
    locator: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.locator is None:
            self.locator = {}


def _build_backend(tmp_path: Path) -> SessionBackend:
    backend = SessionBackend()
    backend.state_file = tmp_path / "state.json"
    backend.state_db_file = str(tmp_path / "state.db")
    backend.log_file = tmp_path / "decision_trace.jsonl"
    backend.load_app_state()
    return backend


def _make_llm_response(content: str) -> object:
    msg = MagicMock()
    msg.content = content
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class TestBuildFullText:
    def test_short_text_unchanged(self):
        chunks = [_FakeChunk("hello"), _FakeChunk("world")]
        result = _build_full_text(chunks)
        assert result == "hello\n\nworld"

    def test_long_text_truncated(self):
        long_chunk = _FakeChunk("x" * (MAX_DOC_CHARS + 1000))
        result = _build_full_text([long_chunk])
        assert MAX_DOC_CHARS // 2 < len(result) <= MAX_DOC_CHARS + 100
        assert "[...中间部分已省略...]" in result


class TestAnalyzeDocumentStructure:
    def test_english_textbook_structure(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        llm_result = {
            "sections": [
                {
                    "label": "Unit 1 - 现在进行时",
                    "type": "lesson",
                    "topic_candidates": ["现在进行时", "be动词变位"],
                    "is_fuzzy": False,
                    "exercises": ["用现在进行时填空: He ___ (run) now."],
                },
                {
                    "label": "单词表 Unit 1",
                    "type": "word_list",
                    "topic_candidates": ["running", "swimming"],
                    "is_fuzzy": False,
                    "exercises": [],
                },
            ]
        }

        def mock_create(**kwargs):
            return _make_llm_response(json.dumps(llm_result))

        backend.llm_skill._orig_create = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create

        try:
            chunks = [
                _FakeChunk("Unit 1 - 现在进行时\n现在进行时描述正在发生的动作。"),
                _FakeChunk("单词表 Unit 1\nrunning 跑步, swimming 游泳"),
            ]
            sections = analyze_document_structure(
                backend=backend, chunks=chunks,
                subject="language", language_id="english",
            )
            assert len(sections) == 2
            assert sections[0].section_type == "lesson"
            assert "现在进行时" in sections[0].topic_candidates
            assert len(sections[0].bound_exercises) == 1
            assert sections[1].section_type == "word_list"
            assert sections[1].topic_candidates == []  # word_list skipped
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig_create

    def test_fuzzy_section_triggers_deep_read(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        call_count = [0]

        def mock_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_response(json.dumps({
                    "sections": [
                        {"label": "模糊段落", "type": "lesson", "topic_candidates": [],
                         "is_fuzzy": True, "exercises": []},
                    ]
                }))
            else:
                return _make_llm_response(json.dumps({
                    "topic_candidates": ["隐藏主题"]
                }))

        backend.llm_skill._orig_create = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create

        try:
            chunks = [_FakeChunk("模糊段落\n这是一些没有明显主题的文本内容，讨论了很多东西。")]
            sections = analyze_document_structure(
                backend=backend, chunks=chunks, subject="language",
            )
            assert len(sections) == 1
            assert call_count[0] >= 2  # structure call + fuzzy read call
            assert not sections[0].is_fuzzy
            assert "隐藏主题" in sections[0].topic_candidates
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig_create

    def test_exercises_bound_correctly(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        llm_result = {
            "sections": [
                {"label": "练习课", "type": "exercise", "topic_candidates": [],
                 "is_fuzzy": False, "exercises": ["1. 3 + 2 = ___", "2. 5 - 1 = ___"]},
            ]
        }

        def mock_create(**kwargs):
            return _make_llm_response(json.dumps(llm_result))

        backend.llm_skill._orig_create = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create

        try:
            chunks = [_FakeChunk("练习课\n1. 3 + 2 = ___\n2. 5 - 1 = ___")]
            sections = analyze_document_structure(
                backend=backend, chunks=chunks, subject="math",
            )
            assert len(sections) == 1
            assert sections[0].section_type == "exercise"
            assert len(sections[0].bound_exercises) == 2
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig_create

    def test_empty_chunks_returns_empty(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        sections = analyze_document_structure(
            backend=backend, chunks=[], subject="math",
        )
        assert sections == []

    def test_llm_failure_graceful_degradation(self, tmp_path: Path):
        backend = _build_backend(tmp_path)
        backend.llm_skill.client.api_key = "test_key"

        def mock_create(**kwargs):
            raise RuntimeError("LLM API error")

        backend.llm_skill._orig_create = backend.llm_skill.client.chat.completions.create
        backend.llm_skill.client.chat.completions.create = mock_create

        try:
            chunks = [_FakeChunk("Some text about math.")]
            sections = analyze_document_structure(
                backend=backend, chunks=chunks, subject="math",
            )
            assert sections == []
        finally:
            backend.llm_skill.client.chat.completions.create = backend.llm_skill._orig_create
