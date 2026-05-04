from __future__ import annotations

import base64
import logging
import mimetypes
import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from src.api.schemas import (
    AudioTurnResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    EventInfo,
    EventListResponse,
    ExploreWindowOpenRequest,
    ExploreWindowResponse,
    HealthResponse,
    KnowledgeGraphResponse,
    MasteryInfo,
    MasteryListResponse,
    PageKnowledgeResponse,
    ProposalInfo,
    ProposalReviewRequest,
    ProposalReviewResponse,
    PushReviewRequest,
    PushReviewResponse,
    ReviewQueueItem,
    ResourceInfo,
    ResourceIngestionStatusResponse,
    ResourceSegmentListResponse,
    ResourceSegmentInfo,
    ResourceTeachingCueInfo,
    ResourceUploadResponse,
    ReviewQueueResponse,
    SessionLearningState,
    SessionListResponse,
    SessionProfile,
    SessionStateResponse,
    SessionSummary,
    StreamInterruptResponse,
    StreamTurnInitResponse,
    TextTurnRequest,
    TopicTeachingCueListResponse,
    TopicResourceListResponse,
    TopicInfo,
    TurnResponse,
)
from src.services.document_ingestion import ingest_document_resource

if TYPE_CHECKING:
    from src.services.session_backend import SessionBackend

API_VERSION = "1.3.0"
SINGLE_SESSION_ID = "default"
TURN_EVENT_KIND = "api_turn_completed"
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LoopTutor Frontend API",
    version=API_VERSION,
    description="Single-session frontend APIs with transactional state storage and on-demand memory retrieval.",
)

# 跨域放行
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@dataclass
class StreamJob:
    stream_id: str
    text: str
    stop_signal: threading.Event


class SingleSessionRuntime:
    def __init__(self, backend_factory: Callable[[], "SessionBackend"] | None = None) -> None:
        self._backend_factory = backend_factory or get_backend
        self._lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._stream_jobs: dict[str, StreamJob] = {}

    def load_state(self):
        backend = self._backend_factory()
        return backend.load_app_state(include_history=False)

    def turn_count(self) -> int:
        backend = self._backend_factory()
        return backend.get_learning_event_count(kind=TURN_EVENT_KIND)

    def events_cursor(self) -> int:
        backend = self._backend_factory()
        return backend.get_learning_event_count()

    def submit_text_turn(self, user_text: str) -> tuple[str, str, int, bytes, object, int]:
        backend = self._backend_factory()
        with self._lock:
            turn_id = self._next_turn_id(backend)
            reply_text, earned_points, reply_audio = backend.evaluate_and_speak(user_text)
            state = backend.load_app_state(include_history=False)
            backend.append_learning_event(
                kind=TURN_EVENT_KIND,
                payload={
                    "turn_id": turn_id,
                    "input_mode": "text",
                    "user_text": user_text,
                    "earned_points": earned_points,
                },
            )
            cursor = backend.get_learning_event_count()
            return turn_id, reply_text, earned_points, reply_audio, state, cursor

    def submit_audio_turn(self, audio_bytes: bytes) -> tuple[str, str, str, int, bytes, object, int]:
        backend = self._backend_factory()
        with self._lock:
            turn_id = self._next_turn_id(backend)
            recognized_text = backend.transcribe_audio(audio_bytes)
            reply_text, earned_points, reply_audio = backend.evaluate_and_speak(recognized_text)
            state = backend.load_app_state(include_history=False)
            backend.append_learning_event(
                kind=TURN_EVENT_KIND,
                payload={
                    "turn_id": turn_id,
                    "input_mode": "audio",
                    "recognized_text": recognized_text,
                    "earned_points": earned_points,
                },
            )
            cursor = backend.get_learning_event_count()
            return turn_id, recognized_text, reply_text, earned_points, reply_audio, state, cursor

    def init_stream_turn(self, user_text: str) -> tuple[StreamJob, str, str, int, object, int]:
        backend = self._backend_factory()
        with self._lock:
            turn_id = self._next_turn_id(backend)
            reply_text, earned_points = backend.evaluate_text_turn(user_text)
            state = backend.load_app_state(include_history=False)

            stream_id = f"stream_{uuid.uuid4().hex[:12]}"
            job = StreamJob(stream_id=stream_id, text=reply_text, stop_signal=threading.Event())
            with self._stream_lock:
                self._stream_jobs[stream_id] = job

            backend.append_learning_event(
                kind=TURN_EVENT_KIND,
                payload={
                    "turn_id": turn_id,
                    "input_mode": "text",
                    "audio_mode": "stream",
                    "user_text": user_text,
                    "earned_points": earned_points,
                    "stream_id": stream_id,
                },
            )
            cursor = backend.get_learning_event_count()
            return job, turn_id, reply_text, earned_points, state, cursor

    def get_stream_job(self, stream_id: str) -> StreamJob:
        with self._stream_lock:
            job = self._stream_jobs.get(stream_id)
            if job is None:
                raise KeyError(stream_id)
            return job

    def consume_stream_job(self, stream_id: str) -> None:
        with self._stream_lock:
            self._stream_jobs.pop(stream_id, None)

    def interrupt_stream(self, stream_id: str) -> bool:
        with self._stream_lock:
            job = self._stream_jobs.get(stream_id)
            if job is None:
                return False
            job.stop_signal.set()
            return True

    def push_review_topic(self, topic_id: str) -> tuple[object, bool]:
        backend = self._backend_factory()
        with self._lock:
            backend.inject_review_topic(topic_id)
            state = backend.load_app_state(include_history=False)
            queued = topic_id in state.learning.review_queue
            backend.append_learning_event(
                kind="review_topic_pushed",
                payload={"topic_id": topic_id, "queued": queued},
            )
            return state, queued

    def open_explore_window(self, minutes: int):
        backend = self._backend_factory()
        with self._lock:
            state = backend.load_app_state(include_history=False)
            cooldown_until = _parse_iso_ts(state.learning.explore_window_cooldown_until)
            if cooldown_until and cooldown_until > datetime.now(timezone.utc):
                backend.append_learning_event(
                    kind="explore_window_open_blocked",
                    payload={
                        "reason": "cooldown_active",
                        "cooldown_until": state.learning.explore_window_cooldown_until,
                    },
                )
                return state

            until = datetime.now(timezone.utc).timestamp() + (max(1, minutes) * 60)
            state.learning.explore_window_until = datetime.fromtimestamp(until, tz=timezone.utc).isoformat()
            state.learning.explore_window_cooldown_until = None
            backend.save_app_state(state)
            backend.append_learning_event(
                kind="explore_window_opened",
                payload={"minutes": max(1, minutes), "until": state.learning.explore_window_until},
            )
            return state

    def close_explore_window(self):
        backend = self._backend_factory()
        with self._lock:
            state = backend.force_close_explore_window(source="frontend_api")
            return state

    def get_events(self, *, after: int, limit: int) -> tuple[int, int, list[object]]:
        backend = self._backend_factory()
        start, next_cursor, events = backend.get_learning_events(after=after, limit=limit)
        return start, next_cursor, events

    @staticmethod
    def _next_turn_id(backend: "SessionBackend") -> str:
        next_turn = backend.get_learning_event_count(kind=TURN_EVENT_KIND) + 1
        return f"turn_{next_turn:06d}"


@lru_cache(maxsize=1)
def get_backend() -> "SessionBackend":
    from src.services.session_backend import SessionBackend
    return SessionBackend()


@lru_cache(maxsize=1)
def get_runtime() -> SingleSessionRuntime:
    return SingleSessionRuntime()


def _start_ingestion_task(target: Callable[[], None]) -> None:
    thread = threading.Thread(target=target, name="resource-ingestion", daemon=True)
    thread.start()


def _resource_segment_counts(record) -> dict[str, int]:
    counts = {
        "segment_count": len(record.segments),
        "classified_count": 0,
        "proposed_count": 0,
        "unclassified_count": 0,
        "parse_failed_count": 0,
        "unsupported_count": 0,
    }
    for segment in record.segments:
        if segment.status == "classified":
            counts["classified_count"] += 1
        elif segment.status == "proposed":
            counts["proposed_count"] += 1
        elif segment.status == "unclassified":
            counts["unclassified_count"] += 1
        elif segment.status in {"parse_failed", "ingestion_failed"}:
            counts["parse_failed_count"] += 1
        elif segment.status == "unsupported":
            counts["unsupported_count"] += 1
    return counts


def _build_ingestion_failed_segment(resource_id: str, media_type: str, error: str):
    from src.core.models import ResourceSegment

    return ResourceSegment(
        segment_id=f"{resource_id}_ingestion_failed_0",
        start_ms=0,
        end_ms=None,
        label="chunk",
        status="ingestion_failed",
        sequence_index=0,
        text=None,
        locator={"kind": media_type or "unknown"},
        decision="unclassified",
        confidence=0.0,
        reason=f"文档入库失败: {error[:120]}",
    )


@lru_cache(maxsize=1)
def get_max_text_chars() -> int:
    raw = os.getenv("API_TEXT_MAX_CHARS", "128").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 128
    return max(1, min(8192, value))


@lru_cache(maxsize=1)
def get_max_audio_bytes() -> int:
    raw = os.getenv("API_AUDIO_MAX_BYTES", "5242880").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 5242880
    return max(1024, min(25 * 1024 * 1024, value))


@app.get("/health", tags=["system"])
def health():
    backend = get_backend()
    return {
        "ok": True,
        "service": "looptutor-api",
        "version": API_VERSION,
        "arch_mode": getattr(backend, "learning_arch_mode", "unknown"),
    }


@app.get("/v1/session/state", response_model=SessionStateResponse, tags=["session"])
def get_session_state() -> SessionStateResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return _build_state_response(state=state, turn_count=runtime.turn_count(), events_cursor=runtime.events_cursor())


@app.post("/v1/session/input/text", response_model=TurnResponse, tags=["session"])
def submit_text_turn(payload: TextTurnRequest) -> TurnResponse:
    user_text = payload.text.strip()
    _validate_text(user_text)
    runtime = get_runtime()
    turn_id, reply_text, earned_points, reply_audio, state, cursor = runtime.submit_text_turn(user_text)
    return _build_turn_response(
        turn_id=turn_id,
        state=state,
        user_text=user_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
        events_cursor=cursor,
    )


@app.post("/v1/session/input/audio", response_model=AudioTurnResponse, tags=["session"])
async def submit_audio_turn(file: UploadFile = File(...)) -> AudioTurnResponse:
    audio_bytes = await file.read()
    _validate_audio(audio_bytes)
    runtime = get_runtime()
    turn_id, recognized_text, reply_text, earned_points, reply_audio, state, cursor = runtime.submit_audio_turn(audio_bytes)
    base = _build_turn_response(
        turn_id=turn_id,
        state=state,
        user_text=recognized_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio=reply_audio,
        events_cursor=cursor,
    )
    return AudioTurnResponse(recognized_text=recognized_text, **base.model_dump())


@app.post("/v1/session/input/audio/sentence", response_model=AudioTurnResponse, tags=["session", "realtime"])
async def submit_audio_sentence(file: UploadFile = File(...)) -> AudioTurnResponse:
    return await submit_audio_turn(file)


@app.post("/v1/session/input/text/realtime", response_model=StreamTurnInitResponse, tags=["session", "realtime"])
def submit_text_turn_realtime(payload: TextTurnRequest) -> StreamTurnInitResponse:
    user_text = payload.text.strip()
    _validate_text(user_text)
    runtime = get_runtime()
    job, turn_id, reply_text, earned_points, state, cursor = runtime.init_stream_turn(user_text)
    return StreamTurnInitResponse(
        session_id=SINGLE_SESSION_ID,
        turn_id=turn_id,
        reply_text=reply_text,
        earned_points=earned_points,
        current_topic_id=state.learning.current_topic_id,
        current_phase=str(state.learning.current_phase),
        total_score=state.learning.total_score,
        explore_window_until=state.learning.explore_window_until,
        stream_id=job.stream_id,
        events_cursor=cursor,
    )


@app.get("/v1/session/output/audio/stream/{stream_id}", tags=["session", "realtime"])
async def stream_reply_audio(stream_id: str):
    runtime = get_runtime()
    backend = get_backend()
    try:
        job = runtime.get_stream_job(stream_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"stream not found: {stream_id}") from exc

    async def _iterator() -> AsyncIterator[bytes]:
        try:
            async for chunk in backend.synthesize_reply_audio_stream(job.text, stop_signal=job.stop_signal):
                if job.stop_signal.is_set():
                    break
                yield chunk
        finally:
            runtime.consume_stream_job(stream_id)

    return StreamingResponse(_iterator(), media_type="audio/mpeg")


@app.post("/v1/session/output/audio/interrupt/{stream_id}", response_model=StreamInterruptResponse, tags=["session", "realtime"])
def interrupt_stream(stream_id: str) -> StreamInterruptResponse:
    runtime = get_runtime()
    interrupted = runtime.interrupt_stream(stream_id)
    return StreamInterruptResponse(
        session_id=SINGLE_SESSION_ID,
        stream_id=stream_id,
        interrupted=interrupted,
    )


@app.get("/v1/session/events", response_model=EventListResponse, tags=["session"])
def get_events(after: int = 0, limit: int = 50) -> EventListResponse:
    runtime = get_runtime()
    start, next_cursor, events = runtime.get_events(after=after, limit=limit)
    items = [
        EventInfo(
            event_index=start + idx + 1,
            ts=event.ts,
            kind=event.kind,
            payload=event.payload,
        )
        for idx, event in enumerate(events)
    ]
    return EventListResponse(
        session_id=SINGLE_SESSION_ID,
        after=max(0, after),
        next_cursor=next_cursor,
        events=items,
    )


@app.get("/v1/session/knowledge/page", response_model=PageKnowledgeResponse, tags=["session", "knowledge"])
def get_page_knowledge(topic_id: str, page: int = 1) -> PageKnowledgeResponse:
    backend = get_backend()
    topic = backend.get_topic(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail=f"topic_id not found: {topic_id}")

    page_number = max(1, page)
    fallback_segment = None
    fallback_resource = None
    for resource in backend.list_resources_related_to_topic(topic_id):
        for segment in resource.segments:
            if segment.status != "classified" or segment.topic_id != topic_id:
                continue
            if fallback_segment is None:
                fallback_segment = segment
                fallback_resource = resource
            locator = segment.locator or {}
            if locator.get("kind") != "pdf":
                continue
            page_start = int(locator.get("page_start") or page_number)
            page_end = int(locator.get("page_end") or page_start)
            if page_start <= page_number <= page_end:
                return _page_knowledge_response(topic_id=topic_id, page=page_number, resource=resource, segment=segment)

    if fallback_segment is not None and fallback_resource is not None:
        return _page_knowledge_response(topic_id=topic_id, page=page_number, resource=fallback_resource, segment=fallback_segment)

    return PageKnowledgeResponse(
        session_id=SINGLE_SESSION_ID,
        topic_id=topic_id,
        page=page_number,
        knowledge_text=f"这一页可以先围绕【{topic.title}】观察：你看到了哪些关键线索？",
    )


# ========== review queue now prefers topic_id and keeps content as compatibility alias ==========
@app.post("/v1/session/review/push", response_model=PushReviewResponse, tags=["session"])
def push_review_topic(payload: PushReviewRequest) -> PushReviewResponse:
    backend = get_backend()
    runtime = get_runtime()
    requested_topic_id = (payload.topic_id or payload.content or "").strip()
    if not requested_topic_id:
        raise HTTPException(status_code=400, detail="topic_id is required")

    topic = backend.get_topic(requested_topic_id) if hasattr(backend, "get_topic") else None
    if topic is None:
        state = runtime.load_state()
        topic = next((item for item in state.curriculum.topics if item.topic_id == requested_topic_id), None)
    if topic is None:
        raise HTTPException(status_code=404, detail=f"topic_id not found: {requested_topic_id}")

    state, queued = runtime.push_review_topic(requested_topic_id)
    return PushReviewResponse(
        session_id=SINGLE_SESSION_ID,
        queued=queued,
        topic_id=requested_topic_id,
        review_queue_size=len(state.learning.review_queue),
    )


@app.get("/v1/session/review-queue", response_model=ReviewQueueResponse, tags=["session"])
def get_review_queue() -> ReviewQueueResponse:
    backend = get_backend()
    runtime = get_runtime()
    state = runtime.load_state()
    items: list[ReviewQueueItem] = []
    for topic_id in state.learning.review_queue:
        topic = backend.get_topic(topic_id)
        resources = backend.list_resources_by_topic(topic_id)
        items.append(
            ReviewQueueItem(
                topic_id=topic_id,
                title=topic.title if topic is not None else topic_id,
                resource_count=len(resources),
            )
        )

    return ReviewQueueResponse(
        session_id=SINGLE_SESSION_ID,
        topics=list(state.learning.review_queue),
        size=len(state.learning.review_queue),
        items=items,
    )


@app.post("/v1/resource/upload", response_model=ResourceUploadResponse, tags=["resource"])
async def upload_resource(
    file: UploadFile = File(...),
    topic_id: str = Form(...),
    resource_name: str = Form(...),
    category: str = Form("learn"),
) -> ResourceUploadResponse:
    normalized_topic_id = topic_id.strip()
    if not normalized_topic_id:
        raise HTTPException(status_code=400, detail="topic_id is required")

    normalized_resource_name = resource_name.strip()
    if not normalized_resource_name:
        raise HTTPException(status_code=400, detail="resource_name is required")

    normalized_category = category.strip().lower() or "learn"
    if normalized_category not in {"learn", "review"}:
        raise HTTPException(status_code=400, detail="category must be learn or review")

    backend = get_backend()
    topic = backend.get_topic(normalized_topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail=f"topic_id not found: {normalized_topic_id}")

    original_name = (file.filename or "resource.bin").strip() or "resource.bin"
    safe_name = original_name.replace("/", "_").replace("\\", "_")

    data_root = Path(os.getenv("DATA_ROOT", "./data"))
    resource_dir = data_root / "resources"
    resource_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
    stored_path = resource_dir / stored_name

    with stored_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    mime_type = (file.content_type or "").strip() or (mimetypes.guess_type(original_name)[0] or "application/octet-stream")
    media_type = _infer_media_type(original_name, mime_type)
    record = backend.create_resource_record(
        topic_id=normalized_topic_id,
        resource_name=normalized_resource_name,
        category=normalized_category,
        media_type=media_type,
        mime_type=mime_type,
        original_filename=original_name,
        stored_path=str(stored_path.resolve()),
        size_bytes=stored_path.stat().st_size,
        ingestion_status="processing",
        ingestion_error=None,
        segments=[],
    )

    runtime = get_runtime()
    if normalized_category == "review":
        state, queued = runtime.push_review_topic(normalized_topic_id)
    else:
        state = runtime.load_state()
        queued = False

    backend.append_learning_event(
        kind="resource_uploaded",
        payload={
            "resource_id": record.resource_id,
            "topic_id": normalized_topic_id,
            "resource_name": normalized_resource_name,
            "category": normalized_category,
            "media_type": media_type,
            "original_filename": original_name,
            "stored_path": str(stored_path),
            "queued": queued,
            "ingestion_status": record.ingestion_status,
        },
    )

    logger.info(
        "upload accepted",
        extra={
            "resource_id": record.resource_id,
            "topic_id": normalized_topic_id,
            "media_type": media_type,
        },
    )
    _start_ingestion_task(lambda: _run_resource_ingestion(resource_id=record.resource_id, default_topic_id=normalized_topic_id))

    return ResourceUploadResponse(
        session_id=SINGLE_SESSION_ID,
        queued=queued,
        review_queue_size=len(state.learning.review_queue),
        resource=_resource_info(record, topic.title),
    )


def _run_resource_ingestion(*, resource_id: str, default_topic_id: str) -> None:
    backend = get_backend()
    record = backend.get_resource(resource_id)
    if record is None:
        logger.warning("ingestion skipped: resource missing", extra={"resource_id": resource_id})
        return

    logger.info("ingestion started", extra={"resource_id": resource_id, "media_type": record.media_type})

    def progress(event: str, payload: dict[str, object]) -> None:
        if event == "document_parsed":
            logger.info("document parsed chunk count", extra=payload)
        elif event == "chunk_classification_progress":
            logger.info("chunk classification progress", extra=payload)

    try:
        topics = backend.load_app_state(include_history=False).curriculum.topics
        segments = ingest_document_resource(
            backend=backend,
            record=record,
            topics=topics,
            default_topic_id=default_topic_id,
            progress_callback=progress,
        )
        backend.update_resource_ingestion(resource_id, status="completed", error=None)
        updated = backend.get_resource(resource_id)
        if updated is None:
            logger.warning("ingestion completed but resource missing", extra={"resource_id": resource_id})
            return
        counts = _resource_segment_counts(updated)
        backend.append_learning_event(
            kind="resource_ingested",
            payload={
                "resource_id": resource_id,
                "segment_count": counts["segment_count"],
                "classified_count": counts["classified_count"],
                "proposed_count": counts["proposed_count"],
                "unclassified_count": counts["unclassified_count"],
                "parse_failed_count": counts["parse_failed_count"],
                "unsupported_count": counts["unsupported_count"],
                "media_type": record.media_type,
            },
        )
        logger.info(
            "ingestion completed",
            extra={"resource_id": resource_id, "segment_count": len(segments), "media_type": record.media_type},
        )
    except Exception as exc:
        error = str(exc)[:500]
        failure_segments = [_build_ingestion_failed_segment(resource_id, record.media_type, error)]
        try:
            backend.replace_resource_segments(resource_id, failure_segments)
        except Exception:
            logger.exception("failed to persist ingestion failure segment", extra={"resource_id": resource_id})
        backend.update_resource_ingestion(resource_id, status="failed", error=error)
        logger.exception("ingestion failed", extra={"resource_id": resource_id, "media_type": record.media_type})


@app.get("/v1/resource/topics/{topic_id}", response_model=TopicResourceListResponse, tags=["resource"])
def get_topic_resources(topic_id: str) -> TopicResourceListResponse:
    backend = get_backend()
    topic = backend.get_topic(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail=f"topic_id not found: {topic_id}")

    resources = backend.list_resources_related_to_topic(topic_id)
    return TopicResourceListResponse(
        session_id=SINGLE_SESSION_ID,
        topic_id=topic.topic_id,
        topic_title=topic.title,
        resources=[_resource_info(resource, topic.title) for resource in resources],
    )


@app.get("/v1/resource/{resource_id}/ingestion-status", response_model=ResourceIngestionStatusResponse, tags=["resource"])
def get_resource_ingestion_status(resource_id: str) -> ResourceIngestionStatusResponse:
    backend = get_backend()
    record = backend.get_resource(resource_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"resource_id not found: {resource_id}")

    counts = _resource_segment_counts(record)
    return ResourceIngestionStatusResponse(
        resource_id=resource_id,
        status=record.ingestion_status,
        segment_count=counts["segment_count"],
        classified_count=counts["classified_count"],
        proposed_count=counts["proposed_count"],
        unclassified_count=counts["unclassified_count"],
        parse_failed_count=counts["parse_failed_count"],
        error=record.ingestion_error,
    )


@app.get("/v1/resource/topics/{topic_id}/teaching-cues", response_model=TopicTeachingCueListResponse, tags=["resource"])
def get_topic_teaching_cues(topic_id: str) -> TopicTeachingCueListResponse:
    backend = get_backend()
    topic = backend.get_topic(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail=f"topic_id not found: {topic_id}")

    cues: list[ResourceTeachingCueInfo] = []
    for resource in backend.list_resources_related_to_topic(topic_id):
        for segment in resource.segments:
            if segment.status != "classified" or segment.topic_id != topic_id:
                continue
            if not segment.guiding_question and not segment.teaching_hint:
                continue
            cues.append(
                ResourceTeachingCueInfo(
                    resource_id=resource.resource_id,
                    resource_name=resource.resource_name,
                    media_type=resource.media_type,
                    segment_id=segment.segment_id,
                    sequence_index=segment.sequence_index,
                    text=segment.text,
                    locator=segment.locator,
                    guiding_question=segment.guiding_question,
                    teaching_hint=segment.teaching_hint,
                    confidence=segment.confidence,
                )
            )

    return TopicTeachingCueListResponse(
        session_id=SINGLE_SESSION_ID,
        topic_id=topic.topic_id,
        topic_title=topic.title,
        cues=cues,
    )


@app.get("/v1/resource/{resource_id}/segments", response_model=ResourceSegmentListResponse, tags=["resource"])
def get_resource_segments(resource_id: str) -> ResourceSegmentListResponse:
    backend = get_backend()
    record = backend.get_resource(resource_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"resource_id not found: {resource_id}")

    return ResourceSegmentListResponse(
        resource_id=resource_id,
        segments=[_resource_segment_info(segment) for segment in record.segments],
    )


@app.get("/v1/resource/files/{resource_id}", tags=["resource"])
def get_resource_file(resource_id: str):
    backend = get_backend()
    record = backend.get_resource(resource_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"resource_id not found: {resource_id}")

    file_path = Path(record.stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="resource file missing")

    return FileResponse(path=file_path, media_type=record.mime_type, filename=record.original_filename)


@app.get("/v1/knowledge/graph", response_model=KnowledgeGraphResponse, tags=["knowledge"])
def get_knowledge_graph() -> KnowledgeGraphResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return _build_graph_response(state)


@app.get("/v1/knowledge/proposals", response_model=list[ProposalInfo], tags=["knowledge"])
def list_knowledge_proposals(status: str | None = None, trigger: str | None = None) -> list[ProposalInfo]:
    runtime = get_runtime()
    state = runtime.load_state()
    proposals = state.learning.graph_proposals
    if status:
        proposals = [proposal for proposal in proposals if proposal.status == status]
    if trigger:
        proposals = [proposal for proposal in proposals if proposal.trigger == trigger]
    return [_proposal_info(proposal) for proposal in proposals]


@app.post("/v1/knowledge/proposals/{proposal_id}/approve", response_model=ProposalReviewResponse, tags=["knowledge"])
def approve_knowledge_proposal(proposal_id: str, payload: ProposalReviewRequest) -> ProposalReviewResponse:
    backend = get_backend()
    try:
        _state, proposal, topic, relinked_count, rescanned_count = backend.approve_graph_proposal(
            proposal_id=proposal_id,
            title=payload.title,
            summary=payload.summary,
            parent_node_ids=payload.parent_node_ids,
            edge_type=payload.edge_type,
            difficulty=payload.difficulty,
            tags=payload.tags,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400 if "required" in str(exc) else 404, detail=str(exc)) from exc
    return ProposalReviewResponse(
        session_id=SINGLE_SESSION_ID,
        proposal=_proposal_info(proposal),
        topic=_topic_info(topic),
        relinked_segment_count=relinked_count,
        rescanned_segment_count=rescanned_count,
    )


@app.post("/v1/knowledge/proposals/{proposal_id}/reject", response_model=ProposalReviewResponse, tags=["knowledge"])
def reject_knowledge_proposal(proposal_id: str, payload: ProposalReviewRequest | None = None) -> ProposalReviewResponse:
    backend = get_backend()
    try:
        _state, proposal, updated_count = backend.reject_graph_proposal(
            proposal_id=proposal_id,
            reason=payload.reason if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProposalReviewResponse(
        session_id=SINGLE_SESSION_ID,
        proposal=_proposal_info(proposal),
        relinked_segment_count=updated_count,
        rescanned_segment_count=0,
    )


@app.get("/v1/session/mastery", response_model=MasteryListResponse, tags=["session"])
def get_mastery() -> MasteryListResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return MasteryListResponse(
        session_id=SINGLE_SESSION_ID,
        mastery=[_mastery_info(topic_id, mastery) for topic_id, mastery in state.learning.mastery_map.items()],
    )


@app.get("/v1/session/explore-window", response_model=ExploreWindowResponse, tags=["session"])
def get_explore_window() -> ExploreWindowResponse:
    runtime = get_runtime()
    state = runtime.load_state()
    return _build_explore_window_response(
        until_text=state.learning.explore_window_until,
        cooldown_text=state.learning.explore_window_cooldown_until,
    )


@app.post("/v1/session/explore-window/open", response_model=ExploreWindowResponse, tags=["session"])
def open_explore_window(payload: ExploreWindowOpenRequest) -> ExploreWindowResponse:
    runtime = get_runtime()
    state = runtime.open_explore_window(payload.minutes)
    return _build_explore_window_response(
        until_text=state.learning.explore_window_until,
        cooldown_text=state.learning.explore_window_cooldown_until,
    )


@app.post("/v1/session/explore-window/close", response_model=ExploreWindowResponse, tags=["session"])
def close_explore_window() -> ExploreWindowResponse:
    runtime = get_runtime()
    state = runtime.close_explore_window()
    return _build_explore_window_response(
        until_text=state.learning.explore_window_until,
        cooldown_text=state.learning.explore_window_cooldown_until,
    )


@app.post("/v1/sessions", response_model=CreateSessionResponse, tags=["sessions", "compat"])
def create_session_compat(payload: CreateSessionRequest | None = None) -> CreateSessionResponse:
    runtime = get_runtime()
    backend = get_backend()
    with runtime._lock:
        state = runtime.load_state()
        if payload:
            if payload.student_id:
                state.profile.student_id = payload.student_id
            if payload.display_name:
                state.profile.display_name = payload.display_name
            if payload.locale:
                state.profile.locale = payload.locale
            backend.save_app_state(state)
            state = backend.load_app_state(include_history=False)

    summary = _build_session_summary(turn_count=runtime.turn_count())
    state_resp = _build_state_response(state=state, turn_count=runtime.turn_count(), events_cursor=runtime.events_cursor())
    return CreateSessionResponse(session=summary, state=state_resp)


@app.get("/v1/sessions", response_model=SessionListResponse, tags=["sessions", "compat"])
def list_sessions_compat() -> SessionListResponse:
    runtime = get_runtime()
    return SessionListResponse(sessions=[_build_session_summary(turn_count=runtime.turn_count())])


@app.get("/v1/sessions/{session_id}/state", response_model=SessionStateResponse, tags=["sessions", "compat"])
def get_session_state_compat(session_id: str) -> SessionStateResponse:
    _ensure_default_session(session_id)
    return get_session_state()


@app.post("/v1/sessions/{session_id}/turns/text", response_model=TurnResponse, tags=["turns", "compat"])
def submit_text_turn_compat(session_id: str, payload: TextTurnRequest) -> TurnResponse:
    _ensure_default_session(session_id)
    return submit_text_turn(payload)


@app.post("/v1/sessions/{session_id}/turns/audio", response_model=AudioTurnResponse, tags=["turns", "compat"])
async def submit_audio_turn_compat(session_id: str, file: UploadFile = File(...)) -> AudioTurnResponse:
    _ensure_default_session(session_id)
    return await submit_audio_turn(file)


@app.get("/v1/sessions/{session_id}/events", response_model=EventListResponse, tags=["events", "compat"])
def get_events_compat(session_id: str, after: int = 0, limit: int = 50) -> EventListResponse:
    _ensure_default_session(session_id)
    return get_events(after=after, limit=limit)


@app.post("/v1/sessions/{session_id}/review-queue", response_model=PushReviewResponse, tags=["review", "compat"])
def push_review_topic_compat(session_id: str, payload: PushReviewRequest) -> PushReviewResponse:
    _ensure_default_session(session_id)
    return push_review_topic(payload)


@app.get("/v1/sessions/{session_id}/review-queue", response_model=ReviewQueueResponse, tags=["review", "compat"])
def get_review_queue_compat(session_id: str) -> ReviewQueueResponse:
    _ensure_default_session(session_id)
    return get_review_queue()


@app.get("/v1/sessions/{session_id}/graph", response_model=KnowledgeGraphResponse, tags=["knowledge", "compat"])
def get_graph_compat(session_id: str) -> KnowledgeGraphResponse:
    _ensure_default_session(session_id)
    return get_knowledge_graph()


@app.get("/v1/sessions/{session_id}/mastery", response_model=MasteryListResponse, tags=["mastery", "compat"])
def get_mastery_compat(session_id: str) -> MasteryListResponse:
    _ensure_default_session(session_id)
    return get_mastery()


@app.get("/v1/sessions/{session_id}/explore-window", response_model=ExploreWindowResponse, tags=["explore", "compat"])
def get_explore_window_compat(session_id: str) -> ExploreWindowResponse:
    _ensure_default_session(session_id)
    return get_explore_window()


@app.post("/v1/sessions/{session_id}/explore-window/open", response_model=ExploreWindowResponse, tags=["explore", "compat"])
def open_explore_window_compat(session_id: str, payload: ExploreWindowOpenRequest) -> ExploreWindowResponse:
    _ensure_default_session(session_id)
    return open_explore_window(payload)


@app.post("/v1/sessions/{session_id}/explore-window/close", response_model=ExploreWindowResponse, tags=["explore", "compat"])
def close_explore_window_compat(session_id: str) -> ExploreWindowResponse:
    _ensure_default_session(session_id)
    return close_explore_window()


def _ensure_default_session(session_id: str) -> None:
    if session_id != SINGLE_SESSION_ID:
        raise HTTPException(status_code=404, detail=f"single-session mode only supports: {SINGLE_SESSION_ID}")


def _build_state_response(*, state, turn_count: int, events_cursor: int) -> SessionStateResponse:
    return SessionStateResponse(
        session_id=SINGLE_SESSION_ID,
        profile=SessionProfile(
            student_id=state.profile.student_id,
            display_name=state.profile.display_name,
            locale=state.profile.locale,
        ),
        learning=SessionLearningState(
            current_topic_id=state.learning.current_topic_id,
            current_phase=str(state.learning.current_phase),
            total_score=state.learning.total_score,
            consecutive_correct=state.learning.consecutive_correct,
            consecutive_wrong=state.learning.consecutive_wrong,
            explore_window_until=state.learning.explore_window_until,
            explore_window_cooldown_until=state.learning.explore_window_cooldown_until,
            review_queue_size=len(state.learning.review_queue),
            history_event_count=events_cursor,
        ),
        topics=[_topic_info(topic) for topic in state.curriculum.topics],
        proposals=[_proposal_info(proposal) for proposal in state.learning.graph_proposals],
        mastery=[_mastery_info(topic_id, mastery) for topic_id, mastery in state.learning.mastery_map.items()],
        turn_count=turn_count,
        events_cursor=events_cursor,
    )


def _build_graph_response(state) -> KnowledgeGraphResponse:
    return KnowledgeGraphResponse(
        session_id=SINGLE_SESSION_ID,
        topics=[_topic_info(topic) for topic in state.curriculum.topics],
        proposals=[_proposal_info(proposal) for proposal in state.learning.graph_proposals],
        mastery=[_mastery_info(topic_id, mastery) for topic_id, mastery in state.learning.mastery_map.items()],
    )


def _build_turn_response(
    *,
    turn_id: str,
    state,
    user_text: str,
    reply_text: str,
    earned_points: int,
    reply_audio: bytes,
    events_cursor: int,
) -> TurnResponse:
    audio_base64 = base64.b64encode(reply_audio).decode("ascii") if reply_audio else None
    return TurnResponse(
        session_id=SINGLE_SESSION_ID,
        turn_id=turn_id,
        user_text=user_text,
        reply_text=reply_text,
        earned_points=earned_points,
        reply_audio_base64=audio_base64,
        current_topic_id=state.learning.current_topic_id,
        current_phase=str(state.learning.current_phase),
        total_score=state.learning.total_score,
        explore_window_until=state.learning.explore_window_until,
        events_cursor=events_cursor,
    )


def _build_explore_window_response(*, until_text: str | None, cooldown_text: str | None) -> ExploreWindowResponse:
    until = _parse_iso_ts(until_text)
    cooldown_until = _parse_iso_ts(cooldown_text)
    cooldown_remaining: int | None = None
    if cooldown_until is not None:
        remaining = int((cooldown_until - datetime.now(timezone.utc)).total_seconds())
        cooldown_remaining = remaining if remaining > 0 else 0

    if until is None:
        return ExploreWindowResponse(
            session_id=SINGLE_SESSION_ID,
            explore_window_until=until_text,
            active=False,
            remaining_seconds=None,
            cooldown_until=cooldown_text,
            cooldown_remaining_seconds=cooldown_remaining,
        )

    now = datetime.now(timezone.utc)
    remaining = int((until - now).total_seconds())
    if remaining <= 0:
        return ExploreWindowResponse(
            session_id=SINGLE_SESSION_ID,
            explore_window_until=until_text,
            active=False,
            remaining_seconds=0,
            cooldown_until=cooldown_text,
            cooldown_remaining_seconds=cooldown_remaining,
        )

    return ExploreWindowResponse(
        session_id=SINGLE_SESSION_ID,
        explore_window_until=until_text,
        active=True,
        remaining_seconds=remaining,
        cooldown_until=cooldown_text,
        cooldown_remaining_seconds=cooldown_remaining,
    )


def _build_session_summary(*, turn_count: int) -> SessionSummary:
    now = datetime.now(timezone.utc).isoformat()
    return SessionSummary(
        session_id=SINGLE_SESSION_ID,
        created_at=now,
        updated_at=now,
        turn_count=turn_count,
    )


def _topic_info(topic) -> TopicInfo:
    return TopicInfo(
        topic_id=topic.topic_id,
        title=topic.title,
        difficulty=topic.difficulty,
        prerequisite_ids=list(topic.prerequisite_ids),
        tags=list(topic.tags),
    )


def _proposal_info(record) -> ProposalInfo:
    return ProposalInfo(
        proposal_id=record.proposal_id,
        title=record.title,
        summary=record.summary,
        trigger=record.trigger,
        tags=list(getattr(record, "tags", [])),
        parent_node_ids=list(record.parent_node_ids),
        edge_type=record.edge_type,
        status=record.status,
        reason=record.reason,
        created_topic_id=record.created_topic_id,
        updated_ts=record.updated_ts,
    )


def _mastery_info(topic_id: str, mastery) -> MasteryInfo:
    return MasteryInfo(
        topic_id=topic_id,
        mastery_state=getattr(mastery, "mastery_state", "unknown"),
        depth_level=mastery.depth_level,
        stability_level=mastery.stability_level,
        success_count=mastery.success_count,
        success_streak=mastery.success_streak,
        spaced_success_count=mastery.spaced_success_count,
        last_success_ts=mastery.last_success_ts,
    )


def _resource_info(record, topic_title: str) -> ResourceInfo:
    return ResourceInfo(
        resource_id=record.resource_id,
        topic_id=record.topic_id,
        topic_title=topic_title,
        resource_name=record.resource_name,
        category=record.category,
        media_type=record.media_type,
        mime_type=record.mime_type,
        original_filename=record.original_filename,
        resource_url=f"/v1/resource/files/{record.resource_id}",
        size_bytes=record.size_bytes,
        created_ts=record.created_ts,
        ingestion_status=record.ingestion_status,
        ingestion_error=record.ingestion_error,
        segments=[_resource_segment_info(segment) for segment in record.segments],
    )


def _resource_segment_info(segment) -> ResourceSegmentInfo:
    return ResourceSegmentInfo(
        segment_id=segment.segment_id,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        label=segment.label,
        status=segment.status,
        sequence_index=segment.sequence_index,
        text=segment.text,
        locator=segment.locator,
        topic_id=segment.topic_id,
        proposal_id=segment.proposal_id,
        proposed_topic_title=segment.proposed_topic_title,
        decision=segment.decision,
        confidence=segment.confidence,
        reason=segment.reason,
        guiding_question=segment.guiding_question,
        teaching_hint=segment.teaching_hint,
    )


def _page_knowledge_response(*, topic_id: str, page: int, resource, segment) -> PageKnowledgeResponse:
    question = (segment.guiding_question or "").strip()
    hint = (segment.teaching_hint or "").strip()
    text = (segment.text or "").strip()
    parts = []
    if question:
        parts.append(question)
    if hint:
        parts.append(hint)
    if text:
        parts.append(f"这段材料提到：{text[:160]}")
    knowledge_text = "\n".join(parts) if parts else "这一页可以先观察材料里的关键词，再说说你发现了什么。"
    return PageKnowledgeResponse(
        session_id=SINGLE_SESSION_ID,
        topic_id=topic_id,
        page=page,
        knowledge_text=knowledge_text,
        resource_id=resource.resource_id,
        segment_id=segment.segment_id,
        guiding_question=segment.guiding_question,
        teaching_hint=segment.teaching_hint,
    )


def _infer_media_type(filename: str, mime_type: str) -> str:
    ext = Path(filename).suffix.lower()
    if mime_type.startswith("video/") or ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return "video"
    if mime_type.startswith("audio/") or ext in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}:
        return "audio"
    if mime_type.startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext == ".doc":
        return "doc"
    if ext == ".pptx":
        return "pptx"
    if ext == ".ppt":
        return "ppt"
    if ext in {".txt", ".md"}:
        return "txt"
    return "binary"


def _validate_text(text: str) -> None:
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")
    max_chars = get_max_text_chars()
    if len(text) > max_chars:
        raise HTTPException(status_code=400, detail=f"text too long, max chars: {max_chars}")


def _validate_audio(audio_bytes: bytes) -> None:
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio file is empty")
    max_bytes = get_max_audio_bytes()
    if len(audio_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"audio file too large, max bytes: {max_bytes}")


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
