from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.core.models import ResourceRecord, ResourceSegment, TopicNode

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

    segments: list[ResourceSegment] = []
    for index, chunk in enumerate(chunks):
        segments.append(_classify_chunk(backend=backend, resource_id=record.resource_id, sequence_index=index, chunk=chunk, topics=topics))

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
) -> ResourceSegment:
    text = chunk.text.strip()
    topic_id: str | None = None
    confidence = 0.0
    reason = "未找到合适知识点"
    status = "unclassified"

    try:
        result = backend.llm_skill.classify_resource_chunk(chunk_text=text, topics=topics)
        if isinstance(result, dict):
            raw_topic_id = result.get("topic_id")
            topic_id = raw_topic_id if isinstance(raw_topic_id, str) and raw_topic_id else None
            raw_confidence = result.get("confidence", 0.0)
            try:
                confidence = max(0.0, min(1.0, float(raw_confidence)))
            except (TypeError, ValueError):
                confidence = 0.0
            raw_reason = result.get("reason", reason)
            if isinstance(raw_reason, str) and raw_reason.strip():
                reason = raw_reason.strip()[:80]
    except Exception as exc:
        reason = f"分类失败: {str(exc)[:60]}"

    valid_topic_ids = {topic.topic_id for topic in topics}
    if topic_id not in valid_topic_ids:
        topic_id = None
    if topic_id and confidence >= CLASSIFIED_THRESHOLD:
        status = "classified"
    else:
        topic_id = None
        status = "unclassified"

    return ResourceSegment(
        segment_id=_segment_id(resource_id, sequence_index),
        start_ms=0,
        end_ms=None,
        label="chunk",
        status=status,
        sequence_index=sequence_index,
        text=text,
        locator=dict(chunk.locator),
        topic_id=topic_id,
        confidence=confidence,
        reason=reason,
    )


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
        confidence=0.0,
        reason=reason[:80],
    )


def _segment_id(resource_id: str, sequence_index: int) -> str:
    return f"seg_{resource_id}_{sequence_index:04d}_{uuid.uuid4().hex[:6]}"
