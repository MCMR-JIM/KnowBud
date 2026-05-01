from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.enums import LearningPhase
from src.core.models import GraphProposalRecord, NodeMastery, TopicNode
from src.services.document_ingestion import ingest_document_resource
from src.services.session_backend import SessionBackend


@dataclass(frozen=True)
class SubjectSpec:
    key: str
    title: str
    focus_terms: list[str]
    shared_tags: list[str]


SUBJECT_SPECS = [
    SubjectSpec(
        key="dino",
        title="恐龙专题",
        focus_terms=["化石", "白垩纪", "陨石", "植食", "肉食", "足迹", "灭绝", "栖息地", "骨骼", "孵化", "演化", "考古"],
        shared_tags=["恐龙", "史前", "科学"],
    ),
    SubjectSpec(
        key="math",
        title="数学专题",
        focus_terms=["数数", "加法", "减法", "比较", "图形", "长度", "时钟", "分组", "规律", "乘法", "平均", "应用题"],
        shared_tags=["数学", "计算", "练习"],
    ),
    SubjectSpec(
        key="lang",
        title="表达专题",
        focus_terms=["看图说话", "组句", "复述", "描写", "比喻", "顺序", "问答", "阅读", "词语", "情绪", "标题", "写话"],
        shared_tags=["语文", "表达", "阅读"],
    ),
    SubjectSpec(
        key="space",
        title="天文专题",
        focus_terms=["太阳", "月球", "行星", "恒星", "彗星", "轨道", "昼夜", "四季", "银河", "火箭", "重力", "观测"],
        shared_tags=["天文", "宇宙", "科学"],
    ),
    SubjectSpec(
        key="bio",
        title="生物专题",
        focus_terms=["种子", "发芽", "根茎", "叶子", "授粉", "食物链", "昆虫", "鸟类", "生态", "水循环", "森林", "保护"],
        shared_tags=["生物", "自然", "观察"],
    ),
]

PROPOSE_TRIGGER_TERMS = ["链式变化", "进阶解释", "综合应用", "迁移问题"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk simulation for topic-resource graph ingestion.")
    parser.add_argument("--topics-per-subject", type=int, default=12, help="How many topics to generate per subject.")
    parser.add_argument("--docs-per-topic", type=int, default=8, help="How many synthetic documents to generate per topic.")
    parser.add_argument("--paragraphs-per-doc", type=int, default=4, help="How many text blocks each document contains.")
    parser.add_argument("--cross-topic-rate", type=float, default=0.35, help="Chance that a paragraph targets a non-home topic.")
    parser.add_argument("--seed", type=int, default=20260501, help="Random seed for deterministic simulation.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data") / "simulated_graph",
        help="Directory to store generated state, docs, and reports.",
    )
    parser.add_argument("--keep-existing", action="store_true", help="Reuse an existing output directory instead of deleting it first.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    output_dir = args.output_dir.resolve()
    prepare_output_dir(output_dir, keep_existing=args.keep_existing)

    backend = build_backend(output_dir)
    topics = build_topics(topics_per_subject=args.topics_per_subject)
    install_state(backend, topics=topics, rng=rng)
    install_fake_classifier(backend, topics=topics)

    docs_dir = output_dir / "generated_docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    resources_summary = generate_and_ingest_resources(
        backend=backend,
        topics=topics,
        docs_dir=docs_dir,
        docs_per_topic=args.docs_per_topic,
        paragraphs_per_doc=args.paragraphs_per_doc,
        cross_topic_rate=args.cross_topic_rate,
        rng=rng,
    )

    report = build_graph_report(backend=backend, topics=topics, resources_summary=resources_summary, args=args)
    write_reports(output_dir=output_dir, report=report)
    print_report_summary(output_dir=output_dir, report=report)


def prepare_output_dir(output_dir: Path, *, keep_existing: bool) -> None:
    if output_dir.exists() and not keep_existing:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def build_backend(output_dir: Path) -> SessionBackend:
    backend = SessionBackend()
    backend.state_file = output_dir / "state.json"
    backend.state_db_file = str(output_dir / "state.db")
    backend.log_file = output_dir / "decision_trace.jsonl"
    backend.audio_artifact_root = output_dir / "audio_artifacts"
    return backend


def build_topics(*, topics_per_subject: int) -> list[TopicNode]:
    topics: list[TopicNode] = []
    for spec in SUBJECT_SPECS:
        focus_terms = expand_terms(spec.focus_terms, count=topics_per_subject)
        for index in range(topics_per_subject):
            topic_id = f"{spec.key}_{index + 1:02d}"
            term = focus_terms[index]
            prerequisite_ids: list[str] = []
            if index >= 1:
                prerequisite_ids.append(f"{spec.key}_{index:02d}")
            if index >= 3 and index % 3 == 0:
                prerequisite_ids.append(f"{spec.key}_{index - 2:02d}")
            tags = [spec.key, term, *spec.shared_tags, f"阶段{index + 1}"]
            topics.append(
                TopicNode(
                    topic_id=topic_id,
                    title=f"{spec.title} {index + 1:02d} {term}",
                    difficulty=min(5, 1 + (index // 3)),
                    prerequisite_ids=prerequisite_ids,
                    tags=tags,
                )
            )
    return topics


def expand_terms(base_terms: list[str], *, count: int) -> list[str]:
    if count <= len(base_terms):
        return base_terms[:count]
    expanded = list(base_terms)
    suffix = 2
    while len(expanded) < count:
        for term in base_terms:
            expanded.append(f"{term}{suffix}")
            if len(expanded) >= count:
                break
        suffix += 1
    return expanded


def install_state(backend: SessionBackend, *, topics: list[TopicNode], rng: random.Random) -> None:
    state = backend.load_app_state()
    state.learning.current_phase = LearningPhase.LEARNING
    state.learning.current_topic_id = topics[0].topic_id if topics else None
    state.curriculum.topics = topics
    state.learning.mastery_map = build_mastery_map(topics=topics, rng=rng)
    state.learning.graph_proposals = build_graph_proposals(topics=topics, rng=rng)
    backend.save_app_state(state)


def build_mastery_map(*, topics: list[TopicNode], rng: random.Random) -> dict[str, NodeMastery]:
    mastery_map: dict[str, NodeMastery] = {}
    states = ["unknown", "learning", "reviewing", "mastered"]
    weights = [0.1, 0.45, 0.25, 0.2]
    now = datetime.now(timezone.utc)
    for topic in topics:
        mastery_state = rng.choices(states, weights=weights, k=1)[0]
        success_count = rng.randint(0, 18)
        mastery_map[topic.topic_id] = NodeMastery(
            mastery_state=mastery_state,
            depth_level=rng.randint(0, 4),
            stability_level=rng.randint(0, 4),
            success_count=success_count,
            success_streak=rng.randint(0, min(6, success_count)),
            spaced_success_count=rng.randint(0, success_count),
            last_success_ts=(now - timedelta(days=rng.randint(0, 30))).isoformat() if success_count else None,
            last_state_ts=(now - timedelta(days=rng.randint(0, 7))).isoformat(),
            reward_window_granted=rng.random() < 0.2,
        )
    return mastery_map


def build_graph_proposals(*, topics: list[TopicNode], rng: random.Random) -> list[GraphProposalRecord]:
    proposals: list[GraphProposalRecord] = []
    candidate_topics = [topic for idx, topic in enumerate(topics) if idx % 6 == 0 and topic.prerequisite_ids]
    now = datetime.now(timezone.utc)
    statuses = ["proposed", "validated", "shadow", "active"]
    for index, topic in enumerate(candidate_topics, start=1):
        created_at = now - timedelta(days=index)
        proposals.append(
            GraphProposalRecord(
                proposal_id=f"proposal_{index:03d}",
                title=f"补充节点建议 {topic.title}",
                summary=f"建议围绕 {topic.title} 拆出一个更细粒度的延伸节点。",
                trigger="bulk_simulation",
                parent_node_ids=list(topic.prerequisite_ids[:1]),
                edge_type="requires",
                status=statuses[index % len(statuses)],
                reason="模拟观测到多次跨主题资源聚合，需要更细粒度节点。",
                created_topic_id=topic.topic_id,
                observation_count=rng.randint(2, 11),
                created_ts=created_at.isoformat(),
                updated_ts=(created_at + timedelta(hours=12)).isoformat(),
            )
        )
    return proposals


def install_fake_classifier(backend: SessionBackend, *, topics: list[TopicNode]) -> None:
    token_map = build_topic_token_map(topics)

    def classify_or_propose_resource_chunk(
        *,
        chunk_text: str,
        topics: list[TopicNode],
        default_parent_topic_id: str | None = None,
    ) -> dict[str, object]:
        text = chunk_text.lower()
        best_topic_id: str | None = None
        best_score = 0
        tie = False
        for topic in topics:
            score = sum(1 for token in token_map[topic.topic_id] if token and token in text)
            if score > best_score:
                best_topic_id = topic.topic_id
                best_score = score
                tie = False
            elif score and score == best_score:
                tie = True
        trigger_term = next((term for term in PROPOSE_TRIGGER_TERMS if term in chunk_text), None)
        if trigger_term and (best_score < 2 or tie or best_topic_id is None):
            valid_topic_ids = {topic.topic_id for topic in topics}
            fallback_parent_id = default_parent_topic_id if default_parent_topic_id in valid_topic_ids else (topics[0].topic_id if topics else None)
            parent_node_ids = [fallback_parent_id] if fallback_parent_id else []
            keyword = trigger_term
            if best_topic_id is not None:
                matched_topic = next((topic for topic in topics if topic.topic_id == best_topic_id), None)
                if matched_topic is not None:
                    keyword = matched_topic.tags[1] if len(matched_topic.tags) > 1 else matched_topic.title
            return {
                "decision": "propose",
                "topic_id": None,
                "confidence": 0.81,
                "reason": f"片段命中{trigger_term}，但现有主题无法稳定承接该新知识点",
                "proposed_topic": {
                    "title": f"自动扩展：{keyword}",
                    "summary": f"围绕{keyword}补充一个可教学的新节点，用于承接资源中的{trigger_term}内容。",
                    "parent_node_ids": parent_node_ids,
                    "edge_type": "requires",
                },
            }
        if best_score < 2 or tie or best_topic_id is None:
            return {
                "decision": "unclassified",
                "topic_id": None,
                "confidence": 0.32 if best_score else 0.18,
                "reason": "关键词命中不足或存在并列候选",
                "proposed_topic": None,
            }
        confidence = min(0.97, 0.50 + (best_score * 0.09))
        return {
            "decision": "link",
            "topic_id": best_topic_id,
            "confidence": round(confidence, 2),
            "reason": f"命中 {best_score} 个主题特征词",
            "proposed_topic": None,
        }

    backend.llm_skill.classify_or_propose_resource_chunk = classify_or_propose_resource_chunk


def build_topic_token_map(topics: list[TopicNode]) -> dict[str, set[str]]:
    token_map: dict[str, set[str]] = {}
    for topic in topics:
        tokens = {topic.topic_id.lower()}
        tokens.update(token.lower() for token in topic.tags if token)
        tokens.update(part.lower() for part in topic.title.replace("-", " ").split() if part)
        token_map[topic.topic_id] = tokens
    return token_map


def generate_and_ingest_resources(
    *,
    backend: SessionBackend,
    topics: list[TopicNode],
    docs_dir: Path,
    docs_per_topic: int,
    paragraphs_per_doc: int,
    cross_topic_rate: float,
    rng: random.Random,
) -> dict[str, object]:
    topic_groups = group_topics_by_subject(topics)
    resource_ids: list[str] = []
    resource_cross_links: list[dict[str, object]] = []
    proposed_segments = 0
    unclassified_segments = 0
    for home_topic in topics:
        for doc_index in range(docs_per_topic):
            paragraph_topics = choose_paragraph_topics(
                home_topic=home_topic,
                topic_groups=topic_groups,
                paragraphs_per_doc=paragraphs_per_doc,
                cross_topic_rate=cross_topic_rate,
                rng=rng,
            )
            content = "\n\n".join(
                build_paragraph(topic=paragraph_topic, paragraph_index=index, rng=rng)
                for index, paragraph_topic in enumerate(paragraph_topics, start=1)
            )
            filename = f"{home_topic.topic_id}_{doc_index + 1:03d}.txt"
            source_path = docs_dir / filename
            source_path.write_text(content, encoding="utf-8")

            record = backend.create_resource_record(
                topic_id=home_topic.topic_id,
                resource_name=f"{home_topic.title} 混合资源 {doc_index + 1:03d}",
                category="learn",
                media_type="txt",
                mime_type="text/plain",
                original_filename=filename,
                stored_path=str(source_path),
                size_bytes=source_path.stat().st_size,
            )
            time.sleep(0.002)
            segments = ingest_document_resource(backend=backend, record=record, topics=topics)
            resource_ids.append(record.resource_id)
            proposed_segments += sum(1 for segment in segments if segment.status == "proposed")
            unclassified_segments += sum(1 for segment in segments if segment.status == "unclassified")

            linked_topics = sorted({segment.topic_id for segment in segments if segment.topic_id})
            if any(topic_id != home_topic.topic_id for topic_id in linked_topics):
                resource_cross_links.append(
                    {
                        "resource_id": record.resource_id,
                        "home_topic_id": home_topic.topic_id,
                        "linked_topic_ids": linked_topics,
                    }
                )

            backend.append_learning_event(
                kind="resource_ingested",
                payload={
                    "resource_id": record.resource_id,
                    "segment_count": len(segments),
                    "classified_count": sum(1 for segment in segments if segment.status == "classified"),
                    "proposed_count": sum(1 for segment in segments if segment.status == "proposed"),
                    "unclassified_count": sum(1 for segment in segments if segment.status == "unclassified"),
                    "parse_failed_count": sum(1 for segment in segments if segment.status == "parse_failed"),
                    "unsupported_count": sum(1 for segment in segments if segment.status == "unsupported"),
                    "media_type": "txt",
                },
            )

    return {
        "resource_ids": resource_ids,
        "cross_links": resource_cross_links,
        "proposed_segments": proposed_segments,
        "unclassified_segments": unclassified_segments,
    }


def group_topics_by_subject(topics: list[TopicNode]) -> dict[str, list[TopicNode]]:
    grouped: dict[str, list[TopicNode]] = defaultdict(list)
    for topic in topics:
        grouped[topic.topic_id.split("_", 1)[0]].append(topic)
    return dict(grouped)


def choose_paragraph_topics(
    *,
    home_topic: TopicNode,
    topic_groups: dict[str, list[TopicNode]],
    paragraphs_per_doc: int,
    cross_topic_rate: float,
    rng: random.Random,
) -> list[TopicNode]:
    result = [home_topic]
    same_subject = topic_groups[home_topic.topic_id.split("_", 1)[0]]
    all_topics = [topic for topics in topic_groups.values() for topic in topics]
    while len(result) < paragraphs_per_doc:
        if rng.random() < cross_topic_rate:
            pool = [topic for topic in all_topics if topic.topic_id != home_topic.topic_id]
        else:
            pool = [topic for topic in same_subject if topic.topic_id != home_topic.topic_id]
            if not pool:
                pool = [home_topic]
        result.append(rng.choice(pool))
    rng.shuffle(result)
    return result


def build_paragraph(*, topic: TopicNode, paragraph_index: int, rng: random.Random) -> str:
    tags = list(topic.tags)
    emphasis = rng.sample(tags, k=min(3, len(tags)))
    if rng.random() < 0.14:
        trigger_term = rng.choice(PROPOSE_TRIGGER_TERMS)
        keyword = emphasis[1] if len(emphasis) > 1 else emphasis[0]
        return (
            f"第{paragraph_index}段：这是一道{trigger_term}练习，围绕{keyword}展开，"
            f"鼓励孩子把当前内容迁移到一个更细的新情境中。"
        )
    examples = [
        f"这段材料聚焦 {topic.title}。",
        f"核心词包括 {'、'.join(emphasis)}。",
        f"老师会围绕 {topic.topic_id} 设计观察、讨论和提问。",
        f"孩子需要根据 {'、'.join(emphasis[:2])} 解释现象并完成小练习。",
        f"该段还会反复提到 {topic.title} 与 {'、'.join(emphasis)} 的联系。",
    ]
    rng.shuffle(examples)
    return f"第{paragraph_index}段：" + "".join(examples)


def build_graph_report(
    *,
    backend: SessionBackend,
    topics: list[TopicNode],
    resources_summary: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    state = backend.load_app_state(include_history=False)
    all_resources = []
    seen_resource_ids: set[str] = set()
    for topic in topics:
        for resource in backend.list_resources_related_to_topic(topic.topic_id):
            if resource.resource_id in seen_resource_ids:
                continue
            seen_resource_ids.add(resource.resource_id)
            all_resources.append(resource)

    segment_status_counter: Counter[str] = Counter()
    topic_segment_counter: Counter[str] = Counter()
    resource_topic_counter: Counter[str] = Counter()
    cross_topic_pair_counter: Counter[str] = Counter()
    resource_rows: list[dict[str, object]] = []
    for resource in all_resources:
        linked_topics = sorted({segment.topic_id for segment in resource.segments if segment.topic_id})
        resource_topic_counter[resource.topic_id] += 1
        for segment in resource.segments:
            segment_status_counter[segment.status] += 1
            if segment.topic_id:
                topic_segment_counter[segment.topic_id] += 1
                if segment.topic_id != resource.topic_id:
                    cross_topic_pair_counter[f"{resource.topic_id}->{segment.topic_id}"] += 1
        resource_rows.append(
            {
                "resource_id": resource.resource_id,
                "home_topic_id": resource.topic_id,
                "segment_count": len(resource.segments),
                "linked_topic_ids": linked_topics,
            }
        )

    prerequisite_edges = [
        {"from": prerequisite_id, "to": topic.topic_id}
        for topic in topics
        for prerequisite_id in topic.prerequisite_ids
    ]
    dependents_map: dict[str, list[str]] = defaultdict(list)
    for edge in prerequisite_edges:
        dependents_map[str(edge["from"])].append(str(edge["to"]))

    mastery_state_counter = Counter(mastery.mastery_state for mastery in state.learning.mastery_map.values())
    proposal_status_counter = Counter(proposal.status for proposal in state.learning.graph_proposals)

    topic_rows = []
    for topic in topics:
        mastery = state.learning.mastery_map.get(topic.topic_id)
        topic_rows.append(
            {
                "topic_id": topic.topic_id,
                "title": topic.title,
                "difficulty": topic.difficulty,
                "prerequisite_ids": list(topic.prerequisite_ids),
                "dependent_ids": sorted(dependents_map.get(topic.topic_id, [])),
                "resource_count": sum(1 for row in resource_rows if topic.topic_id in row["linked_topic_ids"] or row["home_topic_id"] == topic.topic_id),
                "classified_segment_count": topic_segment_counter[topic.topic_id],
                "mastery_state": mastery.mastery_state if mastery else "unknown",
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "simulation": {
            "seed": args.seed,
            "topics_per_subject": args.topics_per_subject,
            "docs_per_topic": args.docs_per_topic,
            "paragraphs_per_doc": args.paragraphs_per_doc,
            "cross_topic_rate": args.cross_topic_rate,
            "subject_count": len(SUBJECT_SPECS),
        },
        "counts": {
            "topic_count": len(topics),
            "prerequisite_edge_count": len(prerequisite_edges),
            "resource_count": len(all_resources),
            "segment_count": sum(len(resource.segments) for resource in all_resources),
            "classified_segments": segment_status_counter["classified"],
            "proposed_segments": resources_summary["proposed_segments"],
            "unclassified_segments": resources_summary["unclassified_segments"],
            "cross_topic_resource_count": len(resources_summary["cross_links"]),
            "graph_proposals": len(state.learning.graph_proposals),
        },
        "status_breakdown": {
            "segment_status": dict(segment_status_counter),
            "mastery_state": dict(mastery_state_counter),
            "proposal_status": dict(proposal_status_counter),
        },
        "topics": topic_rows,
        "prerequisite_edges": prerequisite_edges,
        "resources": resource_rows,
        "cross_topic_pairs_top20": [
            {"pair": pair, "segment_count": count}
            for pair, count in cross_topic_pair_counter.most_common(20)
        ],
        "cross_topic_resources_sample": resources_summary["cross_links"][:40],
        "graph_proposals": [proposal.model_dump() for proposal in state.learning.graph_proposals],
    }


def write_reports(*, output_dir: Path, report: dict[str, object]) -> None:
    json_path = output_dir / "graph_report.json"
    markdown_path = output_dir / "graph_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(build_markdown_report(report), encoding="utf-8")


def build_markdown_report(report: dict[str, object]) -> str:
    counts = report["counts"]
    simulation = report["simulation"]
    lines = [
        "# Simulated Resource Graph Report",
        "",
        "## Simulation",
        f"- Seed: {simulation['seed']}",
        f"- Subjects: {simulation['subject_count']}",
        f"- Topics per subject: {simulation['topics_per_subject']}",
        f"- Docs per topic: {simulation['docs_per_topic']}",
        f"- Paragraphs per doc: {simulation['paragraphs_per_doc']}",
        f"- Cross-topic rate: {simulation['cross_topic_rate']}",
        "",
        "## Counts",
        f"- Topics: {counts['topic_count']}",
        f"- Prerequisite edges: {counts['prerequisite_edge_count']}",
        f"- Resources: {counts['resource_count']}",
        f"- Segments: {counts['segment_count']}",
        f"- Classified segments: {counts['classified_segments']}",
        f"- Proposed segments: {counts['proposed_segments']}",
        f"- Unclassified segments: {counts['unclassified_segments']}",
        f"- Cross-topic resources: {counts['cross_topic_resource_count']}",
        f"- Graph proposals: {counts['graph_proposals']}",
        "",
        "## Top Cross-topic Pairs",
    ]
    for item in report["cross_topic_pairs_top20"]:
        lines.append(f"- {item['pair']}: {item['segment_count']}")
    lines.extend(["", "## Topics"])
    for topic in report["topics"]:
        lines.append(
            f"- {topic['topic_id']} | prereq={','.join(topic['prerequisite_ids']) or '-'} | dependents={','.join(topic['dependent_ids']) or '-'} | resources={topic['resource_count']} | classified_segments={topic['classified_segment_count']} | mastery={topic['mastery_state']}"
        )
    return "\n".join(lines) + "\n"


def print_report_summary(*, output_dir: Path, report: dict[str, object]) -> None:
    counts = report["counts"]
    print(f"Simulation output: {output_dir}")
    print(
        "Graph counts: "
        f"topics={counts['topic_count']}, "
        f"prerequisite_edges={counts['prerequisite_edge_count']}, "
        f"resources={counts['resource_count']}, "
        f"segments={counts['segment_count']}, "
        f"classified={counts['classified_segments']}, "
        f"proposed={counts['proposed_segments']}, "
        f"unclassified={counts['unclassified_segments']}, "
        f"graph_proposals={counts['graph_proposals']}, "
        f"cross_topic_resources={counts['cross_topic_resource_count']}"
    )
    if report["cross_topic_pairs_top20"]:
        top_pair = report["cross_topic_pairs_top20"][0]
        print(f"Top cross-topic pair: {top_pair['pair']} ({top_pair['segment_count']} segments)")
    print(f"Report JSON: {output_dir / 'graph_report.json'}")
    print(f"Report Markdown: {output_dir / 'graph_report.md'}")


if __name__ == "__main__":
    main()
