from __future__ import annotations

import json
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
CLASSIFY_BATCH_SIZE = 1


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
    enable_new_pipeline: bool = False,
    subject: str | None = None,
    language_id: str | None = None,
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

    if enable_new_pipeline and subject:
        segments = _run_structured_ingestion(
            backend=backend, record=record, chunks=chunks,
            topics=topics, subject=subject, language_id=language_id,
        )
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
    batch_size = 1 if len(chunks) <= 1 else CLASSIFY_BATCH_SIZE
    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start:batch_start + batch_size]
        if batch_size == 1:
            segments.append(
                _classify_chunk(
                    backend=backend,
                    resource_id=record.resource_id,
                    sequence_index=batch_start,
                    chunk=batch[0],
                    topics=topics,
                    default_topic_id=default_topic_id or record.topic_id,
                    subject=_ctx_subject,
                    language_id=_ctx_language_id,
                )
            )
        else:
            batch_segments = _classify_chunks_batch(
                backend=backend,
                resource_id=record.resource_id,
                start_index=batch_start,
                chunks=batch,
                topics=topics,
                default_topic_id=default_topic_id or record.topic_id,
                subject=_ctx_subject,
                language_id=_ctx_language_id,
            )
            segments.extend(batch_segments)

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


def _classify_chunks_batch(
    *,
    backend: "SessionBackend",
    resource_id: str,
    start_index: int,
    chunks: list[TextUnit],
    topics: list[TopicNode],
    default_topic_id: str | None,
    subject: str | None = None,
    language_id: str | None = None,
) -> list[ResourceSegment]:
    import json as _json

    topic_payload = [
        {
            "topic_id": t.topic_id,
            "title": t.title,
            "tags": t.tags,
            "prerequisite_ids": t.prerequisite_ids,
        }
        for t in topics
    ]

    chunk_texts = []
    for i, chunk in enumerate(chunks):
        chunk_texts.append(f"片段 {i}:\n```text\n{chunk.text.strip()[:2000]}\n```\n")
    combined = "\n".join(chunk_texts)

    system = (
        "你是儿童学习知识图谱策展助手。你的任务是判断多个教学资源片段各自应该挂到已有知识节点，"
        "还是应该提出一个新知识节点。\n"
        "返回一个 JSON 数组，每个元素对应一个片段，顺序与输入一致。\n"
        "【节点合并与复用规则】\n"
        "1. 只能复用给定的已有节点；如果没有合适节点，但片段表达了明确、可教学的知识点，请提出新节点。\n"
        "2. 如果你要提出的新节点和已有节点的概念本质相同（只是换了种说法），请直接选择 link 到已有节点！\n"
        "3. 不要为了泛泛内容创建节点。\n"
        "【新节点命名规范】\n"
        "1. 提取最精炼的专业术语或核心概念，作为新知识点的名称。\n"
        "2. 绝对不要包含「什么是」、「关于」、「浅析」等冗余前缀。\n"
        "3. 绝对不要包含「是什么」、「及其应用」、「的证明」等冗余后缀。\n"
    )
    user = (
        f"已有知识节点列表：\n{_json.dumps(topic_payload, ensure_ascii=False)}\n\n"
        f"默认父节点：\n{_json.dumps(default_topic_id, ensure_ascii=False)}\n\n"
        f"{combined}"
        "返回 JSON 数组：\n"
        '[{"decision":"link|propose|unclassified","topic_id":string|null,'
        '"confidence":number,"reason":string,"proposed_topic":{"title":string,'
        '"summary":string,"parent_node_ids":[string],"edge_type":"requires"|...}|null,'
        '"guiding_question":string,"teaching_hint":string}]'
    )

    raw_results: list[dict] = []
    try:
        response = backend.llm_skill.client.chat.completions.create(
            model=backend.llm_skill.model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            timeout=120.0,
        )
        content = (response.choices[0].message.content or "").strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        parsed = _json.loads(content)
        if isinstance(parsed, list):
            raw_results = [item for item in parsed if isinstance(item, dict)]
    except Exception:
        raw_results = []

    segments: list[ResourceSegment] = []
    for i, chunk in enumerate(chunks):
        seg_index = start_index + i
        if i < len(raw_results):
            result = raw_results[i]
            normalized = _normalize_chunk_decision(
                result=result, topics=topics,
                default_topic_id=default_topic_id,
            )
        else:
            normalized = {
                "decision": "unclassified",
                "topic_id": None,
                "confidence": 0.0,
                "reason": "batch classify missed this chunk",
                "proposed_topic": None,
                "guiding_question": "",
                "teaching_hint": "",
            }

        proposed_topic_title: str | None = None
        proposed_parent_node_ids: list[str] = []
        if normalized["decision"] == "propose":
            pt = normalized["proposed_topic"]
            if isinstance(pt, dict):
                proposed_topic_title = str(pt.get("title", "")).strip() or None
                proposed_parent_node_ids = pt.get("parent_node_ids") or []

        if normalized["decision"] == "link" and normalized["topic_id"]:
            status = "classified"
        elif normalized.get("proposal_id") and normalized["decision"] == "propose":
            status = "proposed"
        elif normalized["decision"] == "propose" and proposed_topic_title:
            status = "unclassified"
        else:
            status = "unclassified"
            proposed_topic_title = None

        segments.append(
            ResourceSegment(
                segment_id=_segment_id(resource_id, seg_index),
                start_ms=0,
                end_ms=None,
                label="chunk",
                status=status,
                sequence_index=seg_index,
                text=chunk.text.strip(),
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
        )
    return segments


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


def _batch_organize_topic_tree(
    *,
    backend: "SessionBackend",
    candidates: list[str],
    subject: str,
    language_id: str | None = None,
) -> list[dict]:
    candidate_list = json.dumps(candidates, ensure_ascii=False)
    lang_hint = f", 语言: {language_id}" if language_id else ""
    system = (
        "你是知识结构组织助手。把一组概念关键词组织成树形层级。\n"
        "规则：\n"
        "1. 识别可以归类的上级概念（如'光学'包含反射/折射），创建中继节点，标题加 [中继] 后缀\n"
        "2. 子概念挂在父概念下\n"
        "3. 同级概念平铺\n"
        "4. 不要凭空创建不在输入列表中的概念作为叶子节点\n"
        "5. 每个输入的关键词必须在树中出现一次\n"
        f"学科: {subject}{lang_hint}\n"
        "返回 JSON 树形数组。"
    )
    user = (
        f"概念关键词列表:\n{candidate_list}\n\n"
        "请组织为树形结构，返回 JSON 数组。中继节点标题加 [中继] 后缀。"
    )
    try:
        response = backend.llm_skill.client.chat.completions.create(
            model=backend.llm_skill.model_name,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3, timeout=60.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _batch_infer_prerequisites(
    *,
    backend: "SessionBackend",
    tree: list[dict],
    subject: str,
) -> dict[str, list[str]]:
    titles = _collect_tree_titles(tree)
    titles_list = json.dumps(titles, ensure_ascii=False)
    system = (
        "你是知识前置关系分析助手。对每个概念，列出学习它之前需要掌握的前置知识。\n"
        "只从给定的标题列表中挑选前置（可以在当前树中，也可以提及不在树中但已知的通用前置）。\n"
        f"学科: {subject}\n"
        "返回 JSON 对象，键为概念标题，值为前置标题数组。"
    )
    user = f"概念标题列表:\n{titles_list}\n\n请推断每个概念的前置依赖，返回 JSON 对象。"
    try:
        response = backend.llm_skill.client.chat.completions.create(
            model=backend.llm_skill.model_name,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3, timeout=60.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _collect_tree_titles(tree: list[dict], depth: int = 0) -> list[str]:
    titles: list[str] = []
    for node in tree:
        title = (node.get("title") or "").strip()
        if title and title not in titles:
            titles.append(title)
        children = node.get("children") or []
        for ct in _collect_tree_titles(children, depth + 1):
            if ct not in titles:
                titles.append(ct)
    return titles


def _create_topics_from_tree(
    *,
    backend: "SessionBackend",
    tree: list[dict],
    prereq_map: dict[str, list[str]],
    subject: str,
    language_id: str | None,
    topics: list[TopicNode],
    profile: object,
) -> dict[str, str]:
    from src.services.resource_graph_curation import _proposal_tags

    title_to_id: dict[str, str] = {}
    _create_tree_nodes(
        nodes=tree, parent_id=None,
        backend=backend, subject=subject, language_id=language_id,
        topics=topics, profile=profile, prereq_map=prereq_map,
        title_to_id=title_to_id, _proposal_tags=_proposal_tags,
    )
    return title_to_id


def _create_tree_nodes(
    *,
    nodes: list[dict],
    parent_id: str | None,
    backend: "SessionBackend",
    subject: str,
    language_id: str | None,
    topics: list[TopicNode],
    profile: object,
    prereq_map: dict[str, list[str]],
    title_to_id: dict[str, str],
    _proposal_tags: object,
) -> None:
    for node in nodes:
        raw_title = (node.get("title") or "").strip()
        if not raw_title:
            continue
        is_relay = "[中继]" in raw_title
        clean_title = raw_title.replace("[中继]", "").strip()

        existing_id = _find_topic_id(clean_title, topics, title_to_id)
        if existing_id:
            title_to_id[clean_title] = existing_id
            children = node.get("children") or []
            if children:
                _create_tree_nodes(
                    nodes=children, parent_id=existing_id,
                    backend=backend, subject=subject, language_id=language_id,
                    topics=topics, profile=profile, prereq_map=prereq_map,
                    title_to_id=title_to_id, _proposal_tags=_proposal_tags,
                )
            continue

        prereqs_raw = prereq_map.get(raw_title) or prereq_map.get(clean_title) or []
        prereq_ids: list[str] = []
        for pt in prereqs_raw:
            pt_clean = str(pt).replace("[中继]", "").strip()
            pid = title_to_id.get(pt_clean) or _find_topic_id(pt_clean, topics, {})
            if pid:
                prereq_ids.append(pid)

        try:
            proposal = backend.create_graph_proposal_from_resource(
                title=clean_title,
                summary=f"{'中继节点: ' if is_relay else ''}{subject}学科知识点",
                tags=_proposal_tags(
                    subject=subject,
                    facet=profile.default_facet,
                    language_id=language_id,
                ),
                parent_node_ids=[parent_id] if parent_id else [],
                prerequisite_node_ids=list(dict.fromkeys(prereq_ids)),
                edge_type="part_of" if parent_id else "requires",
                reason="batch tree creation",
            )
            _st, _pr, topic, _, _ = backend.approve_graph_proposal(
                proposal_id=proposal.proposal_id,
                difficulty=1,
            )
            tid = topic.topic_id
            title_to_id[clean_title] = tid
            topics.append(topic)
        except Exception:
            tid = ""
            title_to_id[clean_title] = ""

        children = node.get("children") or []
        if children and tid:
            _create_tree_nodes(
                nodes=children, parent_id=tid,
                backend=backend, subject=subject, language_id=language_id,
                topics=topics, profile=profile, prereq_map=prereq_map,
                title_to_id=title_to_id, _proposal_tags=_proposal_tags,
            )


def _find_topic_id(title: str, topics: list[TopicNode], title_map: dict[str, str]) -> str | None:
    if title_map.get(title):
        return title_map[title]
    for t in topics:
        if t.title.strip() == title:
            return t.topic_id
    return None


def _run_structured_ingestion(
    *,
    backend: "SessionBackend",
    record: ResourceRecord,
    chunks: list[TextUnit],
    topics: list[TopicNode],
    subject: str,
    language_id: str | None = None,
) -> list[ResourceSegment]:
    from src.services.document_analyzer import analyze_document_structure, SKIP_SECTION_TYPES
    from src.services.graph_search import GraphSearchAgent
    from src.services.graph_walker import GraphWalker
    from src.services.resource_graph_curation import (
        SUBJECT_PROFILES, _proposal_tags,
    )

    profile = SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"])
    sections = analyze_document_structure(
        backend=backend, chunks=chunks, subject=subject, language_id=language_id,
    )
    if not sections:
        return [
            _status_segment(
                resource_id=record.resource_id, sequence_index=0,
                status="unclassified", reason="structured analysis returned no sections",
                locator={"kind": record.media_type or "unknown"},
            )
        ]

    walker = GraphWalker(backend, subject, language_id)
    search_agent = GraphSearchAgent(backend, subject, language_id)

    # Batch tree organization: collect all candidates, organize, infer prereqs, create
    if sections and backend.llm_skill.client.api_key:
        try:
            all_candidates: list[str] = []
            for section in sections:
                for t in section.topic_candidates:
                    clean = t.strip()
                    if clean and clean not in all_candidates:
                        all_candidates.append(clean)
            if all_candidates:
                tree = _batch_organize_topic_tree(
                    backend=backend, candidates=all_candidates,
                    subject=subject, language_id=language_id,
                )
                if tree:
                    prereq_map = _batch_infer_prerequisites(
                        backend=backend, tree=tree, subject=subject,
                    )
                    _create_topics_from_tree(
                        backend=backend, tree=tree, prereq_map=prereq_map,
                        subject=subject, language_id=language_id,
                        topics=topics, profile=profile,
                    )
                    walker = GraphWalker(backend, subject, language_id)
                    search_agent = GraphSearchAgent(backend, subject, language_id)
        except Exception:
            pass

    segments: list[ResourceSegment] = []
    last_topic_id: str | None = None
    last_proposal_id: str | None = None
    seg_index = 0

    for section in sections:
        if section.section_type in SKIP_SECTION_TYPES:
            seg_index += 1
            segments.append(
                ResourceSegment(
                    segment_id=_segment_id(record.resource_id, seg_index),
                    start_ms=0, end_ms=None, label=section.section_type,
                    status="unclassified", sequence_index=seg_index,
                    text=section.text[:2000], locator={"kind": "structured", "section_type": section.section_type},
                    topic_id=None, proposal_id=None,
                    decision="unclassified", confidence=0.0,
                    reason=f"{section.section_type} section skipped",
                )
            )
            continue

        section_topic_id: str | None = None
        section_proposal_id: str | None = None

        for topic_title in section.topic_candidates:
            if not topic_title.strip():
                continue

            # Deterministic exact-title dedup: skip LLM call for obvious duplicates
            for topic in topics:
                if topic.title.strip() == topic_title.strip():
                    section_topic_id = topic.topic_id
                    last_topic_id = section_topic_id
                    break
            if section_topic_id:
                continue

            search_result = search_agent.search(topic_title, section.text[:1000])
            if search_result.decision == "link" and search_result.confidence >= 0.55:
                section_topic_id = search_result.matched_topic_id
                last_topic_id = section_topic_id
                continue

            walk_result = walker.walk_and_insert(topic_title, section.text[:500])
            if walk_result.action == "link_existing":
                section_topic_id = walk_result.anchor_topic_id
                last_topic_id = section_topic_id
                continue

            try:
                proposal = backend.create_graph_proposal_from_resource(
                    title=topic_title,
                    summary=section.text[:200],
                    tags=_proposal_tags(
                        subject=subject, facet=profile.default_facet,
                        language_id=language_id,
                    ),
                    parent_node_ids=walk_result.parent_node_ids,
                    prerequisite_node_ids=walk_result.prerequisite_node_ids,
                    edge_type=walk_result.relation,
                    reason=walk_result.reason[:80],
                )
                # Auto-approve so subsequent topics in same batch can dedup against it
                _st, _pr, topic, _, _ = backend.approve_graph_proposal(
                    proposal_id=proposal.proposal_id,
                    difficulty=1,
                )
                section_topic_id = topic.topic_id
                last_topic_id = section_topic_id
                # Add to local topics list for deterministic dedup in this batch
                topics.append(topic)
                walker = GraphWalker(backend, subject, language_id)
                search_agent = GraphSearchAgent(backend, subject, language_id)
            except Exception:
                pass

        if section.bound_exercises:
            exercise_text = "\n".join(section.bound_exercises)
            seg_index += 1
            segments.append(
                ResourceSegment(
                    segment_id=_segment_id(record.resource_id, seg_index),
                    start_ms=0, end_ms=None, label="exercise",
                    status="classified" if section_topic_id else "unclassified",
                    sequence_index=seg_index,
                    text=exercise_text[:2000],
                    locator={"kind": "structured", "section_type": "exercise"},
                    topic_id=section_topic_id or last_topic_id,
                    proposal_id=None,
                    decision="link" if (section_topic_id or last_topic_id) else "unclassified",
                    confidence=0.85,
                    reason="bound exercise" if (section_topic_id or last_topic_id) else "no topic to bind",
                )
            )

        seg_index += 1
        segments.append(
            ResourceSegment(
                segment_id=_segment_id(record.resource_id, seg_index),
                start_ms=0, end_ms=None, label="chunk",
                status=(
                    "classified" if section_topic_id
                    else "proposed" if section_proposal_id
                    else "unclassified"
                ),
                sequence_index=seg_index,
                text=section.text[:2000],
                locator={"kind": "structured", "section_type": section.section_type},
                topic_id=section_topic_id or last_topic_id,
                proposal_id=section_proposal_id,
                proposed_topic_title=section.topic_candidates[0] if section.topic_candidates else None,
                decision=(
                    "link" if section_topic_id or last_topic_id
                    else "propose" if section_proposal_id
                    else "unclassified"
                ),
                confidence=0.85,
                reason=(
                    "matched existing topic" if section_topic_id
                    else "new topic proposed" if section_proposal_id
                    else "no topic extracted"
                ),
            )
        )

        if section_topic_id:
            last_topic_id = section_topic_id

    return segments


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
