from __future__ import annotations

from pathlib import Path

from src.core.enums import LearningPhase
from src.core.models import GraphProposalRecord, ResourceRecord, ResourceSegment, TopicNode
from src.services.document_ingestion import ingest_document_resource
from src.services.resource_graph_curation import CandidateTopic, cluster_candidate_topics, detect_resource_subject, normalize_candidate_title
from src.services.session_backend import SessionBackend


def _build_backend(tmp_path: Path) -> SessionBackend:
    backend = SessionBackend()
    backend.state_file = tmp_path / "state.json"
    backend.state_db_file = str(tmp_path / "state.db")
    backend.log_file = tmp_path / "decision_trace.jsonl"

    state = backend.load_app_state()
    state.learning.current_phase = LearningPhase.LEARNING
    state.learning.current_topic_id = "demo_01"
    state.curriculum.topics = [
        TopicNode(topic_id="demo_01", title="恐龙为什么会灭绝？", difficulty=1, prerequisite_ids=[], tags=["恐龙", "灭绝"]),
    ]
    backend.save_app_state(state)
    return backend


def _create_record(tmp_path: Path, backend: SessionBackend, *, name: str, content: str) -> ResourceRecord:
    source_path = tmp_path / "sample.txt"
    source_path.write_text(content, encoding="utf-8")
    return backend.create_resource_record(
        topic_id="demo_01",
        resource_name=name,
        category="learn",
        media_type="txt",
        mime_type="text/plain",
        original_filename="sample.txt",
        stored_path=str(source_path),
        size_bytes=source_path.stat().st_size,
    )


def test_english_resource_aggregates_proposals_and_backfills_segments(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    def fake_classify_or_propose(*, chunk_text: str, topics: list[TopicNode], default_parent_topic_id: str | None = None) -> dict[str, object]:
        if "running in the park" in chunk_text:
            return {
                "decision": "propose",
                "topic_id": None,
                "confidence": 0.86,
                "reason": "讲 be + v-ing 结构",
                "proposed_topic": {
                    "title": "现在进行时与一般现在时的区别",
                    "summary": "比较两种时态",
                    "parent_node_ids": ["demo_01"],
                    "edge_type": "requires",
                },
            }
        if "is reading a book" in chunk_text:
            return {
                "decision": "propose",
                "topic_id": None,
                "confidence": 0.84,
                "reason": "继续讲正在发生的动作",
                "proposed_topic": {
                    "title": "现在进行时",
                    "summary": "描述正在发生的动作",
                    "parent_node_ids": ["demo_01"],
                    "edge_type": "requires",
                },
            }
        if "Role-play" in chunk_text:
            return {
                "decision": "propose",
                "topic_id": None,
                "confidence": 0.8,
                "reason": "课堂活动说明",
                "proposed_topic": {
                    "title": "如何设计动物园",
                    "summary": "课堂活动",
                    "parent_node_ids": ["demo_01"],
                    "edge_type": "requires",
                },
            }
        return {"decision": "unclassified", "topic_id": None, "confidence": 0.2, "reason": "无法判断", "proposed_topic": None}

    backend.llm_skill.classify_or_propose_resource_chunk = fake_classify_or_propose
    record = _create_record(
        tmp_path,
        backend,
        name="七年级英语现在进行时",
        content=(
            "Listen and read. The boy is running in the park now. 这是现在进行时语法。\n\n"
            "Look and say. She is reading a book now. 继续学习现在进行时。\n\n"
            "Role-play. Work in groups and design a zoo for your class."
        ),
    )

    topics = backend.load_app_state(include_history=False).curriculum.topics
    segments = ingest_document_resource(backend=backend, record=record, topics=topics, default_topic_id="demo_01")

    assert len(segments) == 3
    assert segments[0].proposal_id
    assert segments[0].proposal_id == segments[1].proposal_id
    assert segments[0].proposed_topic_title == "现在进行时"
    assert segments[1].proposed_topic_title == "现在进行时"
    assert segments[2].status == "unclassified"
    assert segments[2].proposal_id is None

    state = backend.load_app_state(include_history=False)
    proposals = state.learning.graph_proposals
    assert any(proposal.title == "英语" for proposal in proposals)

    content_proposals = [proposal for proposal in proposals if proposal.title == "现在进行时"]
    assert len(content_proposals) == 1
    proposal = content_proposals[0]
    assert proposal.parent_node_ids == []
    assert proposal.edge_type == "part_of"
    assert proposal.tags == ["subject:language", "facet:grammar", "language:english"]
    assert "支撑片段 2 个" in proposal.summary
    assert all(parent_id != "demo_01" for parent_id in proposal.parent_node_ids)
    assert not any(item.title == "如何设计动物园" for item in proposals)


def test_activity_words_do_not_filter_real_english_grammar_candidates(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.88,
        "reason": "Grammar Focus chunk",
        "proposed_topic": {
            "title": "Grammar Focus: 现在进行时",
            "summary": "present continuous",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(
        tmp_path,
        backend,
        name="英语语法活动混合",
        content="Grammar Focus. Present continuous. Complete the passage and role-play with your partner.",
    )

    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    assert len(segments) == 1
    assert segments[0].status == "proposed"
    assert segments[0].proposal_id is not None
    assert segments[0].proposed_topic_title == "现在进行时"


def test_science_resource_uploaded_under_demo_topic_does_not_parent_demo_01(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.83,
        "reason": "physics formula concept",
        "proposed_topic": {
            "title": "速度公式",
            "summary": "v=d/t",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="初中物理速度", content="速度公式 v = d / t，用于描述路程、时间和速度的关系。")

    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    proposals = backend.load_app_state(include_history=False).learning.graph_proposals
    proposal = next(rec for rec in proposals if rec.proposal_id == segments[0].proposal_id)
    root = next(rec for rec in proposals if rec.title in {"物理", "科学"})
    assert proposal.parent_node_ids == []
    assert proposal.pending_parent_proposal_ids == [root.proposal_id]
    assert proposal.tags[0] in {"subject:science", "subject:physics"}


def test_approving_root_proposal_backfills_child_parent(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.83,
        "reason": "physics formula concept",
        "proposed_topic": {
            "title": "速度公式",
            "summary": "v=d/t",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="初中物理速度", content="速度公式 v = d / t，用于描述路程、时间和速度的关系。")
    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    proposals = backend.load_app_state(include_history=False).learning.graph_proposals
    child = next(rec for rec in proposals if rec.proposal_id == segments[0].proposal_id)
    root = next(rec for rec in proposals if rec.proposal_id == child.pending_parent_proposal_ids[0])

    _state, _root_proposal, root_topic, _relinked_count, _rescanned_count = backend.approve_graph_proposal(
        proposal_id=root.proposal_id,
        difficulty=1,
    )
    updated_child = next(
        rec
        for rec in backend.load_app_state(include_history=False).learning.graph_proposals
        if rec.proposal_id == child.proposal_id
    )
    assert updated_child.parent_node_ids == [root_topic.topic_id]
    assert updated_child.pending_parent_proposal_ids == []

    _state, _child_proposal, child_topic, _relinked_count, _rescanned_count = backend.approve_graph_proposal(
        proposal_id=child.proposal_id,
        difficulty=1,
    )
    assert child_topic.prerequisite_ids == []


def test_existing_english_topic_is_linked_instead_of_creating_proposal(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.curriculum.topics.append(
        TopicNode(
            topic_id="english_present_continuous",
            title="现在进行时",
            difficulty=1,
            prerequisite_ids=[],
            tags=["subject:language", "facet:grammar", "language:english"],
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.84,
        "reason": "present continuous chunk",
        "proposed_topic": {
            "title": "Present continuous",
            "summary": "be doing",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="英语现在进行时复用 topic", content="Present continuous: She is reading now.")

    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    assert segments[0].status == "classified"
    assert segments[0].decision == "link"
    assert segments[0].topic_id == "english_present_continuous"
    assert segments[0].proposal_id is None
    assert not any(rec.title == "现在进行时" for rec in backend.load_app_state(include_history=False).learning.graph_proposals)
    assert not any(rec.title == "语言" for rec in backend.load_app_state(include_history=False).learning.graph_proposals)


def test_legacy_subject_english_topic_is_linked_instead_of_creating_proposal(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.curriculum.topics.append(
        TopicNode(
            topic_id="legacy_english_present_continuous",
            title="现在进行时",
            difficulty=1,
            prerequisite_ids=[],
            tags=["subject:english", "facet:grammar"],
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.84,
        "reason": "present continuous chunk",
        "proposed_topic": {
            "title": "Present continuous",
            "summary": "be doing",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(
        tmp_path,
        backend,
        name="英语现在进行时复用旧 topic",
        content="Present continuous: She is reading now.",
    )

    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    assert segments[0].status == "classified"
    assert segments[0].decision == "link"
    assert segments[0].topic_id == "legacy_english_present_continuous"
    assert segments[0].proposal_id is None


def test_existing_english_proposal_is_reused_instead_of_creating_duplicate(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.learning.graph_proposals.append(
        GraphProposalRecord(
            proposal_id="proposal_present_continuous",
            title="现在进行时",
            summary="facet: grammar；支撑片段 1 个；代表片段：old",
            trigger="resource_ingest",
            tags=["subject:language", "facet:grammar", "language:english"],
            parent_node_ids=[],
            edge_type="related",
            status="proposed",
            reason="existing proposal",
            created_ts="2026-05-04T00:00:00+00:00",
            updated_ts="2026-05-04T00:00:00+00:00",
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.84,
        "reason": "present continuous chunk",
        "proposed_topic": {
            "title": "现在进行时与一般现在时的区别",
            "summary": "be doing",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="英语现在进行时复用 proposal", content="Present continuous: He is running now.")

    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    assert segments[0].status == "proposed"
    assert segments[0].proposal_id == "proposal_present_continuous"
    proposals = backend.load_app_state(include_history=False).learning.graph_proposals
    assert [proposal.proposal_id for proposal in proposals].count("proposal_present_continuous") == 1
    assert len([proposal for proposal in proposals if proposal.title == "现在进行时"]) == 1
    assert not any(proposal.title == "语言" for proposal in proposals)


def test_reupload_same_english_resource_reuses_existing_proposal(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.85,
        "reason": "present continuous chunk",
        "proposed_topic": {
            "title": "现在进行时",
            "summary": "be doing",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }

    first = _create_record(tmp_path, backend, name="第一次上传", content="Present continuous: They are playing football.")
    first_segments = ingest_document_resource(
        backend=backend,
        record=first,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )
    first_proposal_id = first_segments[0].proposal_id
    assert first_proposal_id is not None

    second = _create_record(tmp_path, backend, name="第二次上传", content="Present continuous: We are watching TV now.")
    second_segments = ingest_document_resource(
        backend=backend,
        record=second,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    assert second_segments[0].proposal_id == first_proposal_id
    proposals = backend.load_app_state(include_history=False).learning.graph_proposals
    assert len([proposal for proposal in proposals if proposal.title == "现在进行时"]) == 1


def test_non_root_english_topic_is_not_used_as_parent(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.curriculum.topics.append(
        TopicNode(
            topic_id="english_present_continuous",
            title="现在进行时",
            difficulty=1,
            prerequisite_ids=[],
            tags=["subject:language", "facet:grammar", "language:english"],
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.86,
        "reason": "past tense chunk",
        "proposed_topic": {
            "title": "一般过去时",
            "summary": "simple past",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="英语一般过去时", content="English grammar: simple past tense.")

    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    proposal = next(rec for rec in backend.load_app_state(include_history=False).learning.graph_proposals if rec.proposal_id == segments[0].proposal_id and rec.title == "一般过去时")
    assert proposal.parent_node_ids == []
    assert len(proposal.pending_parent_proposal_ids) == 1
    assert proposal.parent_node_ids != ["english_present_continuous"]


def test_explicit_english_root_topic_is_used_as_parent(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.curriculum.topics.append(
        TopicNode(
            topic_id="english_root",
            title="英语",
            difficulty=1,
            prerequisite_ids=[],
            tags=["subject:language", "facet:root", "language:english"],
        )
    )
    state.curriculum.topics.append(
        TopicNode(
            topic_id="english_present_continuous",
            title="现在进行时",
            difficulty=1,
            prerequisite_ids=[],
            tags=["subject:language", "facet:grammar", "language:english"],
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.86,
        "reason": "past tense chunk",
        "proposed_topic": {
            "title": "一般过去时",
            "summary": "simple past",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="英语一般过去时", content="English grammar: simple past tense.")

    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    proposal = next(rec for rec in backend.load_app_state(include_history=False).learning.graph_proposals if rec.proposal_id == segments[0].proposal_id and rec.title == "一般过去时")
    assert proposal.parent_node_ids == ["english_root"]


def test_detect_resource_subject_identifies_english_teaching_material(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="七年级英语语法", content="Grammar Focus. Present continuous. Listen and repeat.")
    segments = [ResourceSegment(segment_id="seg_1", text="Grammar Focus. Present continuous. Listen and repeat.", proposed_topic_title="现在进行时")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject == "language"


def test_detect_resource_subject_identifies_chinese_reading_as_language(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="七年级语文阅读", content="阅读理解：分析课文主题和人物形象。")
    segments = [ResourceSegment(segment_id="seg_1", text="阅读理解：分析课文主题和人物形象。")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject == "language"


def test_detect_resource_subject_identifies_math_material(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="数学乘法", content="乘法和加法的关系，计算 3 x 4。")
    segments = [ResourceSegment(segment_id="seg_1", text="乘法和加法的关系，计算 3 x 4。")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject == "math"


def test_detect_resource_subject_treats_velocity_formula_as_physics(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="STEM reading", content="Velocity formula v=d/t. Distance, time, and speed describe motion.")
    segments = [ResourceSegment(segment_id="seg_1", text="Velocity formula v=d/t. Distance, time, and speed describe motion.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject in {"science", "physics"}
    assert subject != "language"


def test_detect_resource_subject_identifies_biology_material(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="生物细胞", content="Cell structure and function explain how organisms grow.")
    segments = [ResourceSegment(segment_id="seg_1", text="Cell structure and function explain how organisms grow.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject in {"biology", "science"}


def test_detect_resource_subject_identifies_history_material(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="历史事件", content="这场改革事件改变了王朝的政治结构。")
    segments = [ResourceSegment(segment_id="seg_1", text="这场改革事件改变了王朝的政治结构。")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject == "history"


def test_detect_resource_subject_treats_chinese_history_as_history_not_language(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="Chinese history", content="Chinese history covers important dynasties and reform events.")
    segments = [ResourceSegment(segment_id="seg_1", text="Chinese history covers important dynasties and reform events.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject == "history"


def test_detect_resource_subject_identifies_geography_material(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="地理地图与气候", content="地图技能帮助理解气候区域的分布。")
    segments = [ResourceSegment(segment_id="seg_1", text="地图技能帮助理解气候区域的分布。")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject == "geography"


def test_detect_resource_subject_treats_chinese_geography_as_geography_not_language(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="Chinese geography", content="Chinese geography studies climate regions and maps.")
    segments = [ResourceSegment(segment_id="seg_1", text="Chinese geography studies climate regions and maps.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject == "geography"


def test_detect_resource_subject_does_not_use_weather_word_alone_as_english(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="science article", content="Weather affects climate and energy transfer in the atmosphere.")
    segments = [ResourceSegment(segment_id="seg_1", text="Weather affects climate and energy transfer in the atmosphere.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject != "language"
    assert subject == "physics" or subject == "science" or subject == "general"


def test_detect_resource_subject_does_not_use_story_word_alone_as_language(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="science story", content="This story explains energy flow in an ecosystem.")
    segments = [ResourceSegment(segment_id="seg_1", text="This story explains energy flow in an ecosystem.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject != "language"


def test_detect_resource_subject_does_not_use_time_word_alone_as_language(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="physics timing", content="Time, distance, and speed are related quantities.")
    segments = [ResourceSegment(segment_id="seg_1", text="Time, distance, and speed are related quantities.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject in {"physics", "science", "general"}
    assert subject != "language"


def test_detect_resource_subject_emotion_does_not_match_motion(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="social emotions", content="Emotion changes how people respond in groups.")
    segments = [ResourceSegment(segment_id="seg_1", text="Emotion changes how people respond in groups.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject == "general"


def test_detect_resource_subject_excellent_does_not_match_cell(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    record = _create_record(tmp_path, backend, name="excellent writing", content="Excellent writing shows clear structure and detail.")
    segments = [ResourceSegment(segment_id="seg_1", text="Excellent writing shows clear structure and detail.")]
    subject = detect_resource_subject(record=record, segments=segments, topics=backend.load_app_state(include_history=False).curriculum.topics, default_topic_id="demo_01")
    assert subject in {"language", "general"}
    assert subject != "biology"


def test_english_and_chinese_reading_proposals_do_not_cross_reuse(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.learning.graph_proposals.append(
        GraphProposalRecord(
            proposal_id="proposal_english_reading",
            title="英语阅读理解",
            summary="facet: reading；支撑片段 1 个；代表片段：old",
            trigger="resource_ingest",
            tags=["subject:language", "facet:reading", "language:english"],
            parent_node_ids=[],
            edge_type="related",
            status="proposed",
            reason="existing proposal",
            created_ts="2026-05-04T00:00:00+00:00",
            updated_ts="2026-05-04T00:00:00+00:00",
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.85,
        "reason": "reading chunk",
        "proposed_topic": {
            "title": "阅读理解",
            "summary": "阅读材料分析",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="七年级语文阅读", content="阅读理解：分析课文结构和主题。")
    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    assert segments[0].proposal_id != "proposal_english_reading"
    chinese_proposal = next(rec for rec in backend.load_app_state(include_history=False).learning.graph_proposals if rec.proposal_id == segments[0].proposal_id)
    assert "language:chinese" in chinese_proposal.tags


def test_chinese_resource_creates_chinese_root_title(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.85,
        "reason": "reading chunk",
        "proposed_topic": {
            "title": "阅读理解",
            "summary": "阅读材料分析",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="七年级语文阅读", content="阅读理解：分析课文结构和主题。")
    ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )
    proposals = backend.load_app_state(include_history=False).learning.graph_proposals
    root = next(rec for rec in proposals if rec.title in {"语文", "中文"})
    assert root.tags == ["subject:language", "facet:root", "language:chinese"]


def test_chinese_resource_does_not_reuse_english_root(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.curriculum.topics.append(
        TopicNode(
            topic_id="english_root",
            title="英语",
            difficulty=1,
            prerequisite_ids=[],
            tags=["subject:language", "facet:root", "language:english"],
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.85,
        "reason": "reading chunk",
        "proposed_topic": {
            "title": "阅读理解",
            "summary": "阅读材料分析",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="七年级语文阅读", content="阅读理解：分析课文结构和主题。")
    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    proposals = backend.load_app_state(include_history=False).learning.graph_proposals
    content = next(rec for rec in proposals if rec.proposal_id == segments[0].proposal_id)
    root = next(rec for rec in proposals if rec.title == "语文")
    assert content.parent_node_ids == []
    assert content.pending_parent_proposal_ids == [root.proposal_id]
    assert any(rec.title == "语文" and "language:chinese" in rec.tags for rec in proposals)


def test_legacy_subject_english_proposal_is_reused(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.learning.graph_proposals.append(
        GraphProposalRecord(
            proposal_id="legacy_english_present_continuous",
            title="现在进行时",
            summary="legacy english proposal",
            trigger="resource_ingest",
            tags=["subject:english", "facet:grammar"],
            parent_node_ids=[],
            edge_type="related",
            status="proposed",
            reason="existing legacy proposal",
            created_ts="2026-05-04T00:00:00+00:00",
            updated_ts="2026-05-04T00:00:00+00:00",
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.84,
        "reason": "present continuous chunk",
        "proposed_topic": {
            "title": "Present continuous",
            "summary": "be doing",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(
        tmp_path,
        backend,
        name="英语现在进行时复用旧 proposal",
        content="English grammar: Present continuous. He is running now.",
    )

    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )

    proposals = backend.load_app_state(include_history=False).learning.graph_proposals
    assert segments[0].proposal_id == "legacy_english_present_continuous"
    assert len([rec for rec in proposals if rec.title == "现在进行时"]) == 1


def test_math_project_activity_is_filtered(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.8,
        "reason": "activity",
        "proposed_topic": {
            "title": "Math project",
            "summary": "project activity",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="数学项目活动", content="Project: work in groups and make a poster.")
    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )
    assert segments[0].status == "unclassified"
    assert backend.load_app_state(include_history=False).learning.graph_proposals == []


def test_physics_formula_exercise_still_generates_proposal(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.86,
        "reason": "formula exercise",
        "proposed_topic": {
            "title": "Speed formula exercise",
            "summary": "velocity formula",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }
    record = _create_record(tmp_path, backend, name="物理速度公式练习", content="Exercise: use the velocity formula v=d/t to solve speed problems.")
    segments = ingest_document_resource(
        backend=backend,
        record=record,
        topics=backend.load_app_state(include_history=False).curriculum.topics,
        default_topic_id="demo_01",
    )
    assert segments[0].status == "proposed"
    proposal = next(rec for rec in backend.load_app_state(include_history=False).learning.graph_proposals if rec.proposal_id == segments[0].proposal_id)
    assert proposal.title == "速度公式"
    assert proposal.tags[0] in {"subject:physics", "subject:science"}


def test_weather_emotion_titles_are_clustered_after_normalization() -> None:
    first = normalize_candidate_title("天气如何影响我们的情绪？", subject="language", facet="culture")
    second = normalize_candidate_title("天气如何影响我们的心情？", subject="language", facet="culture")

    assert first == second == "天气如何影响我们的心情"

    clusters = cluster_candidate_topics(
        [
            CandidateTopic(
                segment_index=0,
                raw_title="天气如何影响我们的情绪？",
                normalized_title=first,
                subject="language",
                language_id="english",
                facet="culture",
                confidence=0.8,
                reason="候选 1",
                text="Weather can change how people feel.",
                edge_type="related",
                proposed_parent_node_ids=[],
            ),
            CandidateTopic(
                segment_index=1,
                raw_title="天气如何影响我们的心情？",
                normalized_title=second,
                subject="language",
                language_id="english",
                facet="culture",
                confidence=0.81,
                reason="候选 2",
                text="The weather affects our moods.",
                edge_type="related",
                proposed_parent_node_ids=[],
            ),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].title == "天气如何影响我们的心情"
    assert len(clusters[0].candidates) == 2


def test_prerequisite_inference_on_new_cluster(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.client.api_key = "test_key"

    state = backend.load_app_state(include_history=False)
    state.curriculum.topics.append(
        TopicNode(
            topic_id="math_count", title="数数", difficulty=1,
            prerequisite_ids=[], tags=["subject:math", "facet:concept"],
        )
    )
    state.curriculum.topics.append(
        TopicNode(
            topic_id="math_add", title="加法运算", difficulty=1,
            prerequisite_ids=[], tags=["subject:math", "facet:operation"],
        )
    )
    backend.save_app_state(state)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.85,
        "reason": "new concept",
        "proposed_topic": {
            "title": "乘法",
            "summary": "乘法是重复加法",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
    }

    import json
    from unittest.mock import MagicMock
    from types import SimpleNamespace

    responses: list[list[dict]] = [
        [{"keyword": "加法运算", "priority": "direct"}],
        [],
    ]

    def mock_create(**kwargs):
        data = responses.pop(0) if responses else []
        msg = MagicMock()
        msg.content = json.dumps(data)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    backend.llm_skill._original_create = backend.llm_skill.client.chat.completions.create
    backend.llm_skill.client.chat.completions.create = mock_create

    try:
        record = _create_record(tmp_path, backend, name="数学乘法", content="学习乘法的基本概念 数学")
        topics = backend.load_app_state(include_history=False).curriculum.topics
        segments = ingest_document_resource(
            backend=backend, record=record, topics=topics, default_topic_id="demo_01",
        )
        assert len(segments) >= 1
        assert segments[0].decision == "propose", f"expected propose, got {segments[0].decision} with status {segments[0].status}"

        proposals = backend.load_app_state(include_history=False).learning.graph_proposals
        content_proposal = next(
            (p for p in proposals if p.title == "乘法"),
            None,
        )
        assert content_proposal is not None, f"proposal titles: {[p.title for p in proposals]}, segment status: {segments[0].status}, decision: {segments[0].decision}, proposed_title: {segments[0].proposed_topic_title}"
        prereq_ids = list(getattr(content_proposal, "prerequisite_node_ids", []))
        assert "math_add" in prereq_ids, f"expected math_add in prereqs, got {prereq_ids}"
    finally:
        backend.llm_skill.client.chat.completions.create = backend.llm_skill._original_create
