from __future__ import annotations

from pathlib import Path

from src.core.enums import LearningPhase
from src.core.models import GraphProposalRecord, ResourceRecord, TopicNode
from src.services.document_ingestion import ingest_document_resource
from src.services.resource_graph_curation import CandidateTopic, cluster_candidate_topics, normalize_candidate_title
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
    assert proposal.edge_type == "related"
    assert proposal.tags == ["subject:english", "facet:grammar"]
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

    proposal = next(rec for rec in backend.load_app_state(include_history=False).learning.graph_proposals if rec.proposal_id == segments[0].proposal_id)
    assert proposal.parent_node_ids == []
    assert "pending_subject_root=科学" in proposal.summary
    assert "pending_subject_root=科学" in proposal.reason


def test_existing_english_topic_is_linked_instead_of_creating_proposal(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.curriculum.topics.append(
        TopicNode(
            topic_id="english_present_continuous",
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


def test_existing_english_proposal_is_reused_instead_of_creating_duplicate(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    state = backend.load_app_state(include_history=False)
    state.learning.graph_proposals.append(
        GraphProposalRecord(
            proposal_id="proposal_present_continuous",
            title="现在进行时",
            summary="facet: grammar；支撑片段 1 个；代表片段：old",
            trigger="resource_ingest",
            tags=["subject:english", "facet:grammar"],
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


def test_weather_emotion_titles_are_clustered_after_normalization() -> None:
    first = normalize_candidate_title("天气如何影响我们的情绪？", subject="english", facet="culture_or_content")
    second = normalize_candidate_title("天气如何影响我们的心情？", subject="english", facet="culture_or_content")

    assert first == second == "天气如何影响我们的心情"

    clusters = cluster_candidate_topics(
        [
            CandidateTopic(
                segment_index=0,
                raw_title="天气如何影响我们的情绪？",
                normalized_title=first,
                subject="english",
                facet="culture_or_content",
                confidence=0.8,
                reason="候选 1",
                text="Weather can change how people feel.",
                edge_type="related",
            ),
            CandidateTopic(
                segment_index=1,
                raw_title="天气如何影响我们的心情？",
                normalized_title=second,
                subject="english",
                facet="culture_or_content",
                confidence=0.81,
                reason="候选 2",
                text="The weather affects our moods.",
                edge_type="related",
            ),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].title == "天气如何影响我们的心情"
    assert len(clusters[0].candidates) == 2
