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


def test_upload_txt_ingests_segments_and_exposes_segments_api(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    def fake_classify_or_propose(*, chunk_text: str, topics: list[TopicNode], default_parent_topic_id: str | None = None) -> dict[str, object]:
        if "恐龙" in chunk_text:
            return {
                "decision": "link",
                "topic_id": "demo_01",
                "confidence": 0.9,
                "reason": "片段讨论恐龙灭绝",
                "proposed_topic": None,
            }
        return {
            "decision": "propose",
            "topic_id": None,
            "confidence": 0.82,
            "reason": "现有节点不够细",
            "proposed_topic": {
                "title": "一位数加法练习",
                "summary": "围绕 3 加 2 之类的基础练习",
                "parent_node_ids": ["math_01"],
                "edge_type": "requires",
            },
        }

    backend.llm_skill.classify_or_propose_resource_chunk = fake_classify_or_propose
    client = _make_client(monkeypatch, tmp_path, backend)

    content = (
        "第一段： 恐龙生活在很久以前。科学家认为，小行星撞击地球可能导致气候变化，许多恐龙无法适应环境。\n\n"
        "第二段： 3 加 2 等于 5。我们可以先数 3 个苹果，再数 2 个苹果。"
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
    assert segments[0]["status"] == "classified"
    assert segments[0]["topic_id"] == "demo_01"
    assert segments[0]["locator"] == {"kind": "txt", "line_start": 1, "line_end": 1}
    assert segments[1]["status"] == "proposed"
    assert segments[1]["proposal_id"]
    assert segments[1]["proposed_topic_title"] == "一位数加法练习"

    resource_id = resource["resource_id"]
    segments_response = client.get(f"/v1/resource/{resource_id}/segments")
    assert segments_response.status_code == 200
    assert segments_response.json()["segments"] == segments

    events = client.get("/v1/session/events", params={"after": 0, "limit": 20})
    assert events.status_code == 200
    event_items = events.json()["events"]
    ingested_event = next(event for event in event_items if event["kind"] == "resource_ingested")
    assert ingested_event["payload"]["resource_id"] == resource_id
    assert ingested_event["payload"]["segment_count"] == 2


def test_get_topic_resources_includes_segment_linked_resources(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    def fake_classify_or_propose(*, chunk_text: str, topics: list[TopicNode], default_parent_topic_id: str | None = None) -> dict[str, object]:
        if "加" in chunk_text or "苹果" in chunk_text:
            return {
                "decision": "link",
                "topic_id": "math_01",
                "confidence": 0.88,
                "reason": "片段讲一位数加法",
                "proposed_topic": None,
            }
        return {
            "decision": "link",
            "topic_id": "demo_01",
            "confidence": 0.9,
            "reason": "片段讨论恐龙",
            "proposed_topic": None,
        }

    backend.llm_skill.classify_or_propose_resource_chunk = fake_classify_or_propose
    client = _make_client(monkeypatch, tmp_path, backend)

    content = "恐龙灭绝。\n\n3 加 2 等于 5，我们来数苹果。"
    upload_response = client.post(
        "/v1/resource/upload",
        data={"topic_id": "demo_01", "resource_name": "跨主题文本", "category": "learn"},
        files={"file": ("sample.txt", content.encode("utf-8"), "text/plain")},
    )
    assert upload_response.status_code == 200
    resource_id = upload_response.json()["resource"]["resource_id"]

    topic_resources = client.get("/v1/resource/topics/math_01")
    assert topic_resources.status_code == 200
    resource = next(item for item in topic_resources.json()["resources"] if item["resource_id"] == resource_id)
    assert any(segment["topic_id"] == "math_01" for segment in resource["segments"])


def test_upload_doc_creates_unsupported_or_parse_failed_segment(monkeypatch, tmp_path: Path) -> None:
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


def test_document_ingestion_downgrades_low_confidence_to_unclassified(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_or_propose_resource_chunk = lambda **_: {
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

    source_path = tmp_path / "sample.txt"
    source_path.write_text("这是一段内容。", encoding="utf-8")
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

    assert len(segments) == 1
    assert segments[0].status == "unclassified"
    assert segments[0].proposal_id is None
    assert backend.load_app_state(include_history=False).learning.graph_proposals == []
