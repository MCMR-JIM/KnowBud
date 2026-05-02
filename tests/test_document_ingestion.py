from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from src.core.enums import LearningPhase
from src.core.models import TopicNode
from src.services.document_ingestion import ingest_document_resource
from src.services.session_backend import SessionBackend

app_module = importlib.import_module("src.api.app")


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
        TopicNode(topic_id="math_01", title="一位数加法", difficulty=1, prerequisite_ids=[], tags=["加法", "苹果"]),
        TopicNode(topic_id="chinese_01", title="看图说话", difficulty=1, prerequisite_ids=[], tags=["表达", "说话"]),
    ]
    backend.save_app_state(state)
    return backend


def _make_client(monkeypatch, tmp_path: Path, backend: SessionBackend) -> TestClient:
    data_root = tmp_path / "data"
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    runtime = app_module.SingleSessionRuntime(backend_factory=lambda: backend)
    monkeypatch.setattr(app_module, "get_backend", lambda: backend)
    monkeypatch.setattr(app_module, "get_runtime", lambda: runtime)
    return TestClient(app_module.app)


def test_upload_txt_ingests_segments_and_records_events(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    def fake_classify_or_propose(*, chunk_text: str, topics: list[TopicNode], default_parent_topic_id: str | None = None) -> dict[str, object]:
        if "恐龙" in chunk_text:
            return {
                "decision": "link",
                "topic_id": "demo_01",
                "confidence": 0.9,
                "reason": "片段讨论恐龙灭绝",
                "proposed_topic": None,
                "guiding_question": "你觉得恐龙为什么没能适应环境变化？",
                "teaching_hint": "从气候变化和适应能力引导孩子理解灭绝。",
            }
        if "苹果" in chunk_text or "加" in chunk_text:
            return {
                "decision": "propose",
                "topic_id": None,
                "confidence": 0.82,
                "reason": "片段讲小行星撞击后的气候链式变化，现有节点不够细",
                "proposed_topic": {
                    "title": "小行星撞击导致的气候变化",
                    "summary": "理解小行星撞击如何引发遮光、降温和生态变化",
                    "parent_node_ids": ["demo_01"],
                    "edge_type": "requires",
                },
                "guiding_question": "如果天空长期变暗，地球上的动物会遇到什么困难？",
                "teaching_hint": "用遮光、降温、食物减少串起链式影响。",
            }
        return {
            "decision": "unclassified",
            "topic_id": None,
            "confidence": 0.3,
            "reason": "内容过泛",
            "proposed_topic": None,
            "guiding_question": "",
            "teaching_hint": "",
        }

    backend.llm_skill.classify_or_propose_resource_chunk = fake_classify_or_propose
    client = _make_client(monkeypatch, tmp_path, backend)

    content = (
        "第一段： 恐龙生活在很久以前。科学家认为，小行星撞击地球可能导致气候变化，许多恐龙无法适应环境。\n\n"
        "第二段： 3 加 2 等于 5。我们可以先数 3 个苹果，再数 2 个苹果，一共有 5 个苹果。"
    )
    response = client.post(
        "/v1/resource/upload",
        data={"topic_id": "demo_01", "resource_name": "混合练习", "category": "learn"},
        files={"file": ("sample.txt", content.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    resource = payload["resource"]
    segments = resource["segments"]
    assert len(segments) == 2

    first = segments[0]
    assert first["sequence_index"] == 0
    assert first["status"] == "classified"
    assert first["topic_id"] == "demo_01"
    assert first["confidence"] == 0.9
    assert first["guiding_question"] == "你觉得恐龙为什么没能适应环境变化？"
    assert first["teaching_hint"] == "从气候变化和适应能力引导孩子理解灭绝。"
    assert first["locator"] == {"kind": "txt", "line_start": 1, "line_end": 1}
    assert "恐龙生活在很久以前" in first["text"]

    second = segments[1]
    assert second["sequence_index"] == 1
    assert second["status"] == "proposed"
    assert second["decision"] == "propose"
    assert second["topic_id"] is None
    assert second["proposal_id"]
    assert second["proposed_topic_title"] == "小行星撞击导致的气候变化"
    assert second["confidence"] == 0.82
    assert second["guiding_question"] == "如果天空长期变暗，地球上的动物会遇到什么困难？"
    assert second["teaching_hint"] == "用遮光、降温、食物减少串起链式影响。"
    assert second["locator"] == {"kind": "txt", "line_start": 3, "line_end": 3}
    assert "3 加 2 等于 5" in second["text"]

    resource_id = resource["resource_id"]
    segments_response = client.get(f"/v1/resource/{resource_id}/segments")
    assert segments_response.status_code == 200
    assert segments_response.json()["segments"] == segments

    events = client.get("/v1/session/events", params={"after": 0, "limit": 20})
    assert events.status_code == 200
    event_items = events.json()["events"]
    assert any(event["kind"] == "resource_uploaded" for event in event_items)
    ingested_payload = next(
        event["payload"]
        for event in event_items
        if event["kind"] == "resource_ingested" and event["payload"].get("resource_id") == resource_id
    )
    assert ingested_payload == {
        "resource_id": resource_id,
        "segment_count": 2,
        "classified_count": 1,
        "proposed_count": 1,
        "unclassified_count": 0,
        "parse_failed_count": 0,
        "unsupported_count": 0,
        "media_type": "txt",
    }

    graph_response = client.get("/v1/knowledge/graph")
    assert graph_response.status_code == 200
    proposals = graph_response.json()["proposals"]
    proposal = next((item for item in proposals if item["proposal_id"] == second["proposal_id"]), None)
    assert proposal is not None
    assert proposal["title"] == "小行星撞击导致的气候变化"
    assert proposal["summary"] == "理解小行星撞击如何引发遮光、降温和生态变化"
    assert proposal["trigger"] == "resource_ingest"
    assert proposal["parent_node_ids"] == ["demo_01"]
    assert proposal["edge_type"] == "requires"
    assert proposal["status"] == "proposed"

    state = backend.load_app_state(include_history=False)
    proposal_record = next(rec for rec in state.learning.graph_proposals if rec.proposal_id == second["proposal_id"])
    assert proposal_record.trigger == "resource_ingest"
    assert proposal_record.status == "proposed"
    assert proposal_record.parent_node_ids == ["demo_01"]


def test_document_ingestion_marks_null_and_low_confidence_as_unclassified(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    def fake_classify_or_propose(*, chunk_text: str, topics: list[TopicNode], default_parent_topic_id: str | None = None) -> dict[str, object]:
        if "泛泛" in chunk_text:
            return {"decision": "unclassified", "topic_id": None, "confidence": 0.3, "reason": "内容过泛", "proposed_topic": None}
        if "加" in chunk_text:
            return {
                "decision": "propose",
                "topic_id": None,
                "confidence": 0.4,
                "reason": "置信度不足",
                "proposed_topic": {
                    "title": "低置信度提案",
                    "summary": "不应创建",
                    "parent_node_ids": ["demo_01"],
                    "edge_type": "requires",
                },
            }
        return {"decision": "unclassified", "topic_id": None, "confidence": 0.2, "reason": "无法判断", "proposed_topic": None}

    backend.llm_skill.classify_or_propose_resource_chunk = fake_classify_or_propose

    source_path = tmp_path / "sample.txt"
    source_path.write_text("这是一段泛泛而谈的内容。\n\n3 加 2 等于 5。", encoding="utf-8")
    record = backend.create_resource_record(
        topic_id="demo_01",
        resource_name="待分类文本",
        category="learn",
        media_type="txt",
        mime_type="text/plain",
        original_filename="sample.txt",
        stored_path=str(source_path),
        size_bytes=source_path.stat().st_size,
    )

    topics = backend.load_app_state(include_history=False).curriculum.topics
    segments = ingest_document_resource(backend=backend, record=record, topics=topics)

    assert len(segments) == 2
    assert all(segment.status == "unclassified" for segment in segments)
    assert segments[0].topic_id is None
    assert segments[1].topic_id is None
    assert segments[1].decision == "unclassified"
    assert segments[1].proposal_id is None
    assert segments[1].confidence == 0.4
    assert backend.load_app_state(include_history=False).learning.graph_proposals == []

    stored_segments = backend.list_resource_segments(record.resource_id)
    assert [segment.status for segment in stored_segments] == ["unclassified", "unclassified"]


def test_upload_doc_does_not_fail_and_creates_unsupported_segment(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "unclassified",
        "topic_id": None,
        "confidence": 0.0,
        "reason": "不需要分类",
        "proposed_topic": None,
    }
    client = _make_client(monkeypatch, tmp_path, backend)

    response = client.post(
        "/v1/resource/upload",
        data={"topic_id": "demo_01", "resource_name": "旧文档", "category": "learn"},
        files={"file": ("legacy.doc", b"not-a-real-doc", "application/msword")},
    )

    assert response.status_code == 200
    segments = response.json()["resource"]["segments"]
    assert len(segments) == 1
    assert segments[0]["status"] in {"unsupported", "parse_failed"}
    assert segments[0]["locator"]["kind"] == "doc"


def test_get_topic_resources_includes_resources_matched_by_segment_topic(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    def fake_classify_or_propose(*, chunk_text: str, topics: list[TopicNode], default_parent_topic_id: str | None = None) -> dict[str, object]:
        if "恐龙" in chunk_text:
            return {"decision": "link", "topic_id": "demo_01", "confidence": 0.9, "reason": "片段讨论恐龙灭绝原因", "proposed_topic": None}
        if "加" in chunk_text or "苹果" in chunk_text:
            return {"decision": "link", "topic_id": "math_01", "confidence": 0.85, "reason": "片段讲一位数加法", "proposed_topic": None}
        return {"decision": "unclassified", "topic_id": None, "confidence": 0.3, "reason": "内容过泛", "proposed_topic": None}

    backend.llm_skill.classify_or_propose_resource_chunk = fake_classify_or_propose
    client = _make_client(monkeypatch, tmp_path, backend)

    content = (
        "第一段： 恐龙生活在很久以前。科学家认为，小行星撞击地球可能导致气候变化，许多恐龙无法适应环境。\n\n"
        "第二段： 3 加 2 等于 5。我们可以先数 3 个苹果，再数 2 个苹果，一共有 5 个苹果。"
    )
    upload_response = client.post(
        "/v1/resource/upload",
        data={"topic_id": "demo_01", "resource_name": "跨主题文本", "category": "learn"},
        files={"file": ("sample.txt", content.encode("utf-8"), "text/plain")},
    )

    assert upload_response.status_code == 200
    resource_id = upload_response.json()["resource"]["resource_id"]

    response = client.get("/v1/resource/topics/math_01")

    assert response.status_code == 200
    resources = response.json()["resources"]
    assert resources
    resource = next((item for item in resources if item["resource_id"] == resource_id), None)
    assert resource is not None
    assert any(segment["topic_id"] == "math_01" for segment in resource["segments"])
    assert any(segment["topic_id"] == "demo_01" for segment in resource["segments"])


def test_get_topic_teaching_cues_returns_guiding_questions(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "link",
        "topic_id": "demo_01",
        "confidence": 0.9,
        "reason": "片段讨论恐龙灭绝",
        "proposed_topic": None,
        "guiding_question": "你觉得恐龙为什么没能适应环境变化？",
        "teaching_hint": "从气候变化和适应能力引导孩子理解灭绝。",
    }
    client = _make_client(monkeypatch, tmp_path, backend)

    upload_response = client.post(
        "/v1/resource/upload",
        data={"topic_id": "demo_01", "resource_name": "引导问题测试", "category": "learn"},
        files={"file": ("sample.txt", "恐龙没能适应环境变化。".encode("utf-8"), "text/plain")},
    )
    assert upload_response.status_code == 200
    resource_id = upload_response.json()["resource"]["resource_id"]

    response = client.get("/v1/resource/topics/demo_01/teaching-cues")

    assert response.status_code == 200
    payload = response.json()
    assert payload["topic_id"] == "demo_01"
    assert len(payload["cues"]) == 1
    cue = payload["cues"][0]
    assert cue["resource_id"] == resource_id
    assert cue["resource_name"] == "引导问题测试"
    assert cue["guiding_question"] == "你觉得恐龙为什么没能适应环境变化？"
    assert cue["teaching_hint"] == "从气候变化和适应能力引导孩子理解灭绝。"
    assert "恐龙没能适应环境变化" in cue["text"]


def test_document_ingestion_links_existing_topic(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "link",
        "topic_id": "demo_01",
        "confidence": 0.9,
        "reason": "片段讨论恐龙灭绝",
        "proposed_topic": None,
    }

    source_path = tmp_path / "sample.txt"
    source_path.write_text("恐龙为什么会灭绝？", encoding="utf-8")
    record = backend.create_resource_record(
        topic_id="demo_01",
        resource_name="链接测试",
        category="learn",
        media_type="txt",
        mime_type="text/plain",
        original_filename="sample.txt",
        stored_path=str(source_path),
        size_bytes=source_path.stat().st_size,
    )

    topics = backend.load_app_state(include_history=False).curriculum.topics
    segments = ingest_document_resource(backend=backend, record=record, topics=topics, default_topic_id="demo_01")

    assert len(segments) == 1
    assert segments[0].status == "classified"
    assert segments[0].decision == "link"
    assert segments[0].topic_id == "demo_01"
    assert segments[0].proposal_id is None


def test_document_ingestion_cleans_invalid_parent_ids_with_default_parent(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.82,
        "reason": "片段讲小行星撞击后的气候链式变化，现有节点不够细",
        "proposed_topic": {
            "title": "小行星撞击导致的气候变化",
            "summary": "理解小行星撞击如何引发遮光、降温和生态变化",
            "parent_node_ids": ["missing_topic"],
            "edge_type": "requires",
        },
    }

    source_path = tmp_path / "sample.txt"
    source_path.write_text("小行星撞击会改变气候。", encoding="utf-8")
    record = backend.create_resource_record(
        topic_id="demo_01",
        resource_name="父节点清理测试",
        category="learn",
        media_type="txt",
        mime_type="text/plain",
        original_filename="sample.txt",
        stored_path=str(source_path),
        size_bytes=source_path.stat().st_size,
    )

    topics = backend.load_app_state(include_history=False).curriculum.topics
    segments = ingest_document_resource(backend=backend, record=record, topics=topics, default_topic_id="demo_01")

    assert len(segments) == 1
    assert segments[0].status == "proposed"
    assert segments[0].proposal_id is not None

    state = backend.load_app_state(include_history=False)
    proposal = next(rec for rec in state.learning.graph_proposals if rec.proposal_id == segments[0].proposal_id)
    assert proposal.parent_node_ids == ["demo_01"]


def test_approve_resource_proposal_creates_topic_and_relinks_segments(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.82,
        "reason": "现有节点不够细",
        "proposed_topic": {
            "title": "小行星撞击导致的气候变化",
            "summary": "理解小行星撞击如何引发遮光、降温和生态变化",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
        "guiding_question": "如果天空长期变暗，会发生什么？",
        "teaching_hint": "引导孩子把遮光、降温和食物链连接起来。",
    }
    client = _make_client(monkeypatch, tmp_path, backend)

    response = client.post(
        "/v1/resource/upload",
        data={"topic_id": "demo_01", "resource_name": "气候链式变化", "category": "learn"},
        files={"file": ("sample.txt", "小行星撞击会让天空变暗，气候变冷。".encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 200
    segment = response.json()["resource"]["segments"][0]
    proposal_id = segment["proposal_id"]
    assert proposal_id

    approve = client.post(
        f"/v1/knowledge/proposals/{proposal_id}/approve",
        json={"tags": ["恐龙", "气候"], "reason": "家长确认新增节点"},
    )
    assert approve.status_code == 200
    approve_payload = approve.json()
    topic_id = approve_payload["topic"]["topic_id"]
    assert approve_payload["proposal"]["status"] == "active"
    assert approve_payload["proposal"]["created_topic_id"] == topic_id
    assert approve_payload["relinked_segment_count"] == 1

    graph = client.get("/v1/knowledge/graph").json()
    assert any(topic["topic_id"] == topic_id for topic in graph["topics"])

    segments_response = client.get(f"/v1/resource/{response.json()['resource']['resource_id']}/segments")
    updated_segment = segments_response.json()["segments"][0]
    assert updated_segment["status"] == "classified"
    assert updated_segment["decision"] == "link"
    assert updated_segment["topic_id"] == topic_id
    assert updated_segment["guiding_question"] == "如果天空长期变暗，会发生什么？"


def test_reject_resource_proposal_marks_segments_unclassified(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
        "decision": "propose",
        "topic_id": None,
        "confidence": 0.82,
        "reason": "现有节点不够细",
        "proposed_topic": {
            "title": "临时提案",
            "summary": "稍后拒绝",
            "parent_node_ids": ["demo_01"],
            "edge_type": "requires",
        },
        "guiding_question": "我们要不要新增这个知识点？",
        "teaching_hint": "等待家长判断。",
    }
    client = _make_client(monkeypatch, tmp_path, backend)

    response = client.post(
        "/v1/resource/upload",
        data={"topic_id": "demo_01", "resource_name": "待拒绝提案", "category": "learn"},
        files={"file": ("sample.txt", "这是一段待审核新知识。".encode("utf-8"), "text/plain")},
    )
    proposal_id = response.json()["resource"]["segments"][0]["proposal_id"]

    rejected = client.post(f"/v1/knowledge/proposals/{proposal_id}/reject", json={"reason": "不需要新增"})
    assert rejected.status_code == 200
    assert rejected.json()["proposal"]["status"] == "rejected"
    assert rejected.json()["relinked_segment_count"] == 1

    segments_response = client.get(f"/v1/resource/{response.json()['resource']['resource_id']}/segments")
    updated_segment = segments_response.json()["segments"][0]
    assert updated_segment["status"] == "unclassified"
    assert updated_segment["decision"] == "unclassified"
    assert updated_segment["topic_id"] is None
    assert updated_segment["proposal_id"] is None
