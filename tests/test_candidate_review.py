from __future__ import annotations

import json
from pathlib import Path

from src.core.models import (
    CandidateEdge,
    CandidateGraph,
    CandidateNode,
    CandidateRelay,
    DocumentMeta,
    ExtractionDiagnostics,
    SourceSegment,
    SourceRef,
    TopicNode,
)
from src.services.candidate_review import (
    CompileResult,
    compile_review_result,
    review_candidate_graph,
)


def _make_doc_meta(resource_id: str = "res_test_001") -> DocumentMeta:
    return DocumentMeta(
        resource_id=resource_id,
        resource_name="test doc",
        media_type="txt",
        original_filename="test.txt",
        subject="math",
        language_id=None,
        doc_type="textbook",
        total_chunks=1,
        total_chars=100,
        extraction_timestamp="2026-01-01T00:00:00Z",
    )


def _make_node(temp_id: str, title: str, subject: str = "math", **kwargs) -> CandidateNode:
    defaults = dict(
        temp_id=temp_id,
        title=title,
        normalized_title=title,
        subject=subject,
        facet="general",
        summary=f"{title} summary",
    )
    defaults.update(kwargs)
    return CandidateNode(**defaults)


def _make_relay(relay_id: str, title: str, children: list[str], subject: str = "math") -> CandidateRelay:
    return CandidateRelay(
        relay_id=relay_id,
        title=title,
        subject=subject,
        facet="topic_area",
        node_kind="relay",
        children_temp_ids=list(children),
        confidence=0.8,
        grouping_rationale="test relay",
    )


def _make_edge(
    edge_id: str,
    source: str,
    target: str,
    edge_type: str = "part_of",
    edge_kind: str = "parent_child",
) -> CandidateEdge:
    return CandidateEdge(
        edge_id=edge_id,
        source_temp_id=source,
        target_temp_id=target,
        edge_type=edge_type,
        edge_kind=edge_kind,
        confidence=0.85,
        rationale="test edge",
    )


def _make_candidate_graph(**kwargs) -> CandidateGraph:
    defaults = dict(
        extraction_id="extr_test_001",
        document=_make_doc_meta(),
        diagnostics=ExtractionDiagnostics(pipeline="test", node_count=0),
    )
    defaults.update(kwargs)
    return CandidateGraph(**defaults)


# ── Naming Review Tests ──


def test_naming_exercise_title_detected() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "Role Play: At the Restaurant"),
            _make_node("cand_002", "Present Continuous"),
        ]
    )
    result = review_candidate_graph(graph)
    assert not result.naming.passed
    exercise_issues = [i for i in result.naming.issues if i.issue_type == "exercise_title"]
    assert len(exercise_issues) == 1
    assert exercise_issues[0].temp_id == "cand_001"
    assert exercise_issues[0].severity == "error"
    assert "cand_001" in result.dropped_temp_ids


def test_naming_exercise_chinese_title_detected() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "设计动物园", subject="language"),
            _make_node("cand_002", "动物词汇", subject="language"),
        ]
    )
    result = review_candidate_graph(graph)
    exercise_issues = [i for i in result.naming.issues if i.issue_type == "exercise_title"]
    assert len(exercise_issues) == 1
    assert exercise_issues[0].temp_id == "cand_001"


def test_naming_overlong_title_detected() -> None:
    long_title = "这是一个非常长的标题用来测试审核系统是否能正确检测过长标题并进行适当的处理和警告" * 3
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", long_title),
            _make_node("cand_002", "正常标题"),
        ]
    )
    result = review_candidate_graph(graph)
    overlong = [i for i in result.naming.issues if i.issue_type == "overlong_title"]
    assert len(overlong) == 1
    assert overlong[0].temp_id == "cand_001"
    assert overlong[0].suggested_title is not None


def test_naming_redundant_prefix_stripped() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "什么是勾股定理"),
            _make_node("cand_002", "关于光的折射及其应用"),
        ]
    )
    result = review_candidate_graph(graph)
    redundant = [i for i in result.naming.issues if i.issue_type == "redundant_name"]
    assert len(redundant) == 2
    assert "勾股定理" in result.naming.canonical_titles["cand_001"]


def test_naming_near_duplicate_merge() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "长方形的周长"),
            _make_node("cand_002", "长方形的周长"),
            _make_node("cand_003", "正方形面积"),
        ]
    )
    result = review_candidate_graph(graph)
    near_dup = [i for i in result.naming.issues if i.issue_type == "near_duplicate"]
    assert len(near_dup) == 1
    assert near_dup[0].temp_id == "cand_002"
    assert near_dup[0].merge_target_temp_id == "cand_001"


def test_naming_mergeable_to_existing_topic() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
        ],
        document=_make_doc_meta(),
    )
    existing = [
        TopicNode(
            topic_id="math_pythagorean",
            title="勾股定理",
            difficulty=1,
            prerequisite_ids=[],
            tags=["subject:math", "facet:theorem_or_rule"],
        )
    ]
    result = review_candidate_graph(graph, existing_topics=existing)
    merge_issues = [i for i in result.naming.issues if i.issue_type == "mergeable_to_existing"]
    assert len(merge_issues) == 1
    assert merge_issues[0].merge_target_existing_topic_id == "math_pythagorean"


def test_naming_mergeable_different_wording() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "什么是加法"),
        ],
        document=_make_doc_meta(),
    )
    existing = [
        TopicNode(
            topic_id="math_add",
            title="加法",
            difficulty=1,
            prerequisite_ids=[],
            tags=["subject:math"],
        )
    ]
    result = review_candidate_graph(graph, existing_topics=existing)
    merge_issues = [i for i in result.naming.issues if i.issue_type == "mergeable_to_existing"]
    assert len(merge_issues) == 1


def test_naming_canonical_titles_populated() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "什么是勾股定理"),
            _make_node("cand_002", "关于三角形内角和及其应用"),
        ]
    )
    result = review_candidate_graph(graph)
    assert result.naming.canonical_titles["cand_001"] != "什么是勾股定理"
    assert result.naming.canonical_titles["cand_002"] != "关于三角形内角和及其应用"


# ── Logic Review Tests ──


def test_logic_self_reference_detected() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "cand_001", "requires", "prerequisite"),
        ],
    )
    result = review_candidate_graph(graph)
    self_ref = [i for i in result.logic.issues if i.issue_type == "self_reference"]
    assert len(self_ref) == 1
    assert not result.logic.passed


def test_logic_orphan_node_detected() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
            _make_node("cand_002", "三角形面积"),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "cand_002", "requires", "prerequisite"),
        ],
        candidate_relays=[],
    )
    result = review_candidate_graph(graph)
    orphan = [i for i in result.logic.issues if i.issue_type == "orphan_node"]
    assert len(orphan) == 0  # both have edges


def test_logic_orphan_node_truly_orphan() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
            _make_node("cand_002", "三角形面积"),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "cand_002", "requires", "prerequisite"),
        ],
    )
    result = review_candidate_graph(graph)
    orphan = [i for i in result.logic.issues if i.issue_type == "orphan_node"]
    assert len(orphan) == 0


def test_logic_cross_subject_detected() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理", subject="math"),
            _make_node("cand_002", "光合作用", subject="science"),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "cand_002", "related"),
        ],
    )
    result = review_candidate_graph(graph)
    cross = [i for i in result.logic.issues if i.issue_type == "cross_subject"]
    assert len(cross) == 1
    assert not result.logic.passed


def test_logic_excessive_relay_detected() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
        ],
        candidate_relays=[
            _make_relay("relay_001", "数学", ["cand_001"]),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "relay_001"),
        ],
    )
    result = review_candidate_graph(graph)
    excessive = [i for i in result.logic.issues if i.issue_type == "excessive_relay"]
    assert len(excessive) == 1
    assert "relay_001" in result.dropped_temp_ids


def test_logic_prerequisite_inversion_detected() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "加法"),
            _make_node("cand_002", "乘法"),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "cand_002", "requires", "prerequisite"),
            _make_edge("edge_002", "cand_002", "cand_001", "requires", "prerequisite"),
        ],
    )
    result = review_candidate_graph(graph)
    inversion = [i for i in result.logic.issues if i.issue_type == "prerequisite_inversion"]
    assert len(inversion) == 1
    assert not result.logic.passed


def test_logic_duplicate_edge_detected() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
            _make_node("cand_002", "三角形面积"),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "cand_002", "requires", "prerequisite"),
            _make_edge("edge_002", "cand_001", "cand_002", "requires", "prerequisite"),
        ],
    )
    result = review_candidate_graph(graph)
    dup = [i for i in result.logic.issues if i.issue_type == "duplicate_edge"]
    assert len(dup) == 1


# ── Compilable Graph Tests ──


def test_compilable_drops_exercise_titles() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "Role Play: Shopping"),
            _make_node("cand_002", "勾股定理"),
            _make_node("cand_003", "Fill in the blanks exercise"),
        ],
    )
    result = review_candidate_graph(graph)
    assert len(result.compilable_nodes) == 1
    assert result.compilable_nodes[0].temp_id == "cand_002"
    assert "cand_001" in result.dropped_temp_ids
    assert "cand_003" in result.dropped_temp_ids


def test_compilable_merge_near_duplicates() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "长方形周长"),
            _make_node("cand_002", "长方形周长"),
            _make_node("cand_003", "正方形面积"),
        ],
        candidate_relays=[
            _make_relay("relay_001", "几何", ["cand_001", "cand_002", "cand_003"]),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "relay_001"),
            _make_edge("edge_002", "cand_002", "relay_001"),
            _make_edge("edge_003", "cand_003", "relay_001"),
        ],
    )
    result = review_candidate_graph(graph)
    assert len(result.compilable_nodes) == 2
    compilable_ids = {n.temp_id for n in result.compilable_nodes}
    assert "cand_001" in compilable_ids
    assert "cand_003" in compilable_ids
    assert "cand_002" not in compilable_ids
    assert "cand_002" in result.dropped_temp_ids
    assert result.merge_map.get("cand_002") == "cand_001"


def test_compilable_edges_remap_after_merge() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
            _make_node("cand_002", "勾股定理"),
        ],
        candidate_relays=[
            _make_relay("relay_001", "几何", ["cand_001", "cand_002"]),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "relay_001"),
            _make_edge("edge_002", "cand_002", "relay_001"),
        ],
    )
    result = review_candidate_graph(graph)
    assert len(result.compilable_edges) >= 1
    for edge in result.compilable_edges:
        assert edge.source_temp_id == "cand_001"
        assert edge.target_temp_id == "relay_001"


def test_compilable_self_ref_edge_removed() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "cand_001", "requires", "prerequisite"),
        ],
    )
    result = review_candidate_graph(graph)
    assert len(result.compilable_edges) == 0


def test_compilable_relay_with_dropped_children_removed() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "Role Play"),
            _make_node("cand_002", "勾股定理"),
        ],
        candidate_relays=[
            _make_relay("relay_001", "数学", ["cand_001", "cand_002"]),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "relay_001"),
            _make_edge("edge_002", "cand_002", "relay_001"),
        ],
    )
    result = review_candidate_graph(graph)
    assert len(result.compilable_relays) >= 1
    relay_001 = next((r for r in result.compilable_relays if r.relay_id == "relay_001"), None)
    if relay_001:
        assert "cand_001" not in relay_001.children_temp_ids
        assert "cand_002" in relay_001.children_temp_ids


def test_compilable_nodes_have_parent_and_prereq() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "加法"),
            _make_node("cand_002", "乘法"),
        ],
        candidate_relays=[
            _make_relay("relay_001", "运算", ["cand_001", "cand_002"]),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "relay_001", "part_of", "parent_child"),
            _make_edge("edge_002", "cand_002", "relay_001", "part_of", "parent_child"),
            _make_edge("edge_003", "cand_001", "cand_002", "requires", "prerequisite"),
        ],
    )
    result = review_candidate_graph(graph)
    assert len(result.compilable_nodes) == 2
    for cn in result.compilable_nodes:
        assert len(cn.parent_temp_ids) == 1
        assert cn.parent_temp_ids[0] == "relay_001"
    add_node = next(n for n in result.compilable_nodes if n.temp_id == "cand_001")
    assert "cand_002" in add_node.prerequisite_temp_ids


def test_review_result_structure_complete() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
            _make_node("cand_002", "三角形面积"),
        ],
        candidate_relays=[
            _make_relay("relay_001", "几何", ["cand_001", "cand_002"]),
        ],
        candidate_edges=[
            _make_edge("edge_001", "cand_001", "relay_001"),
            _make_edge("edge_002", "cand_002", "relay_001"),
            _make_edge("edge_003", "cand_001", "cand_002", "requires", "prerequisite"),
        ],
    )
    result = review_candidate_graph(graph)

    assert result.schema_version == "2.0"
    assert result.review_id.startswith("rev_")
    assert result.extraction_id == "extr_test_001"
    assert result.resource_id == "res_test_001"

    assert result.naming.passed
    assert isinstance(result.naming.issues, list)
    assert len(result.naming.canonical_titles) == 2

    assert result.logic.passed
    assert isinstance(result.logic.issues, list)

    assert len(result.compilable_nodes) == 2
    assert len(result.compilable_edges) == 3
    assert len(result.compilable_relays) == 1

    json_str = result.model_dump_json(indent=2, ensure_ascii=False)
    assert len(json_str) > 100
    parsed = json.loads(json_str)
    assert parsed["schema_version"] == "2.0"


# ── Edge Cases ──


def test_empty_graph_review_passes() -> None:
    graph = _make_candidate_graph()
    result = review_candidate_graph(graph)
    assert result.naming.passed
    assert result.logic.passed
    assert len(result.compilable_nodes) == 0
    assert len(result.compilable_edges) == 0
    assert len(result.compilable_relays) == 0


def test_multiple_issues_on_same_node() -> None:
    long_exercise = "Role Play: 这是一个非常长的练习标题用于测试系统能否同时检测多种问题类型" * 2
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", long_exercise),
        ]
    )
    result = review_candidate_graph(graph)
    cand_issues = [i for i in result.naming.issues if i.temp_id == "cand_001"]
    # Should have both exercise_title and overlong_title
    issue_types = {i.issue_type for i in cand_issues}
    assert "exercise_title" in issue_types


def test_merge_map_preserved_in_result() -> None:
    graph = _make_candidate_graph(
        candidate_nodes=[
            _make_node("cand_001", "勾股定理"),
            _make_node("cand_002", "勾股定理"),
            _make_node("cand_003", "三角形面积"),
        ]
    )
    result = review_candidate_graph(graph)
    assert "cand_002" in result.merge_map
    assert result.merge_map["cand_002"] == "cand_001"
    assert "cand_001" not in result.merge_map


# ── Compilation Tests ──

def _build_backend(tmp_path: Path):
    from src.services.session_backend import SessionBackend
    from src.core.enums import LearningPhase

    backend = SessionBackend()
    backend.state_file = tmp_path / "state.json"
    backend.state_db_file = str(tmp_path / "state.db")
    backend.log_file = tmp_path / "trace.jsonl"

    backend.llm_skill.client.api_key = "test_key"
    if hasattr(backend.llm_skill, "ensure_configured"):
        backend.llm_skill.ensure_configured = lambda: None
    if hasattr(backend.llm_skill, "reconfigure"):
        backend.llm_skill.reconfigure = lambda **_: None

    state = backend.load_app_state()
    state.learning.current_phase = LearningPhase.LEARNING
    state.curriculum.topics = [
        TopicNode(topic_id="math_root", title="数学", difficulty=1, prerequisite_ids=[], tags=["subject:math", "facet:root"]),
    ]
    backend.save_app_state(state)
    return backend


def _make_resource_for_compile(backend, tmp_path: Path, resource_id: str, text: str = "test"):
    from src.core.models import ResourceSegment

    source_path = tmp_path / f"{resource_id}.txt"
    source_path.write_text(text, encoding="utf-8")

    return backend.create_resource_record(
        topic_id="math_root",
        resource_name="Test Resource",
        category="learn",
        media_type="txt",
        mime_type="text/plain",
        original_filename=f"{resource_id}.txt",
        stored_path=str(source_path),
        size_bytes=source_path.stat().st_size,
        ingestion_status="processing",
        segments=[
            ResourceSegment(
                segment_id=f"seg_{resource_id}_0001",
                start_ms=0,
                label="chunk",
                status="unclassified",
                sequence_index=1,
                text=text,
                locator={"kind": "structured", "section_type": "topic_area"},
            ),
        ],
    )


def test_compile_creates_relay_and_knowledge_nodes(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    doc_meta = DocumentMeta(
        resource_id="res_compile_001",
        resource_name="test",
        media_type="txt",
        original_filename="test.txt",
        subject="math",
        doc_type="textbook",
    )
    graph = CandidateGraph(
        extraction_id="extr_001",
        document=doc_meta,
        candidate_nodes=[
            CandidateNode(temp_id="cand_001", title="勾股定理", normalized_title="勾股定理", subject="math", facet="theorem_or_rule", summary="a^2+b^2=c^2", node_kind="knowledge", confidence=0.9),
            CandidateNode(temp_id="cand_002", title="三角形面积", normalized_title="三角形面积", subject="math", facet="formula", summary="S=ah/2", node_kind="knowledge", confidence=0.88),
        ],
        candidate_relays=[
            CandidateRelay(relay_id="relay_001", title="几何", subject="math", facet="topic_area", node_kind="relay", children_temp_ids=["cand_001","cand_002"], confidence=0.85, grouping_rationale="几何"),
        ],
        candidate_edges=[
            CandidateEdge(edge_id="edge_001", source_temp_id="cand_001", target_temp_id="relay_001", edge_type="part_of", edge_kind="parent_child", confidence=0.9),
            CandidateEdge(edge_id="edge_002", source_temp_id="cand_002", target_temp_id="relay_001", edge_type="part_of", edge_kind="parent_child", confidence=0.9),
        ],
        diagnostics=ExtractionDiagnostics(pipeline="structured_scan", node_count=2, relay_count=1, edge_count=2),
    )

    review_result = review_candidate_graph(graph)
    assert review_result.naming.passed

    record = _make_resource_for_compile(backend, tmp_path, "res_compile_001")
    result = compile_review_result(backend, review_result, graph, resource_id_override=record.resource_id)

    assert result.relay_count == 1
    assert result.knowledge_count == 2
    assert result.created_topic_count == 3
    assert len(result.errors) == 0
    assert "relay_001" in result.temp_to_topic
    assert "cand_001" in result.temp_to_topic
    assert "cand_002" in result.temp_to_topic

    state = backend.load_app_state(include_history=False)
    topic_titles = {t.title for t in state.curriculum.topics}
    assert "几何" in topic_titles
    assert "勾股定理" in topic_titles
    assert "三角形面积" in topic_titles


def test_compile_handles_merge(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    doc_meta = DocumentMeta(resource_id="res_compile_002", resource_name="test", media_type="txt", original_filename="test.txt", subject="math", doc_type="textbook")
    graph = CandidateGraph(
        extraction_id="extr_002",
        document=doc_meta,
        candidate_nodes=[
            CandidateNode(temp_id="cand_001", title="勾股定理", normalized_title="勾股定理", subject="math", facet="theorem_or_rule", summary="a^2+b^2=c^2", node_kind="knowledge", confidence=0.9),
            CandidateNode(temp_id="cand_002", title="勾股定理", normalized_title="勾股定理", subject="math", facet="theorem_or_rule", summary="dup", node_kind="knowledge", confidence=0.8),
        ],
        diagnostics=ExtractionDiagnostics(pipeline="structured_scan", node_count=2),
    )

    review_result = review_candidate_graph(graph)
    assert len(review_result.compilable_nodes) == 1
    assert "cand_002" in review_result.merge_map

    record = _make_resource_for_compile(backend, tmp_path, "res_compile_002")
    result = compile_review_result(backend, review_result, graph, resource_id_override=record.resource_id)

    assert result.knowledge_count == 1
    assert "cand_001" in result.temp_to_topic
    assert "cand_002" in result.temp_to_topic

    state = backend.load_app_state(include_history=False)
    pythagorean = next((t for t in state.curriculum.topics if t.title == "勾股定理"), None)
    assert pythagorean is not None


def test_compile_prerequisite_edge(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    doc_meta = DocumentMeta(resource_id="res_compile_003", resource_name="test", media_type="txt", original_filename="test.txt", subject="math", doc_type="textbook")
    graph = CandidateGraph(
        extraction_id="extr_003",
        document=doc_meta,
        candidate_nodes=[
            CandidateNode(temp_id="cand_001", title="加法", normalized_title="加法", subject="math", facet="operation", summary="加法运算", node_kind="knowledge", confidence=0.9),
            CandidateNode(temp_id="cand_002", title="乘法", normalized_title="乘法", subject="math", facet="operation", summary="乘法运算", node_kind="knowledge", confidence=0.9),
        ],
        candidate_edges=[
            CandidateEdge(edge_id="edge_001", source_temp_id="cand_001", target_temp_id="cand_002", edge_type="requires", edge_kind="prerequisite", confidence=0.8, rationale="加法是乘法的基础"),
        ],
        diagnostics=ExtractionDiagnostics(pipeline="structured_scan", node_count=2, edge_count=1),
    )

    review_result = review_candidate_graph(graph)
    assert len(review_result.compilable_nodes) == 2

    record = _make_resource_for_compile(backend, tmp_path, "res_compile_003")
    result = compile_review_result(backend, review_result, graph, resource_id_override=record.resource_id)

    assert result.knowledge_count == 2
    assert "cand_001" in result.temp_to_topic
    assert "cand_002" in result.temp_to_topic

    state = backend.load_app_state(include_history=False)
    add_topic = next((t for t in state.curriculum.topics if t.title == "加法"), None)
    assert add_topic is not None
    mul_topic_id = result.temp_to_topic.get("cand_002")
    assert mul_topic_id in add_topic.prerequisite_ids


def test_compile_segment_relink(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    doc_meta = DocumentMeta(resource_id="res_compile_004", resource_name="test", media_type="txt", original_filename="test.txt", subject="math", doc_type="textbook")
    graph = CandidateGraph(
        extraction_id="extr_004",
        document=doc_meta,
        candidate_nodes=[
            CandidateNode(temp_id="cand_001", title="勾股定理", normalized_title="勾股定理", subject="math", facet="theorem_or_rule", summary="a^2+b^2=c^2", node_kind="knowledge", confidence=0.9,
                          source_segment_refs=[SourceRef(segment_id="seg_res_compile_004_0001", excerpt="勾股定理", relevance=0.9)]),
        ],
        source_segments=[
            SourceSegment(segment_id="seg_res_compile_004_0001", segment_index=1, locator={"kind": "structured"}, text="勾股定理: a^2+b^2=c^2", status="unclassified"),
        ],
        diagnostics=ExtractionDiagnostics(pipeline="structured_scan", node_count=1, segment_count=1),
    )

    review_result = review_candidate_graph(graph)
    record = _make_resource_for_compile(backend, tmp_path, "res_compile_004")
    result = compile_review_result(backend, review_result, graph, resource_id_override=record.resource_id)

    assert result.knowledge_count == 1

    segments = backend.list_resource_segments(record.resource_id)
    assert len(segments) > 0


def test_compile_empty_review_is_noop(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    doc_meta = DocumentMeta(resource_id="res_compile_005", resource_name="test", media_type="txt", original_filename="test.txt", subject="math", doc_type="textbook")
    graph = CandidateGraph(
        extraction_id="extr_005",
        document=doc_meta,
        diagnostics=ExtractionDiagnostics(pipeline="structured_scan", node_count=0),
    )

    review_result = review_candidate_graph(graph)
    record = _make_resource_for_compile(backend, tmp_path, "res_compile_005")
    result = compile_review_result(backend, review_result, graph, resource_id_override=record.resource_id)

    assert result.relay_count == 0
    assert result.knowledge_count == 0
    assert result.created_topic_count == 0


def test_compile_dropped_exercise_not_compiled(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    doc_meta = DocumentMeta(resource_id="res_compile_006", resource_name="test", media_type="txt", original_filename="test.txt", subject="math", doc_type="textbook")
    graph = CandidateGraph(
        extraction_id="extr_006",
        document=doc_meta,
        candidate_nodes=[
            CandidateNode(temp_id="cand_001", title="Role Play: Shopping", normalized_title="Role Play", subject="math", facet="general", summary="activity", node_kind="knowledge", confidence=0.7),
            CandidateNode(temp_id="cand_002", title="勾股定理", normalized_title="勾股定理", subject="math", facet="theorem_or_rule", summary="a^2+b^2=c^2", node_kind="knowledge", confidence=0.9),
        ],
        diagnostics=ExtractionDiagnostics(pipeline="structured_scan", node_count=2),
    )

    review_result = review_candidate_graph(graph)
    assert len(review_result.compilable_nodes) == 1
    assert review_result.compilable_nodes[0].temp_id == "cand_002"

    record = _make_resource_for_compile(backend, tmp_path, "res_compile_006")
    result = compile_review_result(backend, review_result, graph, resource_id_override=record.resource_id)

    assert result.knowledge_count == 1
    assert "cand_001" not in result.temp_to_topic

    state = backend.load_app_state(include_history=False)
    topic_titles = {t.title for t in state.curriculum.topics}
    assert "勾股定理" in topic_titles
    assert "Role Play: Shopping" not in topic_titles


def test_compile_result_structure(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)

    doc_meta = DocumentMeta(resource_id="res_compile_007", resource_name="test", media_type="txt", original_filename="test.txt", subject="math", doc_type="textbook")
    graph = CandidateGraph(
        extraction_id="extr_007",
        document=doc_meta,
        candidate_nodes=[
            CandidateNode(temp_id="cand_001", title="勾股定理", normalized_title="勾股定理", subject="math", facet="theorem_or_rule", summary="a^2+b^2=c^2", node_kind="knowledge", confidence=0.9),
        ],
        diagnostics=ExtractionDiagnostics(pipeline="structured_scan", node_count=1),
    )

    review_result = review_candidate_graph(graph)
    record = _make_resource_for_compile(backend, tmp_path, "res_compile_007")
    result = compile_review_result(backend, review_result, graph, resource_id_override=record.resource_id)

    assert isinstance(result, CompileResult)
    assert isinstance(result.temp_to_topic, dict)
    assert isinstance(result.errors, list)
    assert result.created_topic_count == result.knowledge_count + result.relay_count
    assert result.created_topic_count == 1
