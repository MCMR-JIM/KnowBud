from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.models import GraphProposalRecord, ResourceRecord, ResourceSegment, TopicNode

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend


ENGLISH_ACTIVITY_MARKERS = (
    "role-play",
    "role play",
    "project",
    "draw a map",
    "work in groups",
    "group work",
    "pair work",
    "make a poster",
    "act out",
    "小组活动",
    "课堂活动",
    "合作完成",
    "两人一组",
)

ENGLISH_ACTIVITY_TITLE_MARKERS = (
    "role-play",
    "role play",
    "project",
    "draw a map",
    "work in groups",
    "group work",
    "pair work",
    "listen and repeat",
    "complete the passage",
    "fill in",
    "choose",
    "match",
    "act out",
    "design a zoo",
    "设计动物园",
    "制定班级规则",
)

ROOT_MARKER_TAGS = {"facet:root", "subject_root", "graph:root"}


@dataclass(frozen=True)
class SubjectProfile:
    subject_id: str
    root_title: str
    aliases: tuple[str, ...]
    strong_markers: tuple[str, ...]
    weak_markers: tuple[str, ...]
    facets: tuple[str, ...]
    default_facet: str
    non_node_patterns: tuple[str, ...]
    canonical_title_rules: dict[str, tuple[tuple[str, str], ...]]
    default_edge_type: str


LANGUAGE_INSTANCE_MARKERS: dict[str, tuple[str, ...]] = {
    "english": ("英语", "english", "present continuous", "simple past", "grammar focus", "listen and repeat"),
    "chinese": ("语文", "中文", "汉语", "chinese language", "chinese reading", "chinese writing", "古诗", "文言文", "作文", "阅读理解"),
}


SUBJECT_PROFILES: dict[str, SubjectProfile] = {
    "language": SubjectProfile(
        subject_id="language",
        root_title="语言",
        aliases=("语言", "英语", "语文", "中文", "english", "chinese language", "chinese reading", "chinese writing"),
        strong_markers=("英语", "english", "语文", "中文", "grammar focus", "listen and repeat", "role-play", "pronunciation", "chinese language", "chinese reading", "chinese writing"),
        weak_markers=("grammar", "vocabulary", "phonics", "reading comprehension", "guided writing", "present continuous", "simple past", "一般过去时", "现在进行时", "阅读理解", "作文"),
        facets=("grammar", "vocabulary", "pronunciation", "functional_expression", "reading", "writing", "culture"),
        default_facet="culture",
        non_node_patterns=(r"\bunit\s*\d+\b", r"\blesson\s*\d+\b", r"\bfill in\b", r"\bchoose\b", r"\bmatch\b", r"role-play", r"project", r"work in groups", r"listen and repeat", r"设计动物园", r"制定班级规则"),
        canonical_title_rules={
            "grammar": ((r"\bpresent continuous\b", "现在进行时"), (r"\bsimple past\b", "一般过去时"), (r"\bsimple present\b", "一般现在时")),
        },
        default_edge_type="related",
    ),
    "math": SubjectProfile(
        subject_id="math",
        root_title="数学",
        aliases=("数学", "math"),
        strong_markers=("数学", "equation", "geometry", "algebra", "fraction", "定理", "证明", "推论", "坐标系", "勾股定理", "方程"),
        weak_markers=("加法", "减法", "乘法", "除法", "函数", "几何", "面积", "周长", "一元一次方程", "不等式", "统计"),
        facets=("concept", "operation", "theorem_or_rule", "method", "application"),
        default_facet="concept",
        non_node_patterns=(r"练习", r"活动", r"project"),
        canonical_title_rules={},
        default_edge_type="requires",
    ),
    "science": SubjectProfile(
        subject_id="science",
        root_title="科学",
        aliases=("科学", "science"),
        strong_markers=("科学", "experiment", "ecosystem", "matter", "光合作用", "细胞", "化合物", "元素周期", "电路"),
        weak_markers=("实验", "现象", "模型", "能量", "定律", "公式"),
        facets=("concept", "quantity", "formula", "law", "experiment", "phenomenon", "model"),
        default_facet="concept",
        non_node_patterns=(r"练习", r"活动", r"project"),
        canonical_title_rules={},
        default_edge_type="related",
    ),
    "physics": SubjectProfile(
        subject_id="physics",
        root_title="物理",
        aliases=("物理", "physics"),
        strong_markers=("物理", "velocity", "distance", "speed", "force", "energy", "acceleration", "motion"),
        weak_markers=("公式", "定律", "质量", "时间", "路程", "速度", "力", "能量"),
        facets=("concept", "quantity", "formula", "law", "experiment", "phenomenon", "model"),
        default_facet="concept",
        non_node_patterns=(r"练习", r"活动", r"project"),
        canonical_title_rules={},
        default_edge_type="related",
    ),
    "chemistry": SubjectProfile(
        subject_id="chemistry",
        root_title="化学",
        aliases=("化学", "chemistry"),
        strong_markers=("化学", "molecule", "atom", "reaction", "acid", "base"),
        weak_markers=("分子", "原子", "反应", "溶液", "酸", "碱"),
        facets=("concept", "quantity", "formula", "law", "experiment", "phenomenon", "model"),
        default_facet="concept",
        non_node_patterns=(r"练习", r"活动", r"project"),
        canonical_title_rules={},
        default_edge_type="related",
    ),
    "biology": SubjectProfile(
        subject_id="biology",
        root_title="生物",
        aliases=("生物", "biology"),
        strong_markers=("生物", "cell", "cells", "dna", "organism", "ecosystem"),
        weak_markers=("细胞", "组织", "器官", "生态系统", "遗传", "实验"),
        facets=("concept", "quantity", "formula", "law", "experiment", "phenomenon", "model"),
        default_facet="concept",
        non_node_patterns=(r"练习", r"活动", r"project"),
        canonical_title_rules={},
        default_edge_type="related",
    ),
    "history": SubjectProfile(
        subject_id="history",
        root_title="历史",
        aliases=("历史", "history"),
        strong_markers=("历史", "dynasty", "war", "revolution", "empire"),
        weak_markers=("朝代", "事件", "人物", "改革", "战争", "年代"),
        facets=("event", "concept", "person", "cause_effect", "general"),
        default_facet="general",
        non_node_patterns=(r"练习", r"活动", r"project"),
        canonical_title_rules={},
        default_edge_type="related",
    ),
    "geography": SubjectProfile(
        subject_id="geography",
        root_title="地理",
        aliases=("地理", "geography"),
        strong_markers=("地理", "map", "latitude", "longitude", "climate", "region"),
        weak_markers=("地图", "气候", "地形", "区域", "经纬度", "人口"),
        facets=("concept", "place", "cause_effect", "map_skill", "general"),
        default_facet="general",
        non_node_patterns=(r"练习", r"活动", r"project"),
        canonical_title_rules={},
        default_edge_type="related",
    ),
    "general": SubjectProfile(
        subject_id="general",
        root_title="通用",
        aliases=(),
        strong_markers=(),
        weak_markers=(),
        facets=("general",),
        default_facet="general",
        non_node_patterns=(),
        canonical_title_rules={},
        default_edge_type="requires",
    ),
}


@dataclass
class CandidateKind:
    subject: str
    facet: str
    include: bool
    title_hint: str | None = None
    filter_reason: str = ""


@dataclass
class CandidateTopic:
    segment_index: int
    raw_title: str
    normalized_title: str
    subject: str
    language_id: str | None
    facet: str
    confidence: float
    reason: str
    text: str
    edge_type: str
    proposed_parent_node_ids: list[str]


@dataclass
class CandidateCluster:
    title: str
    subject: str
    language_id: str | None
    facet: str
    edge_type: str
    parent_node_ids: list[str]
    candidates: list[CandidateTopic]


def detect_resource_subject(
    *,
    record: ResourceRecord,
    segments: list[ResourceSegment],
    topics: list[TopicNode],
    default_topic_id: str | None = None,
    backend: "SessionBackend" | None = None,
) -> str:
    topic_map = {topic.topic_id: topic for topic in topics}
    resource_name = (record.resource_name or "").lower()
    filename = (record.original_filename or "").lower()
    text = "\n".join(
        filter(
            None,
            [
                record.resource_name,
                record.original_filename,
                *(segment.proposed_topic_title or "" for segment in segments),
                *(segment.text or "" for segment in segments[:12]),
            ],
        )
    ).lower()

    scores = {
        profile_id: _subject_evidence_score(profile=profile, resource_name=resource_name, filename=filename, text=text)
        for profile_id, profile in SUBJECT_PROFILES.items()
        if profile_id != "general"
    }
    best_subject, best_score = max(scores.items(), key=lambda item: (item[1], _subject_priority(item[0])))
    if best_score >= 4:
        return best_subject

    for topic_id in filter(None, [record.topic_id, default_topic_id]):
        topic = topic_map.get(topic_id)
        if topic is None:
            continue
        topic_subject = _infer_topic_subject(topic)
        if topic_subject != "general":
            return topic_subject

    if backend is not None and backend.llm_skill.client.api_key:
        try:
            sample = text[:800]
            subject_list = ", ".join(sorted(k for k in SUBJECT_PROFILES if k != "general"))
            response = backend.llm_skill.client.chat.completions.create(
                model=backend.llm_skill.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"你是学科分类助手。给定文档名和片段，判断最匹配的学科：{subject_list}。"
                            "只返回学科 key，例如 'math'。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"文档名: {record.resource_name}\n片段: {sample}",
                    },
                ],
                temperature=0.1,
                timeout=30.0,
            )
            llm = (response.choices[0].message.content or "").strip().lower()
            if llm in SUBJECT_PROFILES and llm != "general":
                return llm
        except Exception:
            pass

    return "general"


def normalize_candidate_title(title: str, *, subject: str, facet: str, text: str = "") -> str | None:
    profile = SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"])
    raw_title = _clean_title(title)
    full_text = f"{raw_title}\n{text}".lower()
    if not raw_title:
        return None

    if subject == "language":
        return _normalize_language_candidate_title(raw_title, facet=facet, full_text=full_text, language_id=_detect_language_id(raw_title, full_text))

    specialized = _normalize_profile_candidate_title(raw_title, facet=facet, full_text=full_text, profile=profile)
    if specialized:
        return specialized

    normalized = raw_title
    normalized = re.sub(r"^(如何|怎样|怎么|请你|试着)", "", normalized)
    normalized = re.sub(r"(用英语|练习|训练|核心|学习|知识点|专题|unit\s*\d+)", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("？", "").replace("?", "")
    normalized = normalized.replace("情绪", "心情")
    normalized = normalized.strip("：:，,。.！!；;")
    return normalized or None


def classify_candidate_kind(title: str, text: str, *, subject: str) -> CandidateKind:
    profile = SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"])
    cleaned_title = _clean_title(title)
    lowered = f"{cleaned_title}\n{text}".lower()
    title_lowered = cleaned_title.lower()

    # Reject titles that are still derivation-chains after _clean_title
    # (i.e. _clean_title didn't strip them because the arrow chars weren't decoded)
    # Use unicode escapes to avoid encoding issues in the source file
    _derivation_re = re.compile(
        r"[\u21d2\u21d4\u2192\u2190\u2194]"  # ⇒⇔→←↔
        r"|\u63a8\u51fa.+"                    # 推出...
        r"|(\u4e0e|\u548c).+\u7684\u7b49\u4ef7\u6027"  # 与/和...的等价性
    )
    if _derivation_re.search(cleaned_title):
        return CandidateKind(subject=subject, facet=profile.default_facet, include=False, filter_reason="derivation-chain, not a standalone topic")

    if subject == "language":
        if _is_story_title_only(cleaned_title, lowered):
            return CandidateKind(subject=subject, facet="reading", include=True, title_hint=_language_reading_title(lowered))
        if _is_language_grammar(lowered):
            return CandidateKind(subject=subject, facet="grammar", include=True)
        if _is_language_pronunciation(lowered):
            return CandidateKind(subject=subject, facet="pronunciation", include=True)
        if _is_language_writing(lowered):
            return CandidateKind(subject=subject, facet="writing", include=True)
        if _is_language_functional_expression(lowered):
            return CandidateKind(subject=subject, facet="functional_expression", include=True)
        if _is_language_vocabulary(lowered):
            return CandidateKind(subject=subject, facet="vocabulary", include=True)
        if _is_language_reading(lowered):
            return CandidateKind(subject=subject, facet="reading", include=True, title_hint=_language_reading_title(lowered))
        if re.search(r"\b(unit\s*\d+|lesson\s*\d+)\b", title_lowered):
            return CandidateKind(subject=subject, facet="unit", include=False, filter_reason="unit wrapper candidate")
        if _is_activity_dominant_language_candidate(title=title_lowered, text=lowered, profile=profile):
            return CandidateKind(subject=subject, facet="activity", include=False, filter_reason="activity-like candidate")
        return CandidateKind(subject=subject, facet="culture", include=True)

    if _is_non_node_candidate(title_lowered, lowered, profile=profile):
        return CandidateKind(subject=subject, facet=profile.default_facet, include=False, filter_reason="activity-like candidate")
    return CandidateKind(subject=subject, facet=_classify_profile_facet(lowered, profile=profile), include=True)


def cluster_candidate_topics(candidates: list[CandidateTopic]) -> list[CandidateCluster]:
    buckets: dict[tuple[str, str | None, str, str], list[CandidateTopic]] = {}
    for candidate in candidates:
        key = (candidate.subject, candidate.language_id, candidate.facet, candidate.normalized_title)
        buckets.setdefault(key, []).append(candidate)

    clusters: list[CandidateCluster] = []
    for (subject, language_id, facet, normalized_title), items in buckets.items():
        edge_type = _pick_edge_type(items, subject=subject)
        ordered = sorted(items, key=lambda item: (-item.confidence, item.segment_index))
        all_parents = []
        for item in ordered:
            for pid in item.proposed_parent_node_ids:
                if pid not in all_parents:
                    all_parents.append(pid)
        clusters.append(
            CandidateCluster(
                title=normalized_title,
                subject=subject,
                language_id=language_id,
                facet=facet,
                edge_type=edge_type,
                parent_node_ids=all_parents,
                candidates=ordered,
            )
        )
    clusters.sort(key=lambda cluster: (-len(cluster.candidates), -cluster.candidates[0].confidence, cluster.title))
    return clusters


def _deduplicate_clusters_within_batch(
    *,
    backend: "SessionBackend",
    clusters: list[CandidateCluster],
    subject: str,
    language_id: str | None,
) -> list[CandidateCluster]:
    if len(clusters) <= 1:
        return clusters

    unique_titles: list[str] = []
    for cluster in clusters:
        if cluster.title not in unique_titles:
            unique_titles.append(cluster.title)

    if len(unique_titles) <= 1:
        return clusters

    title_list = json.dumps(unique_titles, ensure_ascii=False)
    system = (
        "你是语义消歧专家。给定一组知识节点标题，判断哪些标题本质是同一概念（仅表述不同）。\n"
        "对每组等价标题，保留最规范的那个，合并其余到该标题下。\n"
        '只返回 JSON 数组: [{"keep":"保留的规范标题","merge":["待合并标题1","待合并标题2"]}]。\n'
        "不需要合并的标题不返回。"
    )
    user = (
        f"学科: {subject}\n"
        f"节点标题列表:\n{title_list}\n\n"
        "请输出需要合并的等价标题组。"
    )

    merge_groups: list[dict] = []
    try:
        client = backend.llm_skill.client
        model = backend.llm_skill.model_name
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            timeout=60.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        if isinstance(data, list):
            merge_groups = data
    except Exception:
        return clusters  # On LLM failure, return unchanged

    merge_map: dict[str, str] = {}
    for group in merge_groups:
        if not isinstance(group, dict):
            continue
        keep = str(group.get("keep", "")).strip()
        merge_list = group.get("merge", [])
        if not keep or not isinstance(merge_list, list):
            continue
        for m in merge_list:
            if isinstance(m, str) and m.strip() and m.strip() != keep:
                merge_map[m.strip()] = keep

    if not merge_map:
        return clusters

    title_to_cluster: dict[str, CandidateCluster] = {c.title: c for c in clusters}
    titles_merged: set[str] = set()
    merged: list[CandidateCluster] = []
    for cluster in clusters:
        target = merge_map.get(cluster.title)
        if target is None:
            if cluster.title not in titles_merged:
                merged.append(cluster)
        else:
            if cluster.title in titles_merged:
                continue
            titles_merged.add(cluster.title)
            keeper = title_to_cluster.get(target)
            if keeper is not None:
                keeper.candidates.extend(cluster.candidates)
                for pid in cluster.parent_node_ids:
                    if pid not in keeper.parent_node_ids:
                        keeper.parent_node_ids.append(pid)
                if target not in titles_merged:
                    titles_merged.add(target)
                    merged.append(keeper)
            else:
                merged.append(cluster)

    merged.sort(key=lambda c: (-len(c.candidates), -c.candidates[0].confidence, c.title))
    return merged


def create_resource_level_proposals(
    *,
    backend: "SessionBackend",
    record: ResourceRecord,
    segments: list[ResourceSegment],
    topics: list[TopicNode],
    default_topic_id: str | None = None,
) -> list[GraphProposalRecord]:
    subject = detect_resource_subject(record=record, segments=segments, topics=topics, default_topic_id=default_topic_id, backend=backend)
    profile = SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"])
    language_id = _detect_language_id(record.resource_name, "\n".join(filter(None, [record.original_filename, *(segment.text or "" for segment in segments)]))) if subject == "language" else None
    candidate_topics: list[CandidateTopic] = []
    state = backend.load_app_state(include_history=False)
    topic_map, proposal_map = _build_existing_match_maps(topics=topics, proposals=state.learning.graph_proposals)

    for index, segment in enumerate(segments):
        if segment.decision != "propose" or not segment.proposed_topic_title:
            continue
        kind = classify_candidate_kind(segment.proposed_topic_title, segment.text or "", subject=subject)
        if not kind.include:
            segment.status = "unclassified"
            segment.decision = "unclassified"
            segment.proposal_id = None
            segment.reason = (kind.filter_reason or segment.reason or "candidate filtered")[:80]
            continue

        normalized_title = normalize_candidate_title(
            kind.title_hint or segment.proposed_topic_title,
            subject=subject,
            facet=kind.facet,
            text=segment.text or "",
        )
        if not normalized_title:
            segment.status = "unclassified"
            segment.decision = "unclassified"
            segment.proposal_id = None
            segment.reason = "candidate normalization failed"
            continue

        candidate_topics.append(
            CandidateTopic(
                segment_index=index,
                raw_title=segment.proposed_topic_title,
                normalized_title=normalized_title,
                subject=subject,
                language_id=language_id,
                facet=kind.facet,
                confidence=segment.confidence,
                reason=segment.reason,
                text=segment.text or "",
                edge_type=profile.default_edge_type,
                proposed_parent_node_ids=segment.proposed_parent_node_ids,
            )
        )

    clusters = cluster_candidate_topics(candidate_topics)
    if not clusters:
        return []

    if len(clusters) > 1 and backend.llm_skill.client.api_key:
        try:
            clusters = _deduplicate_clusters_within_batch(
                backend=backend, clusters=clusters,
                subject=subject, language_id=language_id,
            )
        except Exception:
            pass

    parent_node_ids = _select_parent_node_ids(subject=subject, topics=topics, default_topic_id=default_topic_id, language_id=language_id)
    proposals: list[GraphProposalRecord] = []
    pending_parent_proposal_ids: list[str] = []
    needs_new_content_proposal = any(
        _resolve_existing_topic(topic_map, subject=cluster.subject, language_id=cluster.language_id, facet=cluster.facet, normalized_title=cluster.title) is None
        and _resolve_existing_proposal(proposal_map, subject=cluster.subject, language_id=cluster.language_id, facet=cluster.facet, normalized_title=cluster.title) is None
        for cluster in clusters
    )

    if subject != "general" and needs_new_content_proposal and not parent_node_ids:
        existing_root_proposal = _select_pending_root_proposal(
            proposals=state.learning.graph_proposals,
            subject=subject,
            language_id=language_id,
        )
        if existing_root_proposal is not None:
            pending_parent_proposal_ids = [existing_root_proposal.proposal_id]

    if (
        subject != "general"
        and needs_new_content_proposal
        and not parent_node_ids
        and not pending_parent_proposal_ids
        and _should_create_subject_root(subject=subject, topics=topics, backend=backend, language_id=language_id)
    ):
        root_title = _root_title_for_subject(subject=subject, language_id=language_id)
        root_proposal = backend.create_graph_proposal_from_resource(
            title=root_title,
            summary=f"facet: root；支撑片段 {len(candidate_topics)} 个；代表片段：{_representative_snippets([item.text for item in candidate_topics])}",
            tags=_proposal_tags(subject=subject, facet="root", language_id=language_id),
            parent_node_ids=[],
            edge_type="related",
            reason=f"resource batch root proposal; facet=root; segments={len(candidate_topics)}",
        )
        proposals.append(root_proposal)
        pending_parent_proposal_ids = [root_proposal.proposal_id]

    for cluster in clusters:
        existing_topic = _resolve_existing_topic(
            topic_map,
            subject=cluster.subject,
            language_id=cluster.language_id,
            facet=cluster.facet,
            normalized_title=cluster.title,
        )
        if existing_topic is not None:
            for candidate in cluster.candidates:
                _link_segment_to_existing_topic(segments[candidate.segment_index], topic_id=existing_topic.topic_id)
            continue

        existing_proposal = _resolve_existing_proposal(
            proposal_map,
            subject=cluster.subject,
            language_id=cluster.language_id,
            facet=cluster.facet,
            normalized_title=cluster.title,
        )
        if existing_proposal is not None:
            for candidate in cluster.candidates:
                _attach_segment_to_existing_proposal(
                    segments[candidate.segment_index],
                    proposal_id=existing_proposal.proposal_id,
                    proposal_title=existing_proposal.title,
                )
            continue

        cluster_summary = _build_cluster_summary(cluster)
        cluster_reason = f"resource batch cluster; facet={cluster.facet}; segments={len(cluster.candidates)}"

        # Validate LLM-proposed parent IDs: keep only same-subject compatible parents
        valid_parent_ids: list[str] = []
        if cluster.parent_node_ids:
            topic_lookup = {topic.topic_id: topic for topic in topics}
            for pid in cluster.parent_node_ids:
                parent_topic = topic_lookup.get(pid)
                if parent_topic is None:
                    continue
                parent_subject = _infer_topic_subject(parent_topic)
                if parent_subject != subject:
                    continue
                if not _is_root_like_topic(parent_topic, subject):
                    continue
                valid_parent_ids.append(pid)

        cluster_parents = list(dict.fromkeys(valid_parent_ids)) if valid_parent_ids else parent_node_ids

        cluster_prereq_ids: list[str] = []
        if (
            existing_topic is None
            and existing_proposal is None
            and cluster.subject != "general"
            and backend.llm_skill.client.api_key
        ):
            try:
                from src.services.graph_search import GraphSearchAgent

                search_agent = GraphSearchAgent(backend, cluster.subject, cluster.language_id)
                prereq_results = search_agent.infer_prerequisites(
                    concept_title=cluster.title,
                    concept_text=_representative_snippets([c.text for c in cluster.candidates]),
                    max_depth=2,
                )
                missing_prereq_proposals: list[GraphProposalRecord] = []
                created_prereq_titles: set[str] = set()
                for r in prereq_results:
                    if r.get("topic_id"):
                        cluster_prereq_ids.append(r["topic_id"])
                    elif r.get("title"):
                        prereq_title = str(r["title"]).strip()
                        if not prereq_title or prereq_title in created_prereq_titles:
                            continue
                        created_prereq_titles.add(prereq_title)
                        prereq_facet = profile.default_facet
                        prereq_norm = normalize_candidate_title(
                            prereq_title, subject=cluster.subject,
                            facet=prereq_facet, text="",
                        )
                        if not prereq_norm:
                            continue
                        existing_t = _resolve_existing_topic(
                            topic_map,
                            subject=cluster.subject, language_id=cluster.language_id,
                            facet=prereq_facet, normalized_title=prereq_norm,
                        )
                        if existing_t is not None:
                            cluster_prereq_ids.append(existing_t.topic_id)
                            continue
                        existing_p = _resolve_existing_proposal(
                            proposal_map,
                            subject=cluster.subject, language_id=cluster.language_id,
                            facet=prereq_facet, normalized_title=prereq_norm,
                        )
                        if existing_p is not None:
                            cluster_prereq_ids.append(existing_p.proposal_id)
                            continue
                        prereq_proposal = backend.create_graph_proposal_from_resource(
                            title=prereq_title,
                            summary=f"前置知识节点：{cluster.title} 的前置依赖",
                            tags=_proposal_tags(
                                subject=cluster.subject, facet=prereq_facet,
                                language_id=language_id,
                            ),
                            parent_node_ids=[],
                            prerequisite_node_ids=[],
                            pending_parent_proposal_ids=list(pending_parent_proposal_ids),
                            edge_type="requires",
                            reason=f"prerequisite of {cluster.title}",
                        )
                        missing_prereq_proposals.append(prereq_proposal)
                        cluster_prereq_ids.append(prereq_proposal.proposal_id)
                proposals.extend(missing_prereq_proposals)
            except Exception:
                cluster_prereq_ids = []

        has_subject_parent = subject != "general" and (bool(cluster_parents) or bool(pending_parent_proposal_ids))
        proposal = backend.create_graph_proposal_from_resource(
            title=cluster.title,
            summary=cluster_summary,
            tags=_proposal_tags(subject=cluster.subject, facet=cluster.facet, language_id=language_id),
            parent_node_ids=cluster_parents,
            prerequisite_node_ids=cluster_prereq_ids,
            pending_parent_proposal_ids=pending_parent_proposal_ids if subject != "general" and not cluster_parents else [],
            edge_type="part_of" if has_subject_parent else cluster.edge_type,
            reason=cluster_reason,
        )
        proposals.append(proposal)
        for candidate in cluster.candidates:
            _attach_segment_to_existing_proposal(
                segments[candidate.segment_index],
                proposal_id=proposal.proposal_id,
                proposal_title=cluster.title,
            )

    proposed_indexes = {candidate.segment_index for cluster in clusters for candidate in cluster.candidates}
    for index, segment in enumerate(segments):
        if segment.decision == "propose" and index not in proposed_indexes:
            segment.status = "unclassified"
            segment.decision = "unclassified"
            segment.proposal_id = None

    return proposals


def deduplicate_candidate_title(
    *,
    backend: "SessionBackend",
    candidate_title: str,
    candidate_subject: str,
    candidate_facet: str,
    candidate_text: str,
    candidate_language_id: str | None = None,
    existing_nodes: list[dict],
) -> str | None:
    if not candidate_title or not existing_nodes:
        return None

    coarse: list[dict] = []
    for node in existing_nodes:
        node_subject = node.get("subject") or _subject_from_tags(node.get("tags", [])) or "general"
        if node_subject != candidate_subject and node_subject != "general":
            continue
        if candidate_subject == "language" and candidate_language_id:
            node_lang = node.get("language_id")
            if node_lang is not None and node_lang != candidate_language_id:
                continue
        coarse.append(node)

    if not coarse:
        return None

    candidate_list = json.dumps(
        [
            {
                "topic_id": node.get("topic_id", ""),
                "title": node.get("title", ""),
            }
            for node in coarse
        ],
        ensure_ascii=False,
    )

    system = (
        "你是语义消歧专家。比较候选概念与已有知识节点的标题，判断它们是否本质相同。\n"
        "概念本质相同指：同一学术概念的不同叫法、不同语言或简繁表述（如「现在进行时」与「Present Continuous」）。\n"
        "以下情况判定为不同概念：概念包含不同知识维度、明显不同的学术范畴、粒度差异显著（如「实数完备性定理」vs「实数完备性的证明方法」）。\n"
        "仅返回 JSON。"
    )
    user = (
        f"候选概念标题: {candidate_title[:120]}\n"
        f"候选概念描述: {candidate_text[:500]}\n"
        f"候选学科: {candidate_subject}\n"
        f"已有节点列表:\n{candidate_list}\n\n"
        '如果候选概念与已有节点本质相同，返回 {"matched_topic_id": "xxx"}。'
        '如果不同，返回 {"matched_topic_id": null}。'
    )

    try:
        client = backend.llm_skill.client
        model = backend.llm_skill.model_name
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            timeout=60.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        matched = data.get("matched_topic_id") if isinstance(data, dict) else None
        if isinstance(matched, str) and matched:
            node_ids = {node.get("topic_id") for node in coarse}
            if matched in node_ids:
                return matched
        return None
    except Exception:
        return None


def _build_cluster_summary(cluster: CandidateCluster) -> str:
    snippets = _representative_snippets([candidate.text for candidate in cluster.candidates])
    return f"facet: {cluster.facet}；支撑片段 {len(cluster.candidates)} 个；代表片段：{snippets}"


def _representative_snippets(texts: list[str]) -> str:
    snippets: list[str] = []
    for text in texts:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            continue
        snippet = cleaned[:36]
        if snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= 3:
            break
    return " / ".join(snippets)[:160] or "无"


def _clean_title(title: str) -> str:
    cleaned = re.sub(r'[《》“”‘’"\']', "", title or "")
    # Remove common question words and descriptive suffixes
    cleaned = re.sub(r"^(什么是|关于|浅析|探究|理解|掌握|学习)", "", cleaned)
    cleaned = re.sub(r"(是什么|及其应用|的应用|的证明|的推导|的意义|的概念|简介|概述)$", "", cleaned)
    # Strip derivation-chain tails: "A⇒B" -> "A"; "A推出B" -> "A"
    cleaned = re.sub(r"[\u21d2\u21d4\u2192\u2190\u2194].+$", "", cleaned)
    cleaned = re.sub(r"\u63a8\u51fa.+$", "", cleaned)
    # Strip conjunction-equivalence tails only when "的" precedes the suffix:
    # "A与B的等价性" -> "A", but "实数完备性六大定理等价性" stays as-is
    cleaned = re.sub(r"(\u4e0e|\u548c)[^\s]{2,}?\u7684(\u7b49\u4ef7\u6027|\u8054\u7cfb|\u5173\u7cfb)$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:120]


def _normalize_language_candidate_title(title: str, *, facet: str, full_text: str, language_id: str | None) -> str | None:
    if facet == "grammar":
        if re.search(r"\b(present continuous|be\s+doing)\b", full_text):
            return "现在进行时"
        if re.search(r"\b(simple past)\b", full_text):
            return "一般过去时"
        if re.search(r"\b(simple present)\b", full_text):
            return "一般现在时"
        if "现在进行时" in full_text:
            return "现在进行时"
        if "一般过去时" in full_text:
            return "一般过去时"
        if "一般现在时" in full_text:
            return "一般现在时"
        if "情态动词" in full_text or re.search(r"\b(must|should|can|may)\b", full_text):
            if "规则" in full_text or re.search(r"\b(must|mustn't|should|shouldn't)\b", full_text):
                return "情态动词表达规则"
            return "情态动词"
        if "可数名词" in full_text or "不可数名词" in full_text:
            return "可数名词与不可数名词"
        if "物主代词" in full_text:
            return "物主代词"
        return title

    if facet == "vocabulary":
        if "天气" in full_text or re.search(r"\b(sunny|rainy|cloudy|windy|weather)\b", full_text):
            return "天气词汇与天气表达"
        if "动物" in full_text or re.search(r"\b(tiger|lion|elephant|animal|animals)\b", full_text):
            return "动物词汇与描述动物"
        if "食物" in full_text or re.search(r"\b(food|rice|bread|apple|milk)\b", full_text):
            return "食物词汇"
        if "规则" in full_text:
            return "规则词汇与表达"
        return re.sub(r"(英语|词汇|单词|核心)", "", title).strip() or title

    if facet == "pronunciation":
        if "元音" in full_text:
            return "元音组合发音"
        if "辅音" in full_text:
            return "辅音组合发音"
        if "重音" in full_text:
            return "英语单词重音"
        return "英语发音规律"

    if facet == "functional_expression":
        if "打电话" in full_text or re.search(r"\b(phone|call|calling)\b", full_text):
            return "电话用语"
        if "天气" in full_text:
            return "谈论天气"
        if "喜好" in full_text or re.search(r"\b(like|love|favorite)\b", full_text):
            return "表达喜好"
        if "规则" in full_text:
            return "规则表达"
        if "频率" in full_text or re.search(r"\b(always|usually|often|sometimes|never)\b", full_text):
            return "频率表达"
        if "归属" in full_text or re.search(r"\b(mine|yours|his|hers|ours|theirs)\b", full_text):
            return "物品归属表达"
        return re.sub(r"^(如何|怎样|怎么)", "", title).strip("？?") or title

    if facet == "reading":
        return _language_reading_title(full_text, language_id=language_id)

    if facet == "writing":
        if language_id == "chinese":
            return "语文写作"
        if "日记" in full_text:
            return "英语日记写作"
        if "经历" in full_text:
            return "描述经历写作"
        if "续写" in full_text or "故事" in full_text:
            return "英语故事续写"
        return "英语写作"

    if facet == "culture":
        normalized = re.sub(r"^(如何|怎样|怎么)", "", title).strip("？?")
        normalized = normalized.replace("情绪", "心情")
        return normalized or None

    return title


def _normalize_profile_candidate_title(title: str, *, facet: str, full_text: str, profile: SubjectProfile) -> str | None:
    # First apply subject-specific heuristic cleanup to the title itself
    if profile.subject_id == "math":
        title = re.sub(r"(定理|公理|推论|法则|定律|公式)证明.*", r"\1", title)
        title = re.sub(r"的?(完备性|连续性|介值性|有界性).*", r"\1", title)
        title = title.split("：")[0].split(":")[0].split("_")[0]

    for pattern, replacement in profile.canonical_title_rules.get(facet, ()):
        if re.search(pattern, full_text):
            return replacement
    if profile.subject_id == "math":
        if facet == "operation":
            if "加法" in full_text or "addition" in full_text:
                return "加法"
            if "乘法" in full_text or "multiplication" in full_text:
                return "乘法"
    if profile.subject_id in {"science", "physics", "chemistry", "biology"}:
        if facet == "formula" and ("velocity" in full_text or "速度" in full_text):
            return "速度公式"
        if profile.subject_id == "biology" and ("cell" in full_text or "细胞" in full_text):
            return "细胞结构与功能"
    if profile.subject_id == "geography" and ("地图" in full_text or "map" in full_text):
        return "地图技能"
    return title


def _is_language_grammar(text: str) -> bool:
    markers = ("现在进行时", "一般过去时", "一般现在时", "情态动词", "物主代词", "可数名词", "不可数名词")
    return any(marker in text for marker in markers) or bool(re.search(r"\b(be\s+going\s+to|present continuous|simple past)\b", text))


def _is_language_vocabulary(text: str) -> bool:
    markers = ("词汇", "单词", "vocabulary", "动物词汇", "食物词汇", "天气词汇", "规则词汇", "颜色词汇", "家庭词汇")
    if any(marker in text for marker in markers):
        return True
    return bool(
        re.search(r"\b(sunny|rainy|cloudy|windy|weather|tiger|lion|elephant|giraffe|animal|animals|food|rice|bread|apple|milk)\b", text)
    )


def _is_language_pronunciation(text: str) -> bool:
    markers = ("音标", "自然拼读", "发音", "元音", "辅音", "重音", "弱读")
    return any(marker in text for marker in markers)


def _is_language_functional_expression(text: str) -> bool:
    markers = ("打电话", "点餐", "谈论天气", "表达喜好", "谈论规则", "频率", "归属")
    return any(marker in text for marker in markers) or bool(re.search(r"\b(phone|order food|weather|favorite|rules)\b", text))


def _is_language_reading(text: str) -> bool:
    markers = ("阅读理解", "课文", "语篇", "故事", "短文", "passage", "story")
    return any(marker in text for marker in markers)


def _is_language_writing(text: str) -> bool:
    markers = ("写作", "日记", "续写", "描述经历", "作文")
    return any(marker in text for marker in markers)


def _is_story_like(text: str) -> bool:
    return any(marker in text for marker in ("故事", "story", "皇帝的新装", "渔夫和金鱼"))


def _is_story_title_only(title: str, text: str) -> bool:
    if not _is_story_like(text):
        return False
    stripped = re.sub(r"(阅读理解|故事|story|passage|课文)", "", title.lower())
    return len(stripped.strip()) <= 10


def _pick_edge_type(candidates: list[CandidateTopic], *, subject: str) -> str:
    profile = SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"])
    facet = candidates[0].facet if candidates else profile.default_facet
    if facet in {"formula", "quantity", "theorem_or_rule"}:
        return "defines"
    if facet == "experiment":
        return "evidence_for"
    if facet in {"phenomenon", "model", "reading", "writing", "culture"}:
        return "explains"
    if facet == "cause_effect":
        return "causes"
    if facet in {"method", "application", "functional_expression"}:
        return "uses"
    if facet in {"operation", "grammar", "vocabulary", "pronunciation", "concept", "event", "person", "place", "map_skill"}:
        return "part_of"
    if subject in {"math", "science", "physics", "chemistry", "biology"}:
        return "requires" if any("公式" in candidate.text or "定律" in candidate.text for candidate in candidates) else "related"
    return profile.default_edge_type


def _infer_topic_subject(topic: TopicNode) -> str:
    for tag in topic.tags:
        if tag.startswith("subject:"):
            return _canonical_subject(tag.split(":", 1)[1])
    title = topic.title.lower()
    for profile in SUBJECT_PROFILES.values():
        if profile.subject_id == "general":
            continue
        if title == profile.root_title.lower() or any(alias in title for alias in profile.aliases):
            return profile.subject_id
    return "general"


def _select_parent_node_ids(*, subject: str, topics: list[TopicNode], default_topic_id: str | None, language_id: str | None = None) -> list[str]:
    compatible = [
        topic
        for topic in topics
        if _infer_topic_subject(topic) == subject
        and _is_root_like_topic(topic, subject)
        and _language_root_matches(getattr(topic, "tags", []), topic.title, subject=subject, language_id=language_id)
    ]
    if compatible:
        compatible.sort(key=lambda topic: _root_topic_score(topic, subject=subject, language_id=language_id), reverse=True)
        return [compatible[0].topic_id]

    if default_topic_id:
        default_topic = next((topic for topic in topics if topic.topic_id == default_topic_id), None)
        if (
            default_topic is not None
            and _infer_topic_subject(default_topic) == subject
            and _is_root_like_topic(default_topic, subject)
            and _language_root_matches(getattr(default_topic, "tags", []), default_topic.title, subject=subject, language_id=language_id)
        ):
            return [default_topic_id]
    return []


def _is_root_like_topic(topic: TopicNode, subject: str) -> bool:
    title = topic.title.strip().lower()
    subject_label = SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"]).root_title.lower()
    if title == subject_label:
        return True
    return any(tag in ROOT_MARKER_TAGS for tag in topic.tags)


def _should_create_subject_root(*, subject: str, topics: list[TopicNode], backend: "SessionBackend", language_id: str | None = None) -> bool:
    if any(
        _infer_topic_subject(topic) == subject
        and _is_root_like_topic(topic, subject)
        and _language_root_matches(getattr(topic, "tags", []), topic.title, subject=subject, language_id=language_id)
        for topic in topics
    ):
        return False
    state = backend.load_app_state(include_history=False)
    for proposal in state.learning.graph_proposals:
        if proposal.status in {"rejected"}:
            continue
        if _is_root_like_proposal(proposal, subject=subject, language_id=language_id):
            return False
    return True


def _select_pending_root_proposal(
    *,
    proposals: list[GraphProposalRecord],
    subject: str,
    language_id: str | None,
) -> GraphProposalRecord | None:
    reusable_statuses = {"proposed", "validated", "shadow"}
    for proposal in proposals:
        if proposal.status not in reusable_statuses:
            continue
        if _is_root_like_proposal(proposal, subject=subject, language_id=language_id):
            return proposal
    return None


def _is_root_like_proposal(proposal: GraphProposalRecord, *, subject: str, language_id: str | None = None) -> bool:
    title = proposal.title.strip().lower()
    subject_label = _root_title_for_subject(subject=subject, language_id=language_id).lower()
    tags = getattr(proposal, "tags", [])
    if title == subject_label and _subject_from_tags(tags) == subject:
        return True
    return (
        any(tag in ROOT_MARKER_TAGS for tag in tags)
        and _subject_from_tags(tags) == subject
        and _language_root_matches(tags, proposal.title, subject=subject, language_id=language_id)
    )


def _is_activity_dominant_language_candidate(*, title: str, text: str, profile: SubjectProfile) -> bool:
    has_activity_title = any(marker in title for marker in ENGLISH_ACTIVITY_TITLE_MARKERS)
    if re.search(r"(设计|制定|制作|画).*(动物园|地图|海报|班级规则)", title):
        has_activity_title = True
    if re.search(r"^(如何|怎样|怎么).*(设计|制定|制作|画)", title):
        has_activity_title = True
    if not has_activity_title and any(marker in text for marker in ENGLISH_ACTIVITY_MARKERS):
        has_activity_title = any(token in title for token in ("activity", "project", "role", "design", "规则", "动物园", "地图", "海报"))
    if not has_activity_title:
        return False
    return not _has_language_substantive_markers(text)


def _has_language_substantive_markers(text: str) -> bool:
    return any(
        checker(text)
        for checker in (
            _is_language_grammar,
            _is_language_pronunciation,
            _is_language_functional_expression,
            _is_language_vocabulary,
            _is_language_reading,
            _is_language_writing,
        )
    )


def _build_existing_match_maps(
    *,
    topics: list[TopicNode],
    proposals: list[GraphProposalRecord],
) -> tuple[dict[tuple[str, str | None, str, str], TopicNode], dict[tuple[str, str | None, str, str], GraphProposalRecord]]:
    topic_map: dict[tuple[str, str | None, str, str], TopicNode] = {}
    for topic in topics:
        key = _topic_match_key(topic)
        if key is None:
            continue
        topic_map.setdefault(key, topic)

    proposal_map: dict[tuple[str, str | None, str, str], GraphProposalRecord] = {}
    reusable_statuses = {"proposed", "validated", "shadow", "active"}
    for proposal in proposals:
        if proposal.status not in reusable_statuses:
            continue
        key = _proposal_match_key(proposal)
        if key is None:
            continue
        proposal_map.setdefault(key, proposal)
    return topic_map, proposal_map


def _infer_topic_facet(title: str, tags: list[str], *, subject: str) -> str | None:
    facet = _facet_from_tags(tags)
    if facet is not None:
        return facet
    if subject == "language":
        kind = classify_candidate_kind(title, "", subject=subject)
        return kind.facet if kind.include else None
    if subject in {"math", "science", "physics", "chemistry", "biology"}:
        return "concept"
    if subject == "history":
        return "general"
    if subject == "geography":
        return "general"
    if subject == "general":
        return "general"
    return None


def _subject_evidence_score(*, profile: SubjectProfile, resource_name: str, filename: str, text: str) -> int:
    score = 0
    for alias in profile.aliases:
        if alias and (_marker_matches(alias, resource_name) or _marker_matches(alias, filename)):
            score += 6
    for marker in profile.strong_markers:
        if marker and _marker_matches(marker, text):
            score += 4
    score += min(4, sum(1 for marker in profile.weak_markers if marker and _marker_matches(marker, text)))
    return score


def _subject_priority(subject: str) -> int:
    order = {"physics": 8, "chemistry": 7, "biology": 6, "math": 5, "history": 4, "geography": 3, "science": 2, "language": 1, "general": 0}
    return order.get(subject, 0)


def _detect_language_id(*parts: str) -> str | None:
    text = "\n".join(parts).lower()
    best_language: str | None = None
    best_score = 0
    for language_id, markers in LANGUAGE_INSTANCE_MARKERS.items():
        score = sum(1 for marker in markers if marker in text)
        if score > best_score:
            best_language = language_id
            best_score = score
    return best_language


def _marker_matches(marker: str, text: str) -> bool:
    marker = marker.strip().lower()
    haystack = text.lower()
    if not marker or not haystack:
        return False
    if _contains_cjk(marker):
        return marker in haystack
    pattern = r"(?<![a-z0-9])" + re.escape(marker).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _language_reading_title(text: str, language_id: str | None = None) -> str:
    if language_id == "chinese":
        return "语文阅读理解"
    return "英语故事阅读理解" if _is_story_like(text) else "英语阅读理解"


def _classify_profile_facet(text: str, *, profile: SubjectProfile) -> str:
    if profile.subject_id == "math":
        if any(marker in text for marker in ("加法", "减法", "乘法", "除法", "addition", "multiplication")):
            return "operation"
        if any(marker in text for marker in ("公式", "定理", "法则")):
            return "theorem_or_rule"
        if any(marker in text for marker in ("方法", "解题", "步骤")):
            return "method"
        if any(marker in text for marker in ("应用", "实际问题")):
            return "application"
        return "concept"
    if profile.subject_id in {"science", "physics", "chemistry", "biology"}:
        if any(marker in text for marker in ("公式", "formula")):
            return "formula"
        if any(marker in text for marker in ("定律", "law")):
            return "law"
        if any(marker in text for marker in ("实验", "experiment")):
            return "experiment"
        if any(marker in text for marker in ("现象", "phenomenon")):
            return "phenomenon"
        if any(marker in text for marker in ("模型", "model")):
            return "model"
        if any(marker in text for marker in ("速度", "时间", "distance", "speed", "force", "energy", "cell", "细胞")):
            return "quantity"
        return "concept"
    if profile.subject_id == "history":
        if any(marker in text for marker in ("事件", "war", "revolution")):
            return "event"
        if any(marker in text for marker in ("人物", "emperor", "leader")):
            return "person"
        if any(marker in text for marker in ("原因", "影响", "cause", "effect")):
            return "cause_effect"
        return "general"
    if profile.subject_id == "geography":
        if any(marker in text for marker in ("地图", "map", "经纬度", "latitude", "longitude")):
            return "map_skill"
        if any(marker in text for marker in ("地区", "region", "城市", "mountain", "river")):
            return "place"
        if any(marker in text for marker in ("原因", "影响", "climate", "weather")):
            return "cause_effect"
        return "general"
    return profile.default_facet


def _is_non_node_candidate(title: str, text: str, *, profile: SubjectProfile) -> bool:
    has_activity_title = any(re.search(pattern, title) for pattern in profile.non_node_patterns)
    has_activity_text = any(re.search(pattern, text) for pattern in profile.non_node_patterns)
    if not has_activity_title and not has_activity_text:
        return False
    return not _has_profile_substantive_markers(text, profile=profile)


def _proposal_tags(*, subject: str, facet: str, language_id: str | None = None, include_language_tag: bool = True) -> list[str]:
    tags = [f"subject:{subject}", f"facet:{facet}"]
    if include_language_tag and subject == "language" and language_id:
        tags.append(f"language:{language_id}")
    return tags


def _root_topic_score(topic: TopicNode, *, subject: str, language_id: str | None) -> int:
    score = 0
    if topic.title.strip() == SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"]).root_title:
        score += 3
    if "facet:root" in topic.tags:
        score += 2
    if language_id and f"language:{language_id}" in topic.tags:
        score += 2
    return score


def _root_title_for_subject(*, subject: str, language_id: str | None) -> str:
    if subject != "language":
        return SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"]).root_title
    if language_id == "english":
        return "英语"
    if language_id == "chinese":
        return "语文"
    return "语言"


def _topic_match_key(topic: TopicNode) -> tuple[str, str | None, str, str] | None:
    subject = _infer_topic_subject(topic)
    facet = _infer_topic_facet(topic.title, getattr(topic, "tags", []), subject=subject)
    language_id = _language_id_from_tags(getattr(topic, "tags", [])) if subject == "language" else None
    normalized = normalize_candidate_title(topic.title, subject=subject, facet=facet or SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"]).default_facet, text="")
    if not normalized:
        return None
    return (subject, language_id, facet or "general", normalized)


def _proposal_match_key(proposal: GraphProposalRecord) -> tuple[str, str | None, str, str] | None:
    subject = _subject_from_tags(getattr(proposal, "tags", [])) or "general"
    facet = _facet_from_tags(getattr(proposal, "tags", [])) or _infer_topic_facet(proposal.title, getattr(proposal, "tags", []), subject=subject) or "general"
    language_id = _language_id_from_tags(getattr(proposal, "tags", [])) if subject == "language" else None
    normalized = normalize_candidate_title(proposal.title, subject=subject, facet=facet, text="")
    if not normalized:
        return None
    return (subject, language_id, facet, normalized)


def _language_id_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("language:"):
            return tag.split(":", 1)[1]
        if tag == "subject:english":
            return "english"
        if tag in {"subject:chinese", "subject:语文", "subject:中文"}:
            return "chinese"
    return None


def _language_root_matches(tags: list[str], title: str, *, subject: str, language_id: str | None) -> bool:
    if subject != "language":
        return True
    root_language_id = _language_id_from_tags(tags) or _detect_language_id(title)
    if language_id is None:
        return root_language_id is None
    return root_language_id is None or root_language_id == language_id


def _resolve_existing_topic(
    topic_map: dict[tuple[str, str | None, str, str], TopicNode],
    *,
    subject: str,
    language_id: str | None,
    facet: str,
    normalized_title: str,
) -> TopicNode | None:
    if subject != "language":
        return topic_map.get((subject, None, facet, normalized_title))
    if language_id is None:
        return topic_map.get((subject, None, facet, normalized_title))
    return topic_map.get((subject, language_id, facet, normalized_title)) or topic_map.get((subject, None, facet, normalized_title))


def _resolve_existing_proposal(
    proposal_map: dict[tuple[str, str | None, str, str], GraphProposalRecord],
    *,
    subject: str,
    language_id: str | None,
    facet: str,
    normalized_title: str,
) -> GraphProposalRecord | None:
    if subject != "language":
        return proposal_map.get((subject, None, facet, normalized_title))
    if language_id is None:
        return proposal_map.get((subject, None, facet, normalized_title))
    return proposal_map.get((subject, language_id, facet, normalized_title)) or proposal_map.get((subject, None, facet, normalized_title))


def _has_profile_substantive_markers(text: str, *, profile: SubjectProfile) -> bool:
    if profile.subject_id == "language":
        return _has_language_substantive_markers(text)
    if profile.subject_id == "math":
        return any(marker in text for marker in ("加法", "减法", "乘法", "除法", "equation", "geometry", "formula", "概念", "方法"))
    if profile.subject_id in {"science", "physics", "chemistry", "biology"}:
        return any(marker in text for marker in ("公式", "formula", "定律", "law", "实验", "experiment", "速度", "distance", "cell", "细胞", "energy", "force"))
    if profile.subject_id in {"history", "geography"}:
        return any(marker in text for marker in ("事件", "人物", "战争", "地图", "气候", "区域", "经纬度", "原因", "影响"))
    return any(_marker_matches(marker, text) for marker in profile.strong_markers)


def _subject_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("subject:"):
            return _canonical_subject(tag.split(":", 1)[1])
    return None


def _canonical_subject(subject: str) -> str:
    if subject in {"english", "chinese", "语文", "中文"}:
        return "language"
    return subject


def _facet_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("facet:"):
            return tag.split(":", 1)[1]
    return None


def _link_segment_to_existing_topic(segment: ResourceSegment, *, topic_id: str) -> None:
    segment.status = "classified"
    segment.decision = "link"
    segment.topic_id = topic_id
    segment.proposal_id = None
    segment.proposed_topic_title = None
    segment.reason = "matched existing topic via resource curation"
    segment.confidence = max(segment.confidence, 0.75)


def _attach_segment_to_existing_proposal(segment: ResourceSegment, *, proposal_id: str, proposal_title: str) -> None:
    segment.status = "proposed"
    segment.decision = "propose"
    segment.topic_id = None
    segment.proposal_id = proposal_id
    segment.proposed_topic_title = proposal_title
