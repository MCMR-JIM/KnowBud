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

    def fake_classify(*, chunk_text: str, topics: list[TopicNode]) -> dict[str, object]:
        if "恐龙" in chunk_text:
            return {"topic_id": "demo_01", "confidence": 0.9, "reason": "片段讨论恐龙灭绝原因"}
        if "苹果" in chunk_text or "加" in chunk_text:
            return {"topic_id": "math_01", "confidence": 0.85, "reason": "片段讲一位数加法"}
        return {"topic_id": None, "confidence": 0.3, "reason": "内容过泛"}

    backend.llm_skill.classify_resource_chunk = fake_classify
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
    assert first["locator"] == {"kind": "txt", "line_start": 1, "line_end": 1}
    assert "恐龙生活在很久以前" in first["text"]

    second = segments[1]
    assert second["sequence_index"] == 1
    assert second["status"] == "classified"
    assert second["topic_id"] == "math_01"
    assert second["confidence"] == 0.85
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
        "classified_count": 2,
        "unclassified_count": 0,
        "media_type": "txt",
    }


def test_document_ingestion_marks_null_and_low_confidence_as_unclassified(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    def fake_classify(*, chunk_text: str, topics: list[TopicNode]) -> dict[str, object]:
        if "泛泛" in chunk_text:
            return {"topic_id": None, "confidence": 0.3, "reason": "内容过泛"}
        if "加" in chunk_text:
            return {"topic_id": "math_01", "confidence": 0.4, "reason": "置信度不足"}
        return {"topic_id": None, "confidence": 0.2, "reason": "无法判断"}

    backend.llm_skill.classify_resource_chunk = fake_classify

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
    assert segments[1].confidence == 0.4

    stored_segments = backend.list_resource_segments(record.resource_id)
    assert [segment.status for segment in stored_segments] == ["unclassified", "unclassified"]


def test_upload_doc_does_not_fail_and_creates_unsupported_segment(monkeypatch, tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    backend.llm_skill.classify_resource_chunk = lambda **_: {"topic_id": None, "confidence": 0.0, "reason": "不需要分类"}
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

    def fake_classify(*, chunk_text: str, topics: list[TopicNode]) -> dict[str, object]:
        if "恐龙" in chunk_text:
            return {"topic_id": "demo_01", "confidence": 0.9, "reason": "片段讨论恐龙灭绝原因"}
        if "加" in chunk_text or "苹果" in chunk_text:
            return {"topic_id": "math_01", "confidence": 0.85, "reason": "片段讲一位数加法"}
        return {"topic_id": None, "confidence": 0.3, "reason": "内容过泛"}

    backend.llm_skill.classify_resource_chunk = fake_classify
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
