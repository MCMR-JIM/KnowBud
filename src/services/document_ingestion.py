from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.core.models import ResourceRecord, ResourceSegment, TopicNode
from src.agent.models import EdgeType
from src.services.resource_graph_curation import (
    _subject_from_tags,
    create_resource_level_proposals,
    detect_resource_subject,
)

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend


TARGET_CHARS = 1000
MAX_CHARS = 1800
CLASSIFIED_THRESHOLD = 0.55


@dataclass
class TextUnit:
    text: str
    locator: dict[str, object]


def ingest_document_resource(
    backend: "SessionBackend",
    record: ResourceRecord,
    topics: list[TopicNode],
    default_topic_id: str | None = None,
    progress_callback: Callable[[str, dict[str, object]], None] | None = None,
    enable_graph_search: bool = False,
) -> list[ResourceSegment]:
    parser = _select_parser(record)
    if parser is None:
        segments = [
            _status_segment(
                resource_id=record.resource_id,
                sequence_index=0,
                status="unsupported",
                reason=f"暂不支持解析 {record.media_type} 文件",
                locator={"kind": record.media_type or "binary"},
            )
        ]
        backend.replace_resource_segments(record.resource_id, segments)
        return segments

    try:
        units = parser(Path(record.stored_path))
    except Exception as exc:
        segments = [
            _status_segment(
                resource_id=record.resource_id,
                sequence_index=0,
                status="parse_failed",
                reason=f"文档解析失败: {str(exc)[:60]}",
                locator={"kind": record.media_type or "unknown"},
            )
        ]
        backend.replace_resource_segments(record.resource_id, segments)
        return segments

    chunks = _units_to_chunks(units)
    if progress_callback is not None:
        progress_callback(
            "document_parsed",
            {
                "resource_id": record.resource_id,
                "chunk_count": len(chunks),
                "media_type": record.media_type,
            },
        )
    if not chunks:
        segments = [
            _status_segment(
                resource_id=record.resource_id,
                sequence_index=0,
                status="parse_failed",
                reason="文档未提取到可用文本",
                locator={"kind": record.media_type or "unknown"},
            )
        ]
        backend.replace_resource_segments(record.resource_id, segments)
        return segments

    _ctx_subject: str | None = None
    _ctx_language_id: str | None = None
    if enable_graph_search:
        try:
            detected = detect_resource_subject(
                record=record,
                segments=[],
                topics=topics,
                default_topic_id=default_topic_id or record.topic_id,
                backend=backend,
            )
            if detected != "general":
                _ctx_subject = detected
        except Exception:
            _ctx_subject = None

    segments: list[ResourceSegment] = []
    for index, chunk in enumerate(chunks):
        if progress_callback is not None:
            progress_callback(
                "chunk_classification_progress",
                {
                    "resource_id": record.resource_id,
                    "current": index + 1,
                    "total": len(chunks),
                },
            )
        segments.append(
            _classify_chunk(
                backend=backend,
                resource_id=record.resource_id,
                sequence_index=index,
                chunk=chunk,
                topics=topics,
                default_topic_id=default_topic_id or record.topic_id,
                subject=_ctx_subject,
                language_id=_ctx_language_id,
            )
        )

    create_resource_level_proposals(
        backend=backend,
        record=record,
        segments=segments,
        topics=topics,
        default_topic_id=default_topic_id or record.topic_id,
    )

    backend.replace_resource_segments(record.resource_id, segments)
    return segments


def _select_parser(record: ResourceRecord) -> Callable[[Path], list[TextUnit]] | None:
    media_type = (record.media_type or "").strip().lower()
    ext = Path(record.original_filename).suffix.lower()
    if media_type == "txt" or ext in {".txt", ".md"}:
        return _parse_txt
    if media_type == "pdf" or ext == ".pdf":
        return _parse_pdf
    if media_type == "docx" or ext == ".docx":
        return _parse_docx
    if media_type == "pptx" or ext == ".pptx":
        return _parse_pptx
    if media_type == "doc" or ext == ".doc":
        return None
    return None


def _parse_txt(path: Path) -> list[TextUnit]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = text.splitlines()
    units: list[TextUnit] = []
    buffer: list[str] = []
    line_start: int | None = None
    for index, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if stripped:
            if line_start is None:
                line_start = index
            buffer.append(stripped)
            continue
        if buffer and line_start is not None:
            units.append(
                TextUnit(
                    text="\n".join(buffer),
                    locator={"kind": "txt", "line_start": line_start, "line_end": index - 1},
                )
            )
            buffer = []
            line_start = None
    if buffer and line_start is not None:
        units.append(
            TextUnit(
                text="\n".join(buffer),
                locator={"kind": "txt", "line_start": line_start, "line_end": len(lines) or line_start},
            )
        )
    return units


def _parse_pdf(path: Path) -> list[TextUnit]:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise RuntimeError("pypdf is required for PDF parsing") from exc

    reader = PdfReader(str(path))
    units: list[TextUnit] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        for block in _split_text_blocks(text):
            units.append(
                TextUnit(
                    text=block,
                    locator={"kind": "pdf", "page_start": page_index, "page_end": page_index},
                )
            )
    return units


def _parse_docx(path: Path) -> list[TextUnit]:
    try:
        from docx import Document
    except ModuleNotFoundError as exc:
        raise RuntimeError("python-docx is required for DOCX parsing") from exc

    document = Document(str(path))
    units: list[TextUnit] = []
    for paragraph_index, paragraph in enumerate(document.paragraphs, start=1):
        text = paragraph.text.strip()
        if not text:
            continue
        units.append(
            TextUnit(
                text=text,
                locator={"kind": "docx", "paragraph_start": paragraph_index, "paragraph_end": paragraph_index},
            )
        )
    return units


def _parse_pptx(path: Path) -> list[TextUnit]:
    try:
        from pptx import Presentation
    except ModuleNotFoundError as exc:
        raise RuntimeError("python-pptx is required for PPTX parsing") from exc

    presentation = Presentation(str(path))
    units: list[TextUnit] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        merged = "\n".join(parts).strip()
        if not merged:
            continue
        units.append(
            TextUnit(
                text=merged,
                locator={"kind": "pptx", "slide_start": slide_index, "slide_end": slide_index},
            )
        )
    return units


def _split_text_blocks(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", cleaned) if block.strip()]
    return blocks or [cleaned]


def _units_to_chunks(units: list[TextUnit]) -> list[TextUnit]:
    chunks: list[TextUnit] = []
    for unit in units:
        chunks.extend(_split_unit(unit))
    return chunks


def _split_unit(unit: TextUnit) -> list[TextUnit]:
    text = unit.text.strip()
    if not text:
        return []
    if len(text) <= MAX_CHARS:
        return [TextUnit(text=text, locator=dict(unit.locator))]

    chunks: list[TextUnit] = []
    current = ""
    for sentence in _split_sentences(text):
        if not sentence:
            continue
        if current and len(current) + len(sentence) > MAX_CHARS:
            chunks.append(TextUnit(text=current.strip(), locator=dict(unit.locator)))
            current = ""
        if len(sentence) > MAX_CHARS:
            if current:
                chunks.append(TextUnit(text=current.strip(), locator=dict(unit.locator)))
                current = ""
            for piece in _hard_split(sentence):
                chunks.append(TextUnit(text=piece, locator=dict(unit.locator)))
            continue
        if current and len(current) + len(sentence) > TARGET_CHARS:
            chunks.append(TextUnit(text=current.strip(), locator=dict(unit.locator)))
            current = sentence
        else:
            current += sentence
    if current.strip():
        chunks.append(TextUnit(text=current.strip(), locator=dict(unit.locator)))
    return chunks


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;.!?])|\n+", text)
    return [part.strip() for part in parts if part and part.strip()]


def _hard_split(text: str) -> list[str]:
    pieces: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= MAX_CHARS:
            pieces.append(remaining)
            break
        cut = remaining[:MAX_CHARS]
        boundary = max(cut.rfind(marker) for marker in ("。", "！", "？", "；", ";", ".", "，", ",", " "))
        if boundary < int(MAX_CHARS * 0.5):
            boundary = MAX_CHARS
        else:
            boundary += 1
        pieces.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    return [piece for piece in pieces if piece]


def _classify_chunk(
    *,
    backend: "SessionBackend",
    resource_id: str,
    sequence_index: int,
    chunk: TextUnit,
    topics: list[TopicNode],
    default_topic_id: str | None,
    subject: str | None = None,
    language_id: str | None = None,
) -> ResourceSegment:
    text = chunk.text.strip()
    normalized = {
        "decision": "unclassified",
        "topic_id": None,
        "confidence": 0.0,
        "reason": "未找到合适知识点",
        "proposed_topic": None,
        "guiding_question": "",
        "teaching_hint": "",
    }
    proposed_topic_title: str | None = None
    proposed_parent_node_ids: list[str] = []

    try:
        result = backend.llm_skill.classify_or_propose_resource_chunk(
            chunk_text=text,
            topics=topics,
            default_parent_topic_id=default_topic_id,
        )
        if isinstance(result, dict):
            normalized = _normalize_chunk_decision(result=result, topics=topics, default_topic_id=default_topic_id)
            if normalized["decision"] == "propose":
                proposed_topic = normalized["proposed_topic"]
                if isinstance(proposed_topic, dict):
                    proposed_topic_title = str(proposed_topic.get("title", "")).strip() or None
                    proposed_parent_node_ids = proposed_topic.get("parent_node_ids") or []
    except Exception as exc:
        normalized = {
            "decision": "unclassified",
            "topic_id": None,
            "confidence": 0.0,
            "reason": f"分类失败: {str(exc)[:60]}",
            "proposed_topic": None,
            "guiding_question": "",
            "teaching_hint": "",
        }

    if normalized["decision"] == "propose" and subject is not None and backend.llm_skill.client.api_key:
        try:
            from src.services.graph_search import GraphSearchAgent

            agent = GraphSearchAgent(backend, subject, language_id)
            search_result = agent.search(chunk_text=text)
            if search_result.decision == "link" and search_result.confidence >= 0.55:
                normalized["decision"] = "link"
                normalized["topic_id"] = search_result.matched_topic_id
                normalized["confidence"] = max(normalized["confidence"], search_result.confidence)
                normalized["reason"] = f"[图谱去重] {search_result.reason[:60]}"
                normalized["proposed_topic"] = None
                proposed_topic_title = None
                proposed_parent_node_ids = []
            elif search_result.decision == "propose":
                if search_result.proposed_title:
                    proposed_topic_title = search_result.proposed_title
                if search_result.parent_node_ids:
                    proposed_parent_node_ids = search_result.parent_node_ids
                if proposed_topic_title:
                    try:
                        from src.services.resource_graph_curation import deduplicate_candidate_title

                        state = backend.load_app_state(include_history=False)
                        existing = [
                            {
                                "topic_id": t.topic_id,
                                "title": t.title,
                                "subject": _node_subject_tag(t.tags),
                                "facet": _tag_value(t.tags, "facet:"),
                                "language_id": _tag_value(t.tags, "language:"),
                                "tags": t.tags,
                            }
                            for t in state.curriculum.topics
                        ]
                        for p in state.learning.graph_proposals:
                            if p.status in {"rejected"}:
                                continue
                            existing.append(
                                {
                                    "topic_id": p.proposal_id,
                                    "title": p.title,
                                    "subject": _node_subject_tag(getattr(p, "tags", [])),
                                    "facet": _tag_value(getattr(p, "tags", []), "facet:"),
                                    "language_id": _tag_value(getattr(p, "tags", []), "language:"),
                                    "tags": getattr(p, "tags", []),
                                }
                            )
                        matched_id = deduplicate_candidate_title(
                            backend=backend,
                            candidate_title=proposed_topic_title,
                            candidate_subject=subject,
                            candidate_facet="",
                            candidate_text=text,
                            candidate_language_id=language_id,
                            existing_nodes=existing,
                        )
                        if matched_id:
                            if isinstance(matched_id, str) and matched_id.startswith("proposal_"):
                                normalized["decision"] = "propose"
                                normalized["topic_id"] = None
                                normalized["proposal_id"] = matched_id
                            else:
                                normalized["decision"] = "link"
                                normalized["topic_id"] = matched_id
                            normalized["confidence"] = max(normalized["confidence"], 0.8)
                            normalized["reason"] = f"[语义消歧] 归并到已有节点 {matched_id}"
                            normalized["proposed_topic"] = None
                            proposed_topic_title = None
                            proposed_parent_node_ids = []
                    except Exception:
                        pass
        except Exception:
            pass

    if normalized["decision"] == "link" and normalized["topic_id"]:
        status = "classified"
    elif normalized.get("proposal_id") and normalized["decision"] == "propose":
        status = "proposed"
    elif normalized["decision"] == "propose" and proposed_topic_title:
        status = "unclassified"
    else:
        status = "unclassified"
        proposed_topic_title = None

    return ResourceSegment(
        segment_id=_segment_id(resource_id, sequence_index),
        start_ms=0,
        end_ms=None,
        label="chunk",
        status=status,
        sequence_index=sequence_index,
        text=text,
        locator=dict(chunk.locator),
        topic_id=str(normalized["topic_id"]) if normalized["topic_id"] is not None else None,
        proposal_id=str(normalized.get("proposal_id")) if normalized.get("proposal_id") is not None else None,
        proposed_topic_title=proposed_topic_title,
        proposed_parent_node_ids=proposed_parent_node_ids,
        decision=str(normalized["decision"]),
        confidence=float(normalized["confidence"]),
        reason=str(normalized["reason"]),
        guiding_question=str(normalized.get("guiding_question", "")) or None,
        teaching_hint=str(normalized.get("teaching_hint", "")) or None,
    )


def _normalize_chunk_decision(
    *,
    result: dict[str, object],
    topics: list[TopicNode],
    default_topic_id: str | None,
) -> dict[str, object]:
    valid_topic_ids = {topic.topic_id for topic in topics}
    allowed_decisions = {"link", "propose", "unclassified"}
    allowed_edge_types = {item.value for item in EdgeType}

    raw_decision = result.get("decision")
    decision = raw_decision if isinstance(raw_decision, str) and raw_decision in allowed_decisions else "unclassified"
    raw_topic_id = result.get("topic_id")
    topic_id = raw_topic_id if isinstance(raw_topic_id, str) and raw_topic_id in valid_topic_ids else None
    raw_reason = result.get("reason")
    reason = raw_reason.strip()[:80] if isinstance(raw_reason, str) and raw_reason.strip() else "未找到合适知识点"
    raw_guiding_question = result.get("guiding_question")
    guiding_question = raw_guiding_question.strip()[:60] if isinstance(raw_guiding_question, str) else ""
    raw_teaching_hint = result.get("teaching_hint")
    teaching_hint = raw_teaching_hint.strip()[:80] if isinstance(raw_teaching_hint, str) else ""

    raw_confidence = result.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(raw_confidence)))
    except (TypeError, ValueError):
        confidence = 0.0

    proposed_topic: dict[str, object] | None = None
    if decision == "propose":
        raw_proposed_topic = result.get("proposed_topic")
        if isinstance(raw_proposed_topic, dict):
            raw_title = raw_proposed_topic.get("title")
            title = raw_title.strip()[:120] if isinstance(raw_title, str) else ""
            raw_summary = raw_proposed_topic.get("summary")
            summary = raw_summary.strip()[:500] if isinstance(raw_summary, str) else ""
            raw_parent_ids = raw_proposed_topic.get("parent_node_ids")
            parent_node_ids = [
                item for item in raw_parent_ids if isinstance(item, str) and item in valid_topic_ids
            ] if isinstance(raw_parent_ids, list) else []
            if not parent_node_ids and default_topic_id in valid_topic_ids:
                parent_node_ids = [default_topic_id]
            raw_edge_type = raw_proposed_topic.get("edge_type")
            edge_type = raw_edge_type if isinstance(raw_edge_type, str) and raw_edge_type in allowed_edge_types else "requires"
            if title:
                proposed_topic = {
                    "title": title,
                    "summary": summary,
                    "parent_node_ids": parent_node_ids,
                    "edge_type": edge_type,
                }

    if confidence < CLASSIFIED_THRESHOLD:
        decision = "unclassified"

    if decision == "link":
        if topic_id is None:
            decision = "unclassified"
    elif decision == "propose":
        topic_id = None
        if proposed_topic is None:
            decision = "unclassified"
    else:
        topic_id = None
        proposed_topic = None

    if decision == "unclassified":
        topic_id = None
        proposed_topic = None

    return {
        "decision": decision,
        "topic_id": topic_id,
        "confidence": confidence,
        "reason": reason,
        "proposed_topic": proposed_topic,
        "guiding_question": guiding_question,
        "teaching_hint": teaching_hint,
    }


def _tag_value(tags: list[str], prefix: str, default: str | None = None) -> str | None:
    for tag in tags:
        if tag.startswith(prefix):
            return tag.split(":", 1)[1]
    return default


def _node_subject_tag(tags: list[str]) -> str:
    raw = _tag_value(tags, "subject:")
    if raw is None:
        return "general"
    if raw in {"english", "chinese", "语文", "中文"}:
        return "language"
    return raw


def _detect_lang_from_chunks(chunks: list[TextUnit], topics: list[TopicNode]) -> str | None:
    sample = " ".join(c.text for c in chunks[:3]).lower()
    if "english" in sample or "英语" in sample or re.search(r"\b(present continuous|simple past)\b", sample):
        return "english"
    if "语文" in sample or "中文" in sample or "chinese" in sample or "阅读理解" in sample:
        return "chinese"
    return None


def _status_segment(
    *,
    resource_id: str,
    sequence_index: int,
    status: str,
    reason: str,
    locator: dict[str, object],
) -> ResourceSegment:
    return ResourceSegment(
        segment_id=_segment_id(resource_id, sequence_index),
        start_ms=0,
        end_ms=None,
        label="document",
        status=status,
        sequence_index=sequence_index,
        text="",
        locator=locator,
        topic_id=None,
        decision="unclassified",
        confidence=0.0,
        reason=reason[:80],
        guiding_question=None,
        teaching_hint=None,
    )


def _segment_id(resource_id: str, sequence_index: int) -> str:
    return f"seg_{resource_id}_{sequence_index:04d}_{uuid.uuid4().hex[:6]}"
