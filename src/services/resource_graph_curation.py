from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.models import GraphProposalRecord, ResourceRecord, ResourceSegment, TopicNode

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend


SUBJECT_LABELS = {
    "english": "英语",
    "math": "数学",
    "science": "科学",
    "physics": "物理",
    "chemistry": "化学",
    "biology": "生物",
}

ENGLISH_FACETS = {
    "grammar",
    "vocabulary",
    "phonics",
    "function",
    "reading",
    "writing",
    "culture_or_content",
}

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
    facet: str
    confidence: float
    reason: str
    text: str
    edge_type: str


@dataclass
class CandidateCluster:
    title: str
    subject: str
    facet: str
    edge_type: str
    candidates: list[CandidateTopic]


def detect_resource_subject(
    *,
    record: ResourceRecord,
    segments: list[ResourceSegment],
    topics: list[TopicNode],
    default_topic_id: str | None = None,
) -> str:
    topic_map = {topic.topic_id: topic for topic in topics}
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

    english_markers = (
        "英语",
        "english",
        "grammar",
        "vocabulary",
        "phonics",
        "role-play",
        "weather",
        "story",
        "present continuous",
        "一般现在时",
        "一般过去时",
        "现在进行时",
        "情态动词",
        "物主代词",
        "可数名词",
        "不可数名词",
        "阅读理解",
        "写作",
        "打电话",
    )
    if any(marker in text for marker in english_markers):
        return "english"

    math_markers = ("数学", "方程", "函数", "几何", "分数", "加法", "减法", "乘法", "除法")
    if any(marker in text for marker in math_markers):
        return "math"

    science_markers = ("科学", "生物", "物理", "化学", "实验", "细胞", "力", "能量", "公式", "定律")
    if any(marker in text for marker in science_markers):
        return "science"

    for topic_id in filter(None, [record.topic_id, default_topic_id]):
        topic = topic_map.get(topic_id)
        if topic is None:
            continue
        topic_subject = _infer_topic_subject(topic)
        if topic_subject != "general":
            return topic_subject
    return "general"


def normalize_candidate_title(title: str, *, subject: str, facet: str, text: str = "") -> str | None:
    raw_title = _clean_title(title)
    full_text = f"{raw_title}\n{text}".lower()
    if not raw_title:
        return None

    if subject == "english":
        return _normalize_english_candidate_title(raw_title, facet=facet, full_text=full_text)

    normalized = raw_title
    normalized = re.sub(r"^(如何|怎样|怎么|请你|试着)", "", normalized)
    normalized = re.sub(r"(用英语|练习|训练|核心|学习|知识点|专题|unit\s*\d+)", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("？", "").replace("?", "")
    normalized = normalized.replace("情绪", "心情")
    normalized = normalized.strip("：:，,。.！!；;")
    return normalized or None


def classify_candidate_kind(title: str, text: str, *, subject: str) -> CandidateKind:
    cleaned_title = _clean_title(title)
    lowered = f"{cleaned_title}\n{text}".lower()

    if subject == "english":
        if any(marker in lowered for marker in ENGLISH_ACTIVITY_MARKERS):
            return CandidateKind(subject=subject, facet="activity", include=False, filter_reason="activity-like candidate")
        if re.search(r"(设计|制定|制作|画).*(动物园|地图|海报|班级规则)", lowered):
            return CandidateKind(subject=subject, facet="activity", include=False, filter_reason="activity-like candidate")
        if re.search(r"\b(unit\s*\d+|lesson\s*\d+)\b", lowered):
            return CandidateKind(subject=subject, facet="unit", include=False, filter_reason="unit wrapper candidate")
        if re.search(r"\b(fill in|choose|tick|match)\b", lowered) or "练习题" in lowered:
            return CandidateKind(subject=subject, facet="exercise", include=False, filter_reason="exercise fragment")
        if _is_story_title_only(cleaned_title, lowered):
            return CandidateKind(subject=subject, facet="reading", include=True, title_hint="英语故事阅读理解")
        if _is_english_grammar(lowered):
            return CandidateKind(subject=subject, facet="grammar", include=True)
        if _is_english_phonics(lowered):
            return CandidateKind(subject=subject, facet="phonics", include=True)
        if _is_english_writing(lowered):
            return CandidateKind(subject=subject, facet="writing", include=True)
        if _is_english_function(lowered):
            return CandidateKind(subject=subject, facet="function", include=True)
        if _is_english_vocabulary(lowered):
            return CandidateKind(subject=subject, facet="vocabulary", include=True)
        if _is_english_reading(lowered):
            return CandidateKind(subject=subject, facet="reading", include=True, title_hint="英语故事阅读理解")
        return CandidateKind(subject=subject, facet="culture_or_content", include=True)

    if subject == "math":
        return CandidateKind(subject=subject, facet="concept", include=True)
    if subject in {"science", "physics", "chemistry", "biology"}:
        return CandidateKind(subject=subject, facet="concept", include=True)
    return CandidateKind(subject=subject, facet="general", include=True)


def cluster_candidate_topics(candidates: list[CandidateTopic]) -> list[CandidateCluster]:
    buckets: dict[tuple[str, str, str], list[CandidateTopic]] = {}
    for candidate in candidates:
        key = (candidate.subject, candidate.facet, candidate.normalized_title)
        buckets.setdefault(key, []).append(candidate)

    clusters: list[CandidateCluster] = []
    for (subject, facet, normalized_title), items in buckets.items():
        edge_type = _pick_edge_type(items, subject=subject)
        ordered = sorted(items, key=lambda item: (-item.confidence, item.segment_index))
        clusters.append(
            CandidateCluster(
                title=normalized_title,
                subject=subject,
                facet=facet,
                edge_type=edge_type,
                candidates=ordered,
            )
        )
    clusters.sort(key=lambda cluster: (-len(cluster.candidates), -cluster.candidates[0].confidence, cluster.title))
    return clusters


def create_resource_level_proposals(
    *,
    backend: "SessionBackend",
    record: ResourceRecord,
    segments: list[ResourceSegment],
    topics: list[TopicNode],
    default_topic_id: str | None = None,
) -> list[GraphProposalRecord]:
    subject = detect_resource_subject(record=record, segments=segments, topics=topics, default_topic_id=default_topic_id)
    candidate_topics: list[CandidateTopic] = []

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
                facet=kind.facet,
                confidence=segment.confidence,
                reason=segment.reason,
                text=segment.text or "",
                edge_type="related" if subject == "english" else "requires",
            )
        )

    clusters = cluster_candidate_topics(candidate_topics)
    if not clusters:
        return []

    parent_node_ids = _select_parent_node_ids(subject=subject, topics=topics, default_topic_id=default_topic_id)
    proposals: list[GraphProposalRecord] = []

    if subject != "general" and not parent_node_ids and _should_create_subject_root(subject=subject, topics=topics, backend=backend):
        root_title = SUBJECT_LABELS.get(subject, subject.title())
        proposals.append(
            backend.create_graph_proposal_from_resource(
                title=root_title,
                summary=f"facet: root；支撑片段 {len(candidate_topics)} 个；代表片段：{_representative_snippets([item.text for item in candidate_topics])}",
                tags=[f"subject:{subject}", "facet:root"],
                parent_node_ids=[],
                edge_type="related",
                reason=f"resource batch root proposal; facet=root; segments={len(candidate_topics)}",
            )
        )

    for cluster in clusters:
        proposal = backend.create_graph_proposal_from_resource(
            title=cluster.title,
            summary=_build_cluster_summary(cluster),
            tags=[f"subject:{cluster.subject}", f"facet:{cluster.facet}"],
            parent_node_ids=parent_node_ids,
            edge_type=cluster.edge_type,
            reason=f"resource batch cluster; facet={cluster.facet}; segments={len(cluster.candidates)}",
        )
        proposals.append(proposal)
        for candidate in cluster.candidates:
            segment = segments[candidate.segment_index]
            segment.status = "proposed"
            segment.decision = "propose"
            segment.proposal_id = proposal.proposal_id
            segment.proposed_topic_title = cluster.title

    proposed_indexes = {candidate.segment_index for cluster in clusters for candidate in cluster.candidates}
    for index, segment in enumerate(segments):
        if segment.decision == "propose" and index not in proposed_indexes:
            segment.status = "unclassified"
            segment.decision = "unclassified"
            segment.proposal_id = None

    return proposals


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
    cleaned = re.sub(r"[《》\"“”'']", "", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:120]


def _normalize_english_candidate_title(title: str, *, facet: str, full_text: str) -> str | None:
    if facet == "grammar":
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

    if facet == "phonics":
        if "元音" in full_text:
            return "元音组合发音"
        if "辅音" in full_text:
            return "辅音组合发音"
        if "重音" in full_text:
            return "英语单词重音"
        return "英语发音规律"

    if facet == "function":
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
        return "英语故事阅读理解" if _is_story_like(full_text) else "英语阅读理解"

    if facet == "writing":
        if "日记" in full_text:
            return "英语日记写作"
        if "经历" in full_text:
            return "描述经历写作"
        if "续写" in full_text or "故事" in full_text:
            return "英语故事续写"
        return "英语写作"

    if facet == "culture_or_content":
        normalized = re.sub(r"^(如何|怎样|怎么)", "", title).strip("？?")
        normalized = normalized.replace("情绪", "心情")
        return normalized or None

    return title


def _is_english_grammar(text: str) -> bool:
    markers = ("现在进行时", "一般过去时", "一般现在时", "情态动词", "物主代词", "可数名词", "不可数名词")
    return any(marker in text for marker in markers) or bool(re.search(r"\b(be\s+going\s+to|present continuous|simple past)\b", text))


def _is_english_vocabulary(text: str) -> bool:
    markers = ("词汇", "单词", "动物", "食物", "天气", "颜色", "家庭", "规则")
    return any(marker in text for marker in markers)


def _is_english_phonics(text: str) -> bool:
    markers = ("音标", "自然拼读", "发音", "元音", "辅音", "重音", "弱读")
    return any(marker in text for marker in markers)


def _is_english_function(text: str) -> bool:
    markers = ("打电话", "点餐", "谈论天气", "表达喜好", "谈论规则", "频率", "归属")
    return any(marker in text for marker in markers) or bool(re.search(r"\b(phone|order food|weather|favorite|rules)\b", text))


def _is_english_reading(text: str) -> bool:
    markers = ("阅读理解", "课文", "语篇", "故事", "短文", "passage", "story")
    return any(marker in text for marker in markers)


def _is_english_writing(text: str) -> bool:
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
    if subject == "english":
        return "related"
    if subject in {"math", "science", "physics", "chemistry", "biology"}:
        return "requires" if any("公式" in candidate.text or "定律" in candidate.text for candidate in candidates) else "related"
    return "requires"


def _infer_topic_subject(topic: TopicNode) -> str:
    for tag in topic.tags:
        if tag.startswith("subject:"):
            return tag.split(":", 1)[1]
    title = topic.title.lower()
    if "英语" in title or "english" in title:
        return "english"
    if "数学" in title:
        return "math"
    if any(marker in title for marker in ("科学", "物理", "化学", "生物")):
        return "science"
    return "general"


def _select_parent_node_ids(*, subject: str, topics: list[TopicNode], default_topic_id: str | None) -> list[str]:
    compatible = [topic.topic_id for topic in topics if _infer_topic_subject(topic) == subject and _is_root_like_topic(topic, subject)]
    if compatible:
        return compatible[:1]

    if default_topic_id:
        default_topic = next((topic for topic in topics if topic.topic_id == default_topic_id), None)
        if default_topic is not None and (
            _infer_topic_subject(default_topic) == subject or subject in {"general", "math", "science", "physics", "chemistry", "biology"}
        ):
            return [default_topic_id]
    return []


def _is_root_like_topic(topic: TopicNode, subject: str) -> bool:
    title = topic.title.strip().lower()
    subject_label = SUBJECT_LABELS.get(subject, "").lower()
    if title == subject_label:
        return True
    return f"subject:{subject}" in topic.tags and len(topic.prerequisite_ids) == 0


def _should_create_subject_root(*, subject: str, topics: list[TopicNode], backend: "SessionBackend") -> bool:
    if any(_infer_topic_subject(topic) == subject and _is_root_like_topic(topic, subject) for topic in topics):
        return False
    state = backend.load_app_state(include_history=False)
    root_title = SUBJECT_LABELS.get(subject, subject.title())
    for proposal in state.learning.graph_proposals:
        if proposal.title.strip() == root_title and f"subject:{subject}" in getattr(proposal, "tags", []):
            return False
    return True
