from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend
    from src.services.document_ingestion import TextUnit


@dataclass
class SectionTopic:
    section_label: str
    section_type: str  # "lesson" | "word_list" | "exercise" | "appendix" | "unknown"
    text: str
    topic_candidates: list[str]
    is_fuzzy: bool = False
    bound_exercises: list[str] = field(default_factory=list)


SKIP_SECTION_TYPES = {"word_list", "appendix"}
MAX_DOC_CHARS = 24000
FUZZY_WORKERS = 4


def analyze_document_structure(
    *,
    backend: "SessionBackend",
    chunks: list["TextUnit"],
    subject: str,
    language_id: str | None = None,
) -> list[SectionTopic]:
    if not chunks:
        return []

    full_text = _build_full_text(chunks)
    raw_sections = _call_structure_llm(
        backend=backend, full_text=full_text,
        subject=subject, language_id=language_id,
    )
    if not raw_sections:
        return []

    sections = _build_sections(raw_sections, chunks)

    fuzzy_sections = [s for s in sections if s.is_fuzzy]
    if fuzzy_sections:
        _run_fuzzy_reading(
            backend=backend,
            sections=fuzzy_sections,
            subject=subject,
            language_id=language_id,
        )

    return sections


def _build_full_text(chunks: list["TextUnit"]) -> str:
    parts = [c.text for c in chunks if c.text]
    combined = "\n\n".join(parts)
    if len(combined) <= MAX_DOC_CHARS:
        return combined
    head = combined[:MAX_DOC_CHARS // 2]
    tail = combined[-(MAX_DOC_CHARS // 2):]
    return head + "\n\n[...中间部分已省略...]\n\n" + tail


def _call_structure_llm(
    *,
    backend: "SessionBackend",
    full_text: str,
    subject: str,
    language_id: str | None = None,
) -> list[dict]:
    lang_hint = f"语言: {language_id}\n" if language_id else ""
    system = (
        "你是教材结构分析助手。给定一份教学文档全文，完成四项任务：\n"
        "1. 识别文档结构：标记单元/课节/附录/单词表等章节分界点\n"
        "2. 为每段标注类型（lesson / word_list / exercise / appendix / unknown）\n"
        "3. 从每段提取 1-5 个核心知识点的标题作为 topic 候选\n"
        "4. 标记模糊段落（is_fuzzy: 无突出概念，需后续精读）\n\n"
        "【topic 筛选规则——至关重要】\n"
        "- 只提取可教学的知识点（定理、定律、公式、语法点、科学概念）\n"
        "- 不要提取：实验过程描述、课堂活动、观察现象、讨论题、方法论标题\n"
        "- 不要提取：仅作为章节标题但不含知识内容的标签\n"
        "- 举例：可提取「牛顿第一定律」；不可提取「实验：探究摩擦力」\n"
        f"当前学科: {subject}\n{lang_hint}"
        "返回一个 JSON 对象，含一个 sections 数组。每个元素格式：\n"
        '{"label": "章节标签", "type": "lesson|word_list|exercise|appendix|unknown", '
        '"topic_candidates": ["知识点头衔1", "知识点头衔2"], '
        '"is_fuzzy": false, "exercises": ["练习题文本1"]}'
    )

    user = (
        f"文档全文（前{min(len(full_text), MAX_DOC_CHARS)}字符）：\n"
        f"```text\n{full_text[:MAX_DOC_CHARS]}\n```\n\n"
        "请分析结构并返回 JSON。"
    )

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
        data = json.loads(content)
        if isinstance(data, dict) and "sections" in data:
            items = data["sections"]
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []
    except Exception:
        return []


def _build_sections(raw: list[dict], chunks: list["TextUnit"]) -> list[SectionTopic]:
    sections: list[SectionTopic] = []
    for item in raw:
        label = str(item.get("label", "")).strip()
        stype = str(item.get("type", "unknown")).strip().lower()
        if stype not in {"lesson", "word_list", "exercise", "appendix", "unknown"}:
            stype = "unknown"
        candidates = item.get("topic_candidates") or []
        if isinstance(candidates, list):
            candidates = [str(c).strip() for c in candidates if str(c).strip()]
        else:
            candidates = []
        is_fuzzy = bool(item.get("is_fuzzy", False))
        exercises = item.get("exercises") or []
        if isinstance(exercises, list):
            exercises = [str(e).strip() for e in exercises if str(e).strip()]
        else:
            exercises = []
        text = _extract_section_text(label, chunks)
        sections.append(
            SectionTopic(
                section_label=label or stype,
                section_type=stype,
                text=text,
                topic_candidates=candidates if stype not in SKIP_SECTION_TYPES else [],
                is_fuzzy=is_fuzzy and stype not in SKIP_SECTION_TYPES,
                bound_exercises=exercises,
            )
        )
    return sections


def _extract_section_text(label: str, chunks: list["TextUnit"]) -> str:
    if not label:
        return ""
    label_lower = label.lower()
    matched: list[str] = []
    for chunk in chunks:
        chunk_lower = (chunk.text or "").lower()
        if any(
            segment.strip().lower() in chunk_lower
            for segment in label_lower.split(" - ")
            if segment.strip()
        ):
            matched.append(chunk.text)
    if matched:
        return "\n".join(matched)
    return " ".join(c.text for c in chunks[:3]) if chunks else ""


def _run_fuzzy_reading(
    *,
    backend: "SessionBackend",
    sections: list[SectionTopic],
    subject: str,
    language_id: str | None = None,
) -> None:
    lang_hint = f"语言: {language_id}\n" if language_id else ""

    def _fuzzy_read_one(section: SectionTopic) -> None:
        if not section.text.strip():
            return
        system = (
            "你是一个教学文档精读助手。仔细阅读一段模糊段落，提取其中隐藏的核心概念。\n"
            f"学科: {subject}\n{lang_hint}"
            "返回 JSON: {'topic_candidates': ['关键词1', '关键词2']}"
        )
        user = f"段落:\n```text\n{section.text[:2000]}\n```\n请提取 topic 候选关键词。"
        try:
            response = backend.llm_skill.client.chat.completions.create(
                model=backend.llm_skill.model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                timeout=60.0,
            )
            content = (response.choices[0].message.content or "").strip()
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            data = json.loads(content)
            if isinstance(data, dict):
                cands = data.get("topic_candidates") or []
                if isinstance(cands, list):
                    section.topic_candidates = [
                        str(c).strip() for c in cands if str(c).strip()
                    ]
                    section.is_fuzzy = False
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=FUZZY_WORKERS) as executor:
        futures = {executor.submit(_fuzzy_read_one, s): s for s in sections}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass
