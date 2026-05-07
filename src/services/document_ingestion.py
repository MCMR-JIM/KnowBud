from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    lang_hint = ""
    if subject == "language" and language_id:
        lang_hint = (
            f", 语言: {language_id}\n"
            "对于英语，按语法/词汇/发音/阅读/写作/功能句型分组。\n"
            "对于语文，按识字/古诗词/阅读理解/写作/语言知识点分组。\n"
        )
    system = (
        "你是知识结构组织助手。把一组概念关键词组织成树形层级。\n"
        f"学科: {subject}{lang_hint}"
        "规则:\n"
        "1. 中继节点标题必须以 [中继] 结尾\n"
        "2. 每个输入的关键词必须在树中出现一次\n"
        "3. 不要凭空创建不在列表中的叶子节点\n"
        "4. 同级概念平铺在同一中继下\n"
        "返回 JSON 树形数组。"
    )
    user = (
        f"概念关键词列表:\n{candidate_list}\n\n"
        "请组织为树形结构。中继节点标题加 [中继] 后缀。"
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


def _create_relay_and_attach(
    *,
    backend: "SessionBackend",
    tree: list[dict],
    root_topic_id: str | None,
    topic_map: dict[str, str],
    subject: str,
    language_id: str | None,
    topics: list[TopicNode],
    parent_id: str | None = None,
) -> None:
    from src.services.resource_graph_curation import SUBJECT_PROFILES, _proposal_tags

    profile = SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"])
    for node in tree:
        raw_title = (node.get("title") or "").strip()
        if not raw_title:
            continue
        children = node.get("children") or []
        is_relay = "[中继]" in raw_title
        clean = raw_title.replace("[中继]", "").strip()

        if not children:
            # Leaf node: don't create here, GraphLocator will handle it
            continue

        # Relay node: create + approve
        pid = parent_id or root_topic_id
        if clean in topic_map:
            tid = topic_map[clean]
        else:
            try:
                proposal = backend.create_graph_proposal_from_resource(
                    title=clean,
                    summary=f"中继节点: {subject}学科",
                    tags=_proposal_tags(
                        subject=subject, facet=profile.default_facet,
                        language_id=language_id,
                    ),
                    parent_node_ids=[pid] if pid else [],
                    prerequisite_node_ids=[],
                    edge_type="part_of",
                    reason="batch tree relay node",
                )
                _st, _pr, tpc, _, _ = backend.approve_graph_proposal(
                    proposal_id=proposal.proposal_id, difficulty=1,
                )
                tid = tpc.topic_id
                topic_map[clean] = tid
                topics.append(tpc)
            except Exception:
                continue

        if children and tid:
            _create_relay_and_attach(
                backend=backend, tree=children,
                root_topic_id=root_topic_id, topic_map=topic_map,
                subject=subject, language_id=language_id,
                topics=topics, parent_id=tid,
            )


def _run_structured_ingestion(
    *,
    backend: "SessionBackend",
    record: ResourceRecord,
    chunks: list[TextUnit],
    topics: list[TopicNode],
    subject: str,
    language_id: str | None = None,
) -> list[ResourceSegment]:
    from src.services.resource_graph_curation import SUBJECT_PROFILES, _proposal_tags
    from src.services.graph_locator import GraphLocator

    profile = SUBJECT_PROFILES.get(subject, SUBJECT_PROFILES["general"])

    # ── Phase 1: one LLM call to scan full document ──
    scan = _fast_document_scan(backend, chunks, subject, language_id)
    blocks = scan.get("blocks") or []
    _topic_block_types = {
        "topic_area", "grammar_point", "vocabulary_theme", "pronunciation",
        "reading", "functional_expression",
        "character_learning", "poetry", "reading_comprehension", "writing", "language_point",
    }
    topic_blocks = [b for b in blocks if b.get("type") in _topic_block_types]
    exercise_blocks = [b for b in blocks if b.get("type") == "exercise_only"]

    if not topic_blocks and not exercise_blocks:
        return [
            _status_segment(
                resource_id=record.resource_id, sequence_index=0,
                status="unclassified", reason="no topic or exercise blocks found",
                locator={"kind": "structured"},
            )
        ]

    topic_map = {t.title.strip(): t.topic_id for t in topics}
    root_topic_id = _find_subject_root_id(topics, subject, language_id)

    # ── Phase 2: parallel topic extraction (no locator) ──
    all_results: dict[str, list] = {}
    if topic_blocks and backend.llm_skill.client.api_key:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(
                    _process_topic_block, backend, block, chunks,
                    subject, language_id, topic_map,
                ): block
                for block in topic_blocks
            }
            for future in as_completed(futures):
                block = futures[future]
                try:
                    all_results[block.get("label", block.get("summary", ""))] = future.result()
                except Exception:
                    pass

    # ── Collect, dedup, then locate + insert sequentially ──
    all_topics: list[tuple[str, str]] = []
    for results in all_results.values():
        for t, d in results:
            all_topics.append((t, d))

    seen: set[str] = set()
    deduped = [(t, d) for t, d in all_topics if not (t in seen or seen.add(t))]

    # Batch tree organization: create relay nodes before per-topic insertion
    if len(deduped) > 1 and backend.llm_skill.client.api_key:
        try:
            tree = _batch_organize_topic_tree(
                backend=backend,
                candidates=[t for t, d in deduped],
                subject=subject,
                language_id=language_id,
            )
            if tree:
                _create_relay_and_attach(
                    backend=backend, tree=tree,
                    root_topic_id=root_topic_id, topic_map=topic_map,
                    subject=subject, language_id=language_id,
                    topics=topics,
                )
        except Exception:
            pass

    if deduped:
        from src.services.graph_locator import GraphLocator

        locator = GraphLocator(backend, subject, language_id)

        # Step 1: cluster into relay groups (one LLM call)
        all_titles = [t for t, d in deduped if t not in topic_map]
        if len(all_titles) > 2:
            relay_nodes = locator.cluster_into_relays(all_titles)
            if relay_nodes:
                _create_relay_and_attach(
                    backend=backend, tree=relay_nodes,
                    root_topic_id=root_topic_id, topic_map=topic_map,
                    subject=subject, language_id=language_id,
                    topics=topics,
                )
                locator.refresh()

        # Step 2: per-topic locate (proven approach)
        for title, desc in deduped:
            if title in topic_map:
                continue
            pos = locator.locate(title, desc)
            if pos.exists and pos.node_id:
                topic_map[title] = pos.node_id
                continue

            parents = [pid for pid in pos.parent_ids if pid in topic_map.values()]
            if not parents and root_topic_id:
                parents = [root_topic_id]
            successors = [pid for pid in pos.successor_ids
                          if pid in topic_map.values() and pid != root_topic_id]
            try:
                proposal = backend.create_graph_proposal_from_resource(
                    title=title, summary=desc[:200],
                    tags=_proposal_tags(
                        subject=subject, facet=profile.default_facet,
                        language_id=language_id,
                    ),
                    parent_node_ids=parents,
                    prerequisite_node_ids=successors,
                    edge_type="part_of" if parents else "requires",
                    reason=pos.reason[:80],
                )
                _st, _pr, tpc, _, _ = backend.approve_graph_proposal(
                    proposal_id=proposal.proposal_id, difficulty=1,
                )
                topic_map[title] = tpc.topic_id
                locator.refresh()
            except Exception:
                pass

    # ── Process exercises ──
    if exercise_blocks:
        _process_exercise_blocks(
            backend=backend, blocks=exercise_blocks, chunks=chunks,
            topics=topics, topic_map=topic_map,
            record=record, subject=subject, language_id=language_id,
            profile=profile, _proposal_tags=_proposal_tags,
        )

    # ── Build segments ──
    return _build_segments_from_scan(
        scan=scan, record=record, topics=topics, topic_map=topic_map,
    )


# ── Phase 1 helpers ──

def _fast_document_scan(
    backend: "SessionBackend",
    chunks: list[TextUnit],
    subject: str,
    language_id: str | None = None,
) -> dict:
    full_text = "\n\n".join(c.text for c in chunks if c.text)
    if len(full_text) > 24000:
        full_text = full_text[:12000] + "\n\n[...省略...]\n\n" + full_text[-12000:]

    if subject == "language" and language_id == "english":
        system = (
            "你是英语教材分析助手。通读以下英语教学文档全文。\n"
            "任务:\n"
            "1. 判断文档类型: textbook | workbook | examination | vocabulary_list | phonics_chart\n"
            "2. 识别单元结构 (Unit 1, Unit 2...)\n"
            "3. 对每个单元提取以下类型的知识块:\n"
            '   - grammar_point: 语法知识点 (如"现在进行时"、"情态动词 must")\n'
            '     → type="grammar_point", topic_candidates填语法点名称\n'
            '   - vocabulary_theme: 词汇主题 (如"School Rules"、"Weather")\n'
            '     → type="vocabulary_theme", topic_candidates填主题分类名\n'
            '   - pronunciation: 发音规则 (如"a_e /eɪ/"、"aw /ɔː/")\n'
            '     → type="pronunciation", topic_candidates填发音规则\n'
            '   - reading: 阅读课文 (如有明确课文标题)\n'
            '     → type="reading", topic_candidates填课文标题或主题\n'
            '   - functional_expression: 功能句型 (如"Making Requests")\n'
            '     → type="functional_expression", topic_candidates填功能描述\n'
            "4. 单词表/词汇表标记为 type=word_list, 不提取 topic_candidates\n"
            "5. 练习题标记为 type=exercise_only\n"
            "返回 JSON: {\"doc_type\":\"...\",\"blocks\":[{\"label\":\"...\",\"summary\":\"...\","
            '"type":"grammar_point|vocabulary_theme|pronunciation|reading|functional_expression|'
            'word_list|exercise_only|fuzzy|appendix","start_marker":"...","end_marker":"..."}]'
        )
    elif subject == "language" and language_id == "chinese":
        system = (
            "你是语文教材分析助手。通读以下语文教学文档全文。\n"
            "任务:\n"
            "1. 判断文档类型: textbook | workbook | examination | poetry_collection | character_practice\n"
            "2. 识别课文结构 (第X课、第X单元...)\n"
            "3. 对每课/每单元提取:\n"
            '   - character_learning: 生字/识字点\n'
            '     → type="character_learning", topic_candidates填识字主题 (如"会认字:山水火")\n'
            '   - poetry: 古诗词\n'
            '     → type="poetry", topic_candidates填诗词标题\n'
            '   - reading_comprehension: 课文阅读理解\n'
            '     → type="reading_comprehension", topic_candidates填课文标题或理解主题\n'
            '   - writing: 写作练习\n'
            '     → type="writing", topic_candidates填写作类型 (如"看图写话"、"日记")\n'
            '   - language_point: 语言知识点\n'
            '     → type="language_point", topic_candidates填知识点 (如"比喻"、"排比")\n'
            "4. 生字表/写字表标记为 type=word_list\n"
            "5. 练习题标记为 type=exercise_only\n"
            "返回 JSON: {\"doc_type\":\"...\",\"blocks\":[{\"label\":\"...\",\"summary\":\"...\","
            '"type":"character_learning|poetry|reading_comprehension|writing|language_point|'
            'word_list|exercise_only|fuzzy|appendix","start_marker":"...","end_marker":"..."}]'
        )
    else:
        system = (
            "你是教学文档分析助手。通读以下文档全文，返回结构化分析。\n"
            f"学科: {subject}\n"
            "输出 JSON：{\"doc_type\":\"...\",\"blocks\":[{\"label\":\"...\",\"summary\":\"...\","
            '"type":"topic_area|exercise_only|fuzzy|word_list|appendix","start_marker":"...","end_marker":"..."}]'
        )
    user = f"文档全文:\n```text\n{full_text}\n```\n请分析并返回 JSON。"

    fallback = {"doc_type": "unknown", "blocks": []}
    try:
        response = backend.llm_skill.client.chat.completions.create(
            model=backend.llm_skill.model_name,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3, timeout=120.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


# ── Phase 2 helpers ──

def _process_topic_block(
    backend: "SessionBackend",
    block: dict,
    chunks: list[TextUnit],
    subject: str,
    language_id: str | None,
    topic_map: dict[str, str],
) -> list:
    block_text = _extract_block_text(block, chunks)
    topics_data = _extract_topics_from_block_text(backend, block_text, subject, language_id)
    results: list = []
    for td in topics_data:
        title = (td.get("title") or "").strip()
        desc = (td.get("desc") or "").strip()
        if title:
            results.append((title, desc))
    return results


def _extract_block_text(block: dict, chunks: list[TextUnit]) -> str:
    start = (block.get("start_marker") or "").lower()
    end = (block.get("end_marker") or "").lower()
    if not start:
        return " ".join(c.text for c in chunks[:3])

    capturing = False
    parts: list[str] = []
    for chunk in chunks:
        text = chunk.text or ""
        lower = text.lower()
        if start in lower:
            capturing = True
        if capturing:
            parts.append(text)
        if end and end in lower:
            break
    return "\n".join(parts) if parts else " ".join(c.text for c in chunks[:3])


def _extract_topics_from_block_text(
    backend: "SessionBackend",
    block_text: str,
    subject: str,
    language_id: str | None = None,
) -> list[dict]:
    lang_hint = f", 语言: {language_id}" if language_id else ""
    system = (
        "你是教学知识点提取助手。从段落提取可作知识图谱节点的知识点。\n"
        "只提取可教学的知识点（定理、定律、公式、概念、语法点）。\n"
        "不要提取实验过程、课堂活动、练习指令、方法论标题。\n"
        f"学科: {subject}{lang_hint}\n"
        '返回 JSON 数组: [{"title":"知识点名","desc":"一句话说明"}]'
    )
    user = f"段落:\n```text\n{block_text[:3000]}\n```\n请提取知识点。"
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
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def _find_subject_root_id(topics: list[TopicNode], subject: str, language_id: str | None) -> str | None:
    # Find root by subject tag + facet:root, not by generic title
    for t in topics:
        tags = set(t.tags)
        if "facet:root" not in tags:
            continue
        if f"subject:{subject}" not in tags:
            continue
        if subject == "language" and language_id and f"language:{language_id}" not in tags:
            continue
        return t.topic_id
    # Fallback: any facet:root with matching title
    for t in topics:
        if "facet:root" in set(t.tags) and t.title.strip().lower() == subject.lower():
            return t.topic_id
    return None


def _link_to_topic(title: str, topics: list[TopicNode], topic_map: dict[str, str]) -> str | None:
    clean = title.strip()
    if clean in topic_map:
        return topic_map[clean]
    for t in topics:
        if t.title.strip() == clean:
            topic_map[clean] = t.topic_id
            return t.topic_id
    return None


def _process_exercise_blocks(
    *,
    backend: "SessionBackend",
    blocks: list[dict],
    chunks: list[TextUnit],
    topics: list[TopicNode],
    topic_map: dict[str, str],
    record: ResourceRecord,
    subject: str,
    language_id: str | None,
    profile: object,
    _proposal_tags: object,
) -> None:
    pass  # Exercises processed in segment builder


def _build_segments_from_scan(
    *,
    scan: dict,
    record: ResourceRecord,
    topics: list[TopicNode],
    topic_map: dict[str, str],
) -> list[ResourceSegment]:
    blocks = scan.get("blocks") or []
    segments: list[ResourceSegment] = []
    seg_index = 0

    for block in blocks:
        block_text = _extract_block_text(block, [])
        if not block_text and hasattr(block, "text"):
            block_text = block.get("summary", "")
        btype = block.get("type", "unknown")
        label = block.get("label", btype)

        seg_index += 1
        if btype in {"word_list", "appendix"}:
            segments.append(
                ResourceSegment(
                    segment_id=_segment_id(record.resource_id, seg_index),
                    start_ms=0, end_ms=None, label=btype,
                    status="unclassified", sequence_index=seg_index,
                    text=block.get("summary", block_text)[:500],
                    locator={"kind": "structured", "section_type": btype},
                    topic_id=None, proposal_id=None,
                    decision="unclassified", confidence=0.0,
                    reason=f"{btype} section skipped",
                )
            )
        else:
            matched_tid = None
            for title, tid in topic_map.items():
                if title.lower() in (label or "").lower() or title.lower() in (block.get("summary", "") or "").lower():
                    matched_tid = tid
                    break
            segments.append(
                ResourceSegment(
                    segment_id=_segment_id(record.resource_id, seg_index),
                    start_ms=0, end_ms=None, label="chunk",
                    status="classified" if matched_tid else "unclassified",
                    sequence_index=seg_index,
                    text=block.get("summary", label)[:500],
                    locator={"kind": "structured", "section_type": btype},
                    topic_id=matched_tid,
                    proposal_id=None,
                    decision="link" if matched_tid else "unclassified",
                    confidence=0.85,
                    reason="via structured scan" if matched_tid else "no topic extracted",
                )
            )
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
