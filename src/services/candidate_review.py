from __future__ import annotations

import logging
import re
import time
import uuid
from typing import TYPE_CHECKING

from src.core.models import (
    CandidateEdge,
    CandidateGraph,
    CandidateNode,
    CandidateRelay,
    CompilableNode,
    LogicIssue,
    LogicReview,
    NamingIssue,
    NamingReview,
    ReviewResult,
    TopicNode,
)

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend

logger = logging.getLogger(__name__)

EXERCISE_TITLE_MARKERS = (
    "role-play", "role play", "project", "draw a map", "work in groups",
    "group work", "pair work", "listen and repeat", "complete the passage",
    "fill in", "choose", "match", "act out", "design a zoo",
    "设计动物园", "制定班级规则", "练习", "活动",
)

EXERCISE_TITLE_PATTERNS = (
    r"^(如何|怎样|怎么).*(设计|制定|制作|画)",
    r"(设计|制定|制作|画).*(动物园|地图|海报|班级规则)",
)

VERBOSE_TITLE_PATTERNS = (
    r"^(什么是|关于|浅析|探究|理解|掌握|学习|用英语|请你|试着)",
    r"(是什么|及其应用|的应用|的证明|的推导|的意义|的概念|简介|概述)$",
)


def review_candidate_graph(
    candidate_graph: CandidateGraph,
    *,
    existing_topics: list[TopicNode] | None = None,
    backend: "SessionBackend" | None = None,
) -> ReviewResult:
    review_id = f"rev_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    resource_id = candidate_graph.document.resource_id
    extraction_id = candidate_graph.extraction_id

    nodes = candidate_graph.candidate_nodes
    relays = candidate_graph.candidate_relays
    edges = candidate_graph.candidate_edges

    node_by_id: dict[str, CandidateNode] = {n.temp_id: n for n in nodes}
    relay_by_id: dict[str, CandidateRelay] = {r.relay_id: r for r in relays}

    # ── Naming Review ──
    naming = _review_naming(nodes, existing_topics=existing_topics, backend=backend)

    # ── Logic Review ──
    logic = _review_logic(nodes, relays, edges, node_by_id, relay_by_id)

    # ── Build Compilable Graph ──
    compilable_nodes, compilable_edges, compilable_relays, merge_map, dropped = _build_compilable(
        nodes=nodes,
        relays=relays,
        edges=edges,
        naming=naming,
        logic=logic,
        node_by_id=node_by_id,
        relay_by_id=relay_by_id,
    )

    return ReviewResult(
        review_id=review_id,
        extraction_id=extraction_id,
        resource_id=resource_id,
        naming=naming,
        logic=logic,
        compilable_nodes=compilable_nodes,
        compilable_edges=compilable_edges,
        compilable_relays=compilable_relays,
        merge_map=merge_map,
        dropped_temp_ids=dropped,
    )


# ── Naming Review ──

def _review_naming(
    nodes: list[CandidateNode],
    *,
    existing_topics: list[TopicNode] | None = None,
    backend: object | None = None,
) -> NamingReview:
    issues: list[NamingIssue] = []
    canonical_titles: dict[str, str] = {}
    issue_counter = 0

    for node in nodes:
        title = node.title.strip()
        normalized = _normalize_title_for_review(title)

        canonical_titles[node.temp_id] = normalized

        # 1. Check for exercise / activity titles
        if _is_exercise_title(title):
            issue_counter += 1
            issues.append(
                NamingIssue(
                    issue_id=f"name_{issue_counter:03d}",
                    temp_id=node.temp_id,
                    issue_type="exercise_title",
                    severity="error",
                    title=title,
                    suggested_title=None,
                    description=f"「{title}」是练习/活动标题，不适合作知识节点",
                )
            )

        # 2. Check for overlong titles
        if len(title) > 80:
            shortened = title[:60]
            issue_counter += 1
            issues.append(
                NamingIssue(
                    issue_id=f"name_{issue_counter:03d}",
                    temp_id=node.temp_id,
                    issue_type="overlong_title",
                    severity="warn",
                    title=title,
                    suggested_title=shortened,
                    description=f"标题过长 ({len(title)} 字符)，建议缩短",
                )
            )

        # 3. Check for redundant prefixes/suffixes
        cleaned = _strip_verbose_patterns(title)
        if cleaned != title and cleaned:
            issue_counter += 1
            issues.append(
                NamingIssue(
                    issue_id=f"name_{issue_counter:03d}",
                    temp_id=node.temp_id,
                    issue_type="redundant_name",
                    severity="warn",
                    title=title,
                    suggested_title=cleaned,
                    description=f"标题含冗余前缀/后缀，建议简化为「{cleaned}」",
                )
            )

    # 4. Check for near-duplicates within the batch
    normalized_set: dict[str, str] = {}  # normalized_title -> first temp_id
    for node in nodes:
        nt = canonical_titles.get(node.temp_id, node.title)
        nt_key = nt.lower().strip()
        if nt_key in normalized_set:
            first_id = normalized_set[nt_key]
            if first_id != node.temp_id:
                issue_counter += 1
                issues.append(
                    NamingIssue(
                        issue_id=f"name_{issue_counter:03d}",
                        temp_id=node.temp_id,
                        issue_type="near_duplicate",
                        severity="warn",
                        title=node.title,
                        suggested_title=canonical_titles.get(first_id, nt),
                        description=f"「{node.title}」与 {first_id}「{node_by_title(nodes, first_id)}」标题重复",
                        merge_target_temp_id=first_id,
                    )
                )
        else:
            normalized_set[nt_key] = node.temp_id

    # 5. Check if any candidate title matches an existing graph topic
    if existing_topics:
        for node in nodes:
            for topic in existing_topics:
                if _titles_match(node.title, topic.title):
                    issue_counter += 1
                    issues.append(
                        NamingIssue(
                            issue_id=f"name_{issue_counter:03d}",
                            temp_id=node.temp_id,
                            issue_type="mergeable_to_existing",
                            severity="info",
                            title=node.title,
                            suggested_title=topic.title,
                            description=f"「{node.title}」可合并到已有节点「{topic.title}」({topic.topic_id})",
                            merge_target_existing_topic_id=topic.topic_id,
                        )
                    )
                    break

    passed = not any(i.severity == "error" for i in issues)
    return NamingReview(passed=passed, issues=issues, canonical_titles=canonical_titles)


def node_by_title(nodes: list[CandidateNode], temp_id: str) -> str:
    for n in nodes:
        if n.temp_id == temp_id:
            return n.title
    return temp_id


def _is_exercise_title(title: str) -> bool:
    lowered = title.lower()
    for marker in EXERCISE_TITLE_MARKERS:
        if marker in lowered:
            return True
    for pattern in EXERCISE_TITLE_PATTERNS:
        if re.search(pattern, lowered):
            return True
    return False


def _normalize_title_for_review(title: str) -> str:
    cleaned = _strip_verbose_patterns(title)
    cleaned = re.sub(r"[\u21d2\u21d4\u2192\u2190\u2194].+$", "", cleaned)
    cleaned = re.sub(r"\u63a8\u51fa.+$", "", cleaned)
    cleaned = cleaned.replace("？", "").replace("?", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:120] or cleaned


def _strip_verbose_patterns(title: str) -> str:
    cleaned = title
    for pattern in VERBOSE_TITLE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)
    return cleaned.strip() or title


def _titles_match(a: str, b: str) -> bool:
    na = _normalize_title_for_review(a).lower()
    nb = _normalize_title_for_review(b).lower()
    return na == nb and len(na) > 1


# ── Logic Review ──

def _review_logic(
    nodes: list[CandidateNode],
    relays: list[CandidateRelay],
    edges: list[CandidateEdge],
    node_by_id: dict[str, CandidateNode],
    relay_by_id: dict[str, CandidateRelay],
) -> LogicReview:
    issues: list[LogicIssue] = []
    issue_counter = 0
    all_ids = set(node_by_id.keys()) | set(relay_by_id.keys())

    # Build edge lookup
    outgoing: dict[str, list[CandidateEdge]] = {}
    incoming: dict[str, list[CandidateEdge]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source_temp_id, []).append(edge)
        incoming.setdefault(edge.target_temp_id, []).append(edge)

    for node in nodes:
        tid = node.temp_id

        # 1. Check for self-reference
        node_out = outgoing.get(tid, [])
        for edge in node_out:
            if edge.target_temp_id == tid:
                issue_counter += 1
                issues.append(
                    LogicIssue(
                        issue_id=f"logic_{issue_counter:03d}",
                        temp_id=tid,
                        issue_type="self_reference",
                        severity="error",
                        description=f"节点 {tid} 的边 {edge.edge_id} 引用自身",
                        affected_temp_ids=[tid],
                    )
                )

        # 2. Check for orphan nodes (no edges at all)
        if not node_out and not incoming.get(tid, []):
            issue_counter += 1
            issues.append(
                LogicIssue(
                    issue_id=f"logic_{issue_counter:03d}",
                    temp_id=tid,
                    issue_type="orphan_node",
                    severity="warn",
                    description=f"节点 {tid}「{node.title}」无任何边连接",
                    affected_temp_ids=[tid],
                )
            )

        # 3. Check for cross-subject mismatches via edges
        node_subject = _canonical_subject(node.subject)
        for edge in node_out:
            target = node_by_id.get(edge.target_temp_id) or relay_by_id.get(edge.target_temp_id)
            if target is None:
                continue
            target_subject = _canonical_subject(getattr(target, "subject", ""))
            if node_subject and target_subject and node_subject != target_subject:
                issue_counter += 1
                issues.append(
                    LogicIssue(
                        issue_id=f"logic_{issue_counter:03d}",
                        temp_id=tid,
                        issue_type="cross_subject",
                        severity="error",
                        description=f"节点 {tid}({node_subject}) 连接到 {edge.target_temp_id}({target_subject})，学科不匹配",
                        affected_temp_ids=[tid, edge.target_temp_id],
                    )
                )

    # 4. Check for excessive relays (0 or 1 child)
    for relay in relays:
        if len(relay.children_temp_ids) < 2:
            issue_counter += 1
            issues.append(
                LogicIssue(
                    issue_id=f"logic_{issue_counter:03d}",
                    temp_id=relay.relay_id,
                    issue_type="excessive_relay",
                    severity="warn",
                    description=f"中继节点 {relay.relay_id}「{relay.title}」仅有 {len(relay.children_temp_ids)} 个子节点，可移除",
                    affected_temp_ids=[relay.relay_id],
                )
            )

    # 5. Check for prerequisite inversion (bidirectional requires edges)
    prereq_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        if edge.edge_type == "requires" and edge.edge_kind == "prerequisite":
            pair = (edge.source_temp_id, edge.target_temp_id)
            reverse = (edge.target_temp_id, edge.source_temp_id)
            if reverse in prereq_pairs:
                issue_counter += 1
                issues.append(
                    LogicIssue(
                        issue_id=f"logic_{issue_counter:03d}",
                        temp_id=edge.source_temp_id,
                        issue_type="prerequisite_inversion",
                        severity="error",
                        description=f"节点 {edge.source_temp_id} 与 {edge.target_temp_id} 存在双向 requires 边",
                        affected_temp_ids=[edge.source_temp_id, edge.target_temp_id],
                    )
                )
            prereq_pairs.add(pair)

    # 6. Check for duplicate edges (same src -> dst pair with same type)
    edge_pairs: dict[tuple[str, str], str] = {}
    for edge in edges:
        key = (edge.source_temp_id, edge.target_temp_id)
        if key in edge_pairs:
            issue_counter += 1
            existing_id = edge_pairs[key]
            issues.append(
                LogicIssue(
                    issue_id=f"logic_{issue_counter:03d}",
                    temp_id=edge.source_temp_id,
                    issue_type="duplicate_edge",
                    severity="info",
                    description=f"边 {edge.edge_id} 与 {existing_id} 重复 ({edge.source_temp_id} -> {edge.target_temp_id})",
                    affected_temp_ids=[edge.source_temp_id, edge.target_temp_id],
                )
            )
        else:
            edge_pairs[key] = edge.edge_id

    passed = not any(i.severity == "error" for i in issues)
    return LogicReview(passed=passed, issues=issues)


def _canonical_subject(subject: str) -> str:
    if subject in {"english", "chinese", "语文", "中文"}:
        return "language"
    return subject


# ── Compilable Graph Builder ──

def _build_compilable(
    *,
    nodes: list[CandidateNode],
    relays: list[CandidateRelay],
    edges: list[CandidateEdge],
    naming: NamingReview,
    logic: LogicReview,
    node_by_id: dict[str, CandidateNode],
    relay_by_id: dict[str, CandidateRelay],
) -> tuple[list[CompilableNode], list[CandidateEdge], list[CandidateRelay], dict[str, str], list[str]]:
    # Determine which nodes to drop
    dropped_ids: set[str] = set()
    merge_map: dict[str, str] = {}

    for issue in naming.issues:
        if issue.issue_type == "exercise_title" and issue.severity == "error":
            dropped_ids.add(issue.temp_id)
        elif issue.issue_type == "near_duplicate" and issue.merge_target_temp_id:
            merge_map[issue.temp_id] = issue.merge_target_temp_id
            dropped_ids.add(issue.temp_id)

    # Determine which relays to drop (excessive)
    for issue in logic.issues:
        if issue.issue_type == "excessive_relay":
            dropped_ids.add(issue.temp_id)

    # Determine which edges to drop (self-reference, cross-subject, duplicate)
    dropped_edge_ids: set[str] = set()
    duplicate_edge_ids: set[str] = set()
    edge_pairs: dict[tuple[str, str], str] = {}
    for edge in edges:
        key = (edge.source_temp_id, edge.target_temp_id)
        if key in edge_pairs:
            duplicate_edge_ids.add(edge.edge_id)
        else:
            edge_pairs[key] = edge.edge_id

    for issue in logic.issues:
        if issue.issue_type in {"self_reference", "cross_subject"}:
            for eid in _find_edges_for_issue(edges, issue):
                dropped_edge_ids.add(eid)
        if issue.issue_type == "duplicate_edge":
            for eid in duplicate_edge_ids:
                dropped_edge_ids.add(eid)

    # Build compilable nodes (exclude dropped)
    compilable_nodes: list[CompilableNode] = []
    for node in nodes:
        if node.temp_id in dropped_ids:
            continue
        canonical_title = naming.canonical_titles.get(node.temp_id, node.title)
        compilable_nodes.append(
            CompilableNode(
                temp_id=node.temp_id,
                canonical_title=canonical_title,
                subject=node.subject,
                language_id=node.language_id,
                facet=node.facet,
                summary=node.summary,
                node_kind="knowledge",
                parent_temp_ids=[],
                prerequisite_temp_ids=[],
                edge_type="part_of",
                tags=list(node.tags),
                difficulty=node.difficulty,
                source_temp_ids=[node.temp_id],
            )
        )

    # Build compilable relays (exclude dropped)
    compilable_relays: list[CandidateRelay] = []
    for relay in relays:
        if relay.relay_id in dropped_ids:
            continue
        filtered_children = [cid for cid in relay.children_temp_ids if cid not in dropped_ids and cid not in merge_map]
        if not filtered_children:
            continue
        r = relay.model_copy(deep=True)
        r.children_temp_ids = filtered_children
        r.parent_temp_ids = [pid for pid in r.parent_temp_ids if pid not in dropped_ids]
        compilable_relays.append(r)

    # Build compilable edges (exclude dropped, remap after merge)
    compilable_edges: list[CandidateEdge] = []
    for edge in edges:
        if edge.edge_id in dropped_edge_ids:
            continue
        src = merge_map.get(edge.source_temp_id, edge.source_temp_id)
        tgt = merge_map.get(edge.target_temp_id, edge.target_temp_id)
        if src in dropped_ids or tgt in dropped_ids:
            continue
        # Drop self-references created by merge remap
        if src == tgt:
            continue
        e = edge.model_copy(deep=True)
        e.source_temp_id = src
        e.target_temp_id = tgt
        e.review_status = "reviewed"
        compilable_edges.append(e)

    # Deduplicate edges (same src/tgt/type after remap)
    seen_edge_keys: set[tuple[str, str, str]] = set()
    deduped_edges: list[CandidateEdge] = []
    for e in compilable_edges:
        key = (e.source_temp_id, e.target_temp_id, e.edge_type)
        if key not in seen_edge_keys:
            seen_edge_keys.add(key)
            deduped_edges.append(e)
    compilable_edges = deduped_edges

    # Populate parent/prereq from edges (dedup)
    node_parents: dict[str, list[str]] = {}
    node_prereqs: dict[str, list[str]] = {}
    for edge in compilable_edges:
        if edge.edge_kind == "parent_child" or edge.edge_type == "part_of":
            node_parents.setdefault(edge.source_temp_id, []).append(edge.target_temp_id)
        elif edge.edge_type == "requires":
            node_prereqs.setdefault(edge.source_temp_id, []).append(edge.target_temp_id)

    for cn in compilable_nodes:
        cn.parent_temp_ids = list(dict.fromkeys(node_parents.get(cn.temp_id, [])))
        cn.prerequisite_temp_ids = list(dict.fromkeys(node_prereqs.get(cn.temp_id, [])))

    return (
        compilable_nodes,
        compilable_edges,
        compilable_relays,
        merge_map,
        sorted(dropped_ids),
    )


def _find_edges_for_issue(edges: list[CandidateEdge], issue: LogicIssue) -> list[str]:
    eids: list[str] = []
    affected = set(issue.affected_temp_ids)
    if issue.issue_type == "self_reference":
        for e in edges:
            if e.source_temp_id == e.target_temp_id:
                eids.append(e.edge_id)
    elif issue.issue_type == "cross_subject":
        for e in edges:
            if e.source_temp_id in affected and e.target_temp_id in affected:
                eids.append(e.edge_id)
    return eids


# ── Compilation Layer ──

from dataclasses import dataclass, field


@dataclass
class CompileResult:
    temp_to_topic: dict[str, str] = field(default_factory=dict)
    created_topic_count: int = 0
    relay_count: int = 0
    knowledge_count: int = 0
    relinked_segment_count: int = 0
    errors: list[str] = field(default_factory=list)


def compile_review_result(
    backend: "SessionBackend",
    review_result: ReviewResult,
    candidate_graph: CandidateGraph,
    *,
    resource_id_override: str | None = None,
) -> CompileResult:
    result = CompileResult()

    # ── Phase 0: Normalize relay IDs ──
    relay_id_alias: dict[str, str] = {}
    for i, relay in enumerate(review_result.compilable_relays, start=1):
        expected_id = f"relay_{i:03d}"
        if relay.relay_id != expected_id:
            relay_id_alias[relay.relay_id] = expected_id
    if relay_id_alias:
        for relay in review_result.compilable_relays:
            if relay.relay_id in relay_id_alias:
                relay.relay_id = relay_id_alias[relay.relay_id]
        for edge in review_result.compilable_edges:
            if edge.source_temp_id in relay_id_alias:
                edge.source_temp_id = relay_id_alias[edge.source_temp_id]
            if edge.target_temp_id in relay_id_alias:
                edge.target_temp_id = relay_id_alias[edge.target_temp_id]
        for key in sorted(relay_id_alias):
            result.errors.append(f"relay id '{key}' normalized to '{relay_id_alias[key]}'")

    # ── Phase 0b: Build temp_id lookup ──
    node_by_temp: dict[str, CompilableNode] = {
        n.temp_id: n for n in review_result.compilable_nodes
    }
    relay_ids = {r.relay_id for r in review_result.compilable_relays}

    # Resolve merge_map: merged_id → canonical_temp_id
    merge_inverse: dict[str, list[str]] = {}
    for merged, canonical in review_result.merge_map.items():
        merge_inverse.setdefault(canonical, []).append(merged)

    # ── Phase 1: Create and approve relays ──
    relay_topic_map: dict[str, str] = {}
    relay_proposal_map: dict[str, str] = {}
    # Find subject root topic for relay parenting
    subject_root_topic_id = _find_subject_root(backend, review_result)

    for relay in review_result.compilable_relays:
        _proposal_tags = _make_compile_tags(relay.subject, relay.language_id, relay.facet)
        # Resolve parent ids: relay.parent_temp_ids → topic IDs, or fall back to subject root
        relay_parent_ids: list[str] = []
        relay_pending_parents: list[str] = []
        for parent_ref in relay.parent_temp_ids:
            if parent_ref in relay_topic_map:
                relay_parent_ids.append(relay_topic_map[parent_ref])
            elif parent_ref in relay_proposal_map:
                relay_pending_parents.append(relay_proposal_map[parent_ref])
        if not relay_parent_ids and not relay_pending_parents and subject_root_topic_id:
            relay_parent_ids = [subject_root_topic_id]
        try:
            proposal = backend.create_graph_proposal_from_resource(
                title=relay.title,
                summary=relay.grouping_rationale,
                tags=_proposal_tags,
                parent_node_ids=relay_parent_ids,
                pending_parent_proposal_ids=relay_pending_parents,
                edge_type="part_of",
                reason="compiled relay",
            )
            relay_proposal_map[relay.relay_id] = proposal.proposal_id
        except Exception as exc:
            result.errors.append(f"relay proposal {relay.relay_id}: {exc}")
            continue

    for relay in review_result.compilable_relays:
        proposal_id = relay_proposal_map.get(relay.relay_id)
        if not proposal_id:
            continue
        try:
            _, __, topic, ___, ____ = backend.approve_graph_proposal(
                proposal_id=proposal_id,
                title=relay.title,
                summary=relay.grouping_rationale,
                difficulty=1,
                tags=_make_compile_tags(relay.subject, relay.language_id, relay.facet),
                reason="compiled relay",
            )
            relay_topic_map[relay.relay_id] = topic.topic_id
            result.temp_to_topic[relay.relay_id] = topic.topic_id
            result.relay_count += 1
            result.created_topic_count += 1
        except Exception as exc:
            result.errors.append(f"relay approve {relay.relay_id}: {exc}")

    # ── Phase 2: Create proposals for all knowledge nodes ──
    knowledge_proposals: dict[str, str] = {}
    knowledge_nodes: list[CompilableNode] = list(review_result.compilable_nodes)

    # Pass 2a: Create proposals (parent_node_ids = relay parents only)
    for node in knowledge_nodes:
        canonical_title = node.canonical_title or node.temp_id
        parent_topic_ids: list[str] = []
        pending_parent_ids: list[str] = []

        for parent_ref in node.parent_temp_ids:
            if parent_ref in relay_topic_map:
                parent_topic_ids.append(relay_topic_map[parent_ref])
            elif parent_ref in relay_proposal_map:
                pending_parent_ids.append(relay_proposal_map[parent_ref])

        # For prerequisite_refs, we'll handle them post-approval
        # Only prereq refs that are already approved relays go here
        prereq_topic_ids: list[str] = []
        for prereq_ref in node.prerequisite_temp_ids:
            if prereq_ref in relay_topic_map:
                prereq_topic_ids.append(relay_topic_map[prereq_ref])

        edge_type = node.edge_type
        if not parent_topic_ids and not pending_parent_ids and prereq_topic_ids:
            parent_topic_ids = prereq_topic_ids
            prereq_topic_ids = []
            edge_type = "requires"

        _proposal_tags = _make_compile_tags(node.subject, node.language_id, node.facet, is_knowledge=True)
        try:
            proposal = backend.create_graph_proposal_from_resource(
                title=canonical_title,
                summary=node.summary,
                tags=_proposal_tags,
                parent_node_ids=parent_topic_ids,
                pending_parent_proposal_ids=pending_parent_ids,
                prerequisite_node_ids=prereq_topic_ids,
                edge_type=edge_type,
                reason="compiled knowledge node",
            )
            knowledge_proposals[node.temp_id] = proposal.proposal_id
        except Exception as exc:
            result.errors.append(f"knowledge proposal {node.temp_id}: {exc}")

    # Pass 2b: Approve knowledge nodes in dependency order
    approved: set[str] = set()

    def _pending_count(n: CompilableNode) -> int:
        count = 0
        for ref in n.prerequisite_temp_ids:
            if ref not in relay_topic_map and ref not in approved:
                count += 1
        return count

    remaining = sorted(knowledge_nodes, key=_pending_count)

    for node in remaining:
        proposal_id = knowledge_proposals.get(node.temp_id)
        if not proposal_id:
            continue
        canonical_title = node.canonical_title or node.temp_id
        try:
            _, __, topic, ___, ____ = backend.approve_graph_proposal(
                proposal_id=proposal_id,
                title=canonical_title,
                summary=node.summary,
                difficulty=node.difficulty or 1,
                tags=_make_compile_tags(node.subject, node.language_id, node.facet, is_knowledge=True),
                reason="compiled knowledge node",
            )
            result.temp_to_topic[node.temp_id] = topic.topic_id
            result.knowledge_count += 1
            result.created_topic_count += 1
            approved.add(node.temp_id)

            for merged_src in node.source_temp_ids:
                if merged_src != node.temp_id:
                    result.temp_to_topic[merged_src] = topic.topic_id
            for merged_id in merge_inverse.get(node.temp_id, []):
                result.temp_to_topic[merged_id] = topic.topic_id
        except Exception as exc:
            result.errors.append(f"knowledge approve {node.temp_id}: {exc}")

    # ── Phase 3: Post-approval — update prerequisite edges between knowledge nodes ──
    _apply_prerequisite_edges(
        backend=backend,
        knowledge_nodes=knowledge_nodes,
        temp_to_topic=result.temp_to_topic,
    )

    # ── Phase 4: Relink resource segments ──
    effective_resource_id = resource_id_override or candidate_graph.document.resource_id
    result.relinked_segment_count = _relink_segments_to_topics(
        backend=backend,
        resource_id=effective_resource_id,
        candidate_graph=candidate_graph,
        temp_to_topic=result.temp_to_topic,
    )

    # ── Phase 5: Update ingestion status ──
    net_node_count = len(review_result.compilable_nodes)
    if net_node_count > 0:
        try:
            backend.update_resource_ingestion(
                effective_resource_id,
                status="completed",
                extracted_node_count=net_node_count,
            )
        except Exception:
            pass

    return result


def _apply_prerequisite_edges(
    *,
    backend: "SessionBackend",
    knowledge_nodes: list[CompilableNode],
    temp_to_topic: dict[str, str],
) -> None:
    state = backend.load_app_state(include_history=False)
    topic_by_id: dict[str, TopicNode] = {t.topic_id: t for t in state.curriculum.topics}
    changed = False

    for node in knowledge_nodes:
        source_topic_id = temp_to_topic.get(node.temp_id)
        if not source_topic_id:
            continue
        source_topic = topic_by_id.get(source_topic_id)
        if source_topic is None:
            continue

        for prereq_ref in node.prerequisite_temp_ids:
            prereq_topic_id = temp_to_topic.get(prereq_ref)
            if not prereq_topic_id or prereq_topic_id == source_topic_id:
                continue
            if prereq_topic_id not in source_topic.prerequisite_ids:
                source_topic.prerequisite_ids = list(dict.fromkeys([*source_topic.prerequisite_ids, prereq_topic_id]))
                changed = True

    if changed:
        backend.save_app_state(state)


def _relink_segments_to_topics(
    *,
    backend: "SessionBackend",
    resource_id: str,
    candidate_graph: CandidateGraph,
    temp_to_topic: dict[str, str],
) -> int:
    from src.core.models import ResourceSegment

    resource = backend.get_resource(resource_id)
    if resource is None:
        return 0

    segments = list(resource.segments)

    # Build block → candidate mapping from candidate graph
    block_candidate_map: dict[int, list[str]] = {}
    for node in candidate_graph.candidate_nodes:
        for ref in node.source_segment_refs:
            for idx, seg in enumerate(candidate_graph.source_segments):
                if seg.segment_id == ref.segment_id:
                    block_candidate_map.setdefault(idx, []).append(node.temp_id)

    relinked = 0
    for segment in segments:
        seq = segment.sequence_index
        # Try to match segment to source segment by index
        if seq - 1 < len(candidate_graph.source_segments):
            candidates = block_candidate_map.get(seq - 1, [])
            if candidates:
                # Find the best topic_id from candidate node
                for cand_id in candidates:
                    topic_id = temp_to_topic.get(cand_id)
                    if topic_id:
                        segment.status = "classified"
                        segment.decision = "link"
                        segment.topic_id = topic_id
                        segment.confidence = max(segment.confidence, 0.85)
                        segment.reason = "compiled from reviewed candidate"
                        relinked += 1
                        break

    if relinked > 0:
        backend.replace_resource_segments(resource_id, segments)

    return relinked


def _find_subject_root(backend: "SessionBackend", review_result: ReviewResult) -> str | None:
    state = backend.load_app_state(include_history=False)
    subject = review_result.compilable_relays[0].subject if review_result.compilable_relays else ""
    if not subject and review_result.compilable_nodes:
        subject = review_result.compilable_nodes[0].subject
    for topic in state.curriculum.topics:
        if "facet:root" in topic.tags and f"subject:{subject}" in topic.tags:
            return topic.topic_id
    return None


def _make_compile_tags(
    subject: str,
    language_id: str | None,
    facet: str,
    is_knowledge: bool = False,
) -> list[str]:
    tags = [f"subject:{subject}", f"facet:{facet}"]
    if subject == "language" and language_id:
        tags.append(f"language:{language_id}")
    tags.append("compiled")
    if is_knowledge:
        tags.append("resource-approved")
        tags.append("active")
    return list(dict.fromkeys(tags))
