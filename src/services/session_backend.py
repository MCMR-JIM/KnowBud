from __future__ import annotations

import os
import json
import time
import sqlite3
import re
from pathlib import Path
from dataclasses import dataclass, field
import datetime
from datetime import timezone
from typing import AsyncIterator

from src.core.enums import UserIntent, LearningPhase
from src.core.models import AppState, UserProfile, LearningState, CurriculumConfig, TopicNode, PendingQuestion, ErrorRecord, LearningEvent, GraphProposalRecord, ResourceRecord, ResourceSegment, NodeMastery
from src.agent.models import EdgeType, GraphMutationProposal
from src.core.decision_engine import DecisionEngine
from src.skills.base_skill import SkillContext
from src.skills.voice_io_skill import VoiceIOSkill
from src.skills.llm_tutor_skill import LLMTutorSkill
from src.agent.orchestrator import AgentOrchestrator
from src.agent.policy import AgentPolicyConfig
from src.agent.mastery_engine import MasteryEngine
from src.services.env_loader import load_project_env

@dataclass
class UIRenderBundle:
    play_path: Path | None = None
    audio_bytes: bytes | None = None
    show_question: object | None = None
    messages: list[str] = field(default_factory=list)

class SessionBackend:
    _ALLOWED_EDGE_TYPES: set[str] = {item.value for item in EdgeType}

    _PROPOSAL_RECORD_TRANSITIONS: dict[str, set[str]] = {
        "proposed": {"validated", "rejected", "shadow"},
        "validated": {"shadow", "rejected"},
        "shadow": {"active", "rejected"},
        "active": set(),
        "rejected": set(),
    }

    def __init__(self) -> None:
        load_project_env()
        data_root = Path(os.getenv("DATA_ROOT", "./data"))
        self.ctx = SkillContext(data_root=data_root)
        self.state_file = Path(os.getenv("STATE_FILE", "./data/state.json"))
        self.state_db_file = os.getenv("STATE_DB_FILE", "").strip()
        self.log_file = Path(os.getenv("DECISION_LOG_FILE", "./logs/decision_trace.jsonl"))
        self.audio_artifact_root = Path(os.getenv("AUDIO_ARTIFACT_ROOT", "./artifacts/audio"))
        self.learning_arch_mode = os.getenv("LEARNING_ARCH_MODE", "legacy").strip().lower()
        self.agent_policy = AgentPolicyConfig.from_env()
        self.explore_window_minutes = self.agent_policy.explore_window_minutes
        self.explore_window_cooldown_minutes = max(0, self.agent_policy.explore_window_cooldown_minutes)
        self.shadow_activate_observation_turns = max(1, self.agent_policy.shadow_activate_observation_turns)
        self.shadow_rollback_wrong_streak = max(1, self.agent_policy.shadow_rollback_wrong_streak)
        self.history_tail_limit = self._bounded_int_env("HISTORY_TAIL_LIMIT", default=200, lower=20, upper=2000)

        fail_th = int(os.getenv("FSM_FAIL_THRESHOLD", "3"))
        master_st = int(os.getenv("FSM_MASTER_STREAK", "3"))
        self.engine = DecisionEngine(fail_threshold=fail_th, master_streak=master_st)

        self.voice_skill = VoiceIOSkill(self.ctx, whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", "tiny"))
        self.llm_skill = LLMTutorSkill(
            self.ctx,
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )
        self.agent_orchestrator = (
            AgentOrchestrator(policy=self.agent_policy)
            if self.learning_arch_mode in {"agent", "hybrid"}
            else None
        )
        self.mastery_engine = MasteryEngine()

    def load_app_state(self, *, include_history: bool = True, history_limit: int | None = None) -> AppState:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            state = self._load_state_row(conn)
            if state is None:
                state = self._load_legacy_or_default_state()
                self._save_state_row(conn, state)
                self._migrate_legacy_events(conn, state)

            if include_history:
                limit = self.history_tail_limit if history_limit is None else max(0, history_limit)
                state.learning.history_logs = self._fetch_recent_events(conn, limit=limit)
            else:
                state.learning.history_logs = []

            return state

    def save_app_state(self, state: AppState) -> None:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            self._save_state_row(conn, state)

    def handle_text_event(self, intent: UserIntent, text: str | None = None) -> UIRenderBundle:
        state = self.load_app_state()
        if state.learning.current_phase == LearningPhase.PRACTICING and intent == UserIntent.SUBMIT_ANSWER and text:
            question = state.learning.pending_question or PendingQuestion(
                question_id="demo_q_01", stem="恐龙为什么会灭绝？", expected_format="open"
            )
            try:
                eval_result = self.llm_skill.evaluate_answer(question=question, user_answer=text)
                is_correct = eval_result.is_correct
                state.learning.last_evaluation = eval_result
            except Exception as exc:
                print(f"[SessionBackend] LLM调用失败，启用兜底: {exc}")
                is_correct = "陨石" in text or "火山" in text

            self._apply_answer_outcome(state=state, question=question, is_correct=is_correct)

        decision = self.engine.evaluate(state=state.learning, curriculum=state.curriculum, intent=intent, user_answer_text=text)

        if decision.state_delta.patch_learning:
            for k, v in decision.state_delta.patch_learning.items():
                setattr(state.learning, k, v)

        self._append_decision_log(intent=intent, action_kind=str(decision.action.kind), trace=decision.trace)

        self.save_app_state(state)
        return UIRenderBundle()

    # 🚀 新增：家长端调用，强制推送错题
    def inject_review_topic(self, topic_id: str):
        state = self.load_app_state()
        if topic_id not in state.learning.review_queue:
            state.learning.review_queue.append(topic_id)
            self.save_app_state(state)

    def get_topic(self, topic_id: str) -> TopicNode | None:
        state = self.load_app_state(include_history=False)
        return next((topic for topic in state.curriculum.topics if topic.topic_id == topic_id), None)

    def update_subject_root(
        self,
        topic_id: str,
        title: str,
        *,
        subject: str | None = None,
        language_id: str | None = None,
    ) -> TopicNode | None:
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("title is required")

        state = self.load_app_state(include_history=False)
        topic = next((item for item in state.curriculum.topics if item.topic_id == topic_id), None)
        if topic is None:
            return None

        topic.title = normalized_title
        if subject:
            preserved_tags = [
                tag for tag in topic.tags
                if not tag.startswith("subject:") and not tag.startswith("language:") and tag != "facet:root"
            ]
            topic.tags = [f"subject:{subject}", "facet:root", *preserved_tags]
            if language_id:
                topic.tags.append(f"language:{language_id}")
            topic.tags = list(dict.fromkeys(topic.tags))
        now = datetime.datetime.now(timezone.utc).isoformat()
        for proposal in state.learning.graph_proposals:
            if proposal.created_topic_id != topic_id:
                continue
            proposal.title = normalized_title
            if proposal.summary.startswith("学科：") or proposal.reason == "parent-created subject root":
                proposal.summary = f"学科：{normalized_title}"
            proposal.updated_ts = now

        self.save_app_state(state)
        return topic

    def delete_topic_subtree(self, topic_id: str) -> dict[str, int] | None:
        state = self.load_app_state(include_history=False)
        if not any(topic.topic_id == topic_id for topic in state.curriculum.topics):
            return None

        topics = list(state.curriculum.topics)
        topic_ids_to_delete: set[str] = set()

        def collect_children(parent_id: str) -> None:
            if parent_id in topic_ids_to_delete:
                return
            topic_ids_to_delete.add(parent_id)
            for topic in topics:
                if parent_id in topic.parent_ids or parent_id in topic.prerequisite_ids:
                    collect_children(topic.topic_id)

        collect_children(topic_id)

        state.curriculum.topics = [topic for topic in topics if topic.topic_id not in topic_ids_to_delete]
        for topic in state.curriculum.topics:
            topic.parent_ids = [item for item in topic.parent_ids if item not in topic_ids_to_delete]
            topic.prerequisite_ids = [item for item in topic.prerequisite_ids if item not in topic_ids_to_delete]

        for deleted_topic_id in topic_ids_to_delete:
            state.learning.mastery_map.pop(deleted_topic_id, None)
            state.learning.shadow_observation_map.pop(deleted_topic_id, None)
            state.learning.shadow_wrong_streak_map.pop(deleted_topic_id, None)

        state.learning.review_queue = [item for item in state.learning.review_queue if item not in topic_ids_to_delete]
        state.learning.error_book = [record for record in state.learning.error_book if record.topic_id not in topic_ids_to_delete]

        now = datetime.datetime.now(timezone.utc).isoformat()
        for proposal in state.learning.graph_proposals:
            if proposal.created_topic_id in topic_ids_to_delete:
                proposal.status = "rejected"
                proposal.reason = "parent-deleted subject"
            proposal.parent_node_ids = [item for item in proposal.parent_node_ids if item not in topic_ids_to_delete]
            proposal.prerequisite_node_ids = [item for item in proposal.prerequisite_node_ids if item not in topic_ids_to_delete]
            proposal.updated_ts = now

        self.save_app_state(state)

        resources_deleted = 0
        for resource in self.list_all_resources():
            if resource.topic_id in topic_ids_to_delete and self.delete_resource(resource.resource_id):
                resources_deleted += 1

        segments_unlinked = 0
        for resource in self.list_all_resources():
            changed = False
            for segment in resource.segments:
                if segment.topic_id not in topic_ids_to_delete:
                    continue
                segment.topic_id = None
                segment.status = "unclassified"
                segment.decision = "unclassified"
                segment.reason = "subject deleted"
                changed = True
                segments_unlinked += 1
            if changed:
                self.replace_resource_segments(resource.resource_id, resource.segments)

        return {
            "deleted_topic_count": len(topic_ids_to_delete),
            "deleted_resource_count": resources_deleted,
            "unlinked_segment_count": segments_unlinked,
        }

    def delete_resource(self, resource_id: str) -> bool:
        stored_path: str | None = None
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            row = conn.execute(
                "SELECT stored_path FROM resource_library WHERE resource_id = ?",
                (resource_id,),
            ).fetchone()
            if row is None:
                return False

            stored_path = str(row["stored_path"])
            conn.execute("DELETE FROM resource_segments WHERE resource_id = ?", (resource_id,))
            conn.execute("DELETE FROM resource_library WHERE resource_id = ?", (resource_id,))
            conn.commit()

        if stored_path:
            try:
                Path(stored_path).unlink(missing_ok=True)
            except OSError:
                pass

        return True

    def create_resource_record(
        self,
        *,
        topic_id: str,
        resource_name: str,
        category: str,
        media_type: str,
        mime_type: str,
        original_filename: str,
        stored_path: str,
        size_bytes: int,
        ingestion_status: str = "pending",
        ingestion_error: str | None = None,
        segments: list[ResourceSegment] | None = None,
    ) -> ResourceRecord:
        record = ResourceRecord(
            resource_id=f"res_{int(time.time() * 1000)}",
            topic_id=topic_id,
            resource_name=resource_name,
            category=category,
            media_type=media_type,
            mime_type=mime_type,
            original_filename=original_filename,
            stored_path=stored_path,
            size_bytes=size_bytes,
            created_ts=datetime.datetime.now(timezone.utc).isoformat(),
            ingestion_status=ingestion_status,
            ingestion_error=ingestion_error,
            segments=segments
            if segments is not None
            else [
                ResourceSegment(
                    segment_id="seg_full",
                    start_ms=0,
                    end_ms=None,
                    label="full",
                    status="confirmed",
                )
            ],
        )
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            self._insert_resource_row(conn, record)
        return record

    def update_resource_ingestion(
        self,
        resource_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            conn.execute(
                "UPDATE resource_library SET ingestion_status = ?, ingestion_error = ? WHERE resource_id = ?",
                (status, error, resource_id),
            )
            conn.commit()

    def list_resources_by_topic(self, topic_id: str) -> list[ResourceRecord]:
        return self.list_resources_related_to_topic(topic_id)

    def list_resources_related_to_topic(self, topic_id: str) -> list[ResourceRecord]:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            rows = conn.execute(
                """
                SELECT resource_id, topic_id, resource_name, category, media_type, mime_type,
                       original_filename, stored_path, size_bytes, created_ts, ingestion_status, ingestion_error, segments_json
                FROM resource_library
                WHERE resource_id IN (
                    SELECT DISTINCT r.resource_id
                    FROM resource_library r
                    LEFT JOIN resource_segments s ON s.resource_id = r.resource_id
                    WHERE r.topic_id = ? OR s.topic_id = ?
                )
                ORDER BY created_ts DESC, resource_id DESC
                """,
                (topic_id, topic_id),
            ).fetchall()
            return [self._resource_from_row(conn, row) for row in rows]

    def get_resource(self, resource_id: str) -> ResourceRecord | None:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            row = conn.execute(
                """
                SELECT resource_id, topic_id, resource_name, category, media_type, mime_type,
                       original_filename, stored_path, size_bytes, created_ts, ingestion_status, ingestion_error, segments_json
                FROM resource_library
                WHERE resource_id = ?
                """,
                (resource_id,),
            ).fetchone()
            if row is None:
                return None
            return self._resource_from_row(conn, row)

    def list_resource_segments(self, resource_id: str) -> list[ResourceSegment]:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            return self._load_resource_segments(conn, resource_id)

    def replace_resource_segments(self, resource_id: str, segments: list[ResourceSegment]) -> None:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            conn.execute("DELETE FROM resource_segments WHERE resource_id = ?", (resource_id,))
            for segment in segments:
                self._insert_resource_segment_row(conn, resource_id, segment)
            conn.execute(
                "UPDATE resource_library SET segments_json = ? WHERE resource_id = ?",
                (json.dumps([segment.model_dump() for segment in segments], ensure_ascii=False), resource_id),
            )
            conn.commit()

    def list_all_resources(self) -> list[ResourceRecord]:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            rows = conn.execute(
                """
                SELECT resource_id, topic_id, resource_name, category, media_type, mime_type,
                       original_filename, stored_path, size_bytes, created_ts, ingestion_status, ingestion_error, segments_json
                FROM resource_library
                ORDER BY created_ts DESC, resource_id DESC
                """
            ).fetchall()
            return [self._resource_from_row(conn, row) for row in rows]

    def create_graph_proposal_from_resource(
        self,
        *,
        title: str,
        summary: str,
        tags: list[str] | None = None,
        parent_node_ids: list[str],
        pending_parent_proposal_ids: list[str] | None = None,
        prerequisite_node_ids: list[str] | None = None,
        edge_type: str,
        reason: str,
    ) -> GraphProposalRecord:
        state = self.load_app_state(include_history=False)
        now = datetime.datetime.now(timezone.utc).isoformat()
        safe_edge_type = edge_type if edge_type in self._ALLOWED_EDGE_TYPES else "requires"
        proposal = GraphMutationProposal(
            proposal_id=f"proposal_{int(time.time() * 1000)}_{os.urandom(4).hex()}",
            trigger="resource_ingest",
            title=title.strip(),
            summary=summary.strip(),
            tags=list(dict.fromkeys(tags or [])),
            parent_node_ids=list(parent_node_ids),
            prerequisite_node_ids=list(dict.fromkeys(prerequisite_node_ids or [])),
            pending_parent_proposal_ids=list(dict.fromkeys(pending_parent_proposal_ids or [])),
            edge_type=EdgeType(safe_edge_type),
            reason=reason[:80],
        )
        self._upsert_graph_proposal(state=state, proposal=proposal)
        record = next(rec for rec in state.learning.graph_proposals if rec.proposal_id == proposal.proposal_id)
        record.created_ts = now
        record.updated_ts = now
        self.save_app_state(state)
        return record

    def approve_graph_proposal(
        self,
        *,
        proposal_id: str,
        title: str | None = None,
        summary: str | None = None,
        parent_node_ids: list[str] | None = None,
        edge_type: str | None = None,
        difficulty: int = 1,
        tags: list[str] | None = None,
        reason: str | None = None,
    ) -> tuple[AppState, GraphProposalRecord, TopicNode, int, int]:
        state = self.load_app_state(include_history=False)
        proposal = self._find_graph_proposal(state, proposal_id)
        if proposal is None:
            raise ValueError(f"proposal not found: {proposal_id}")
        if proposal.status == "rejected":
            raise ValueError("rejected proposal cannot be approved")

        now = datetime.datetime.now(timezone.utc).isoformat()
        valid_topic_ids = {topic.topic_id for topic in state.curriculum.topics}
        approved_title = (title or proposal.title).strip()
        if not approved_title:
            raise ValueError("title is required")
        approved_summary = (summary if summary is not None else proposal.summary).strip()
        parent_override = parent_node_ids is not None
        approved_parents = [item for item in (parent_node_ids if parent_override else proposal.parent_node_ids) if item in valid_topic_ids]
        if not parent_override:
            approved_parents = list(
                dict.fromkeys(
                    [
                        *approved_parents,
                        *self._resolve_pending_parent_topic_ids(
                            state=state,
                            pending_parent_proposal_ids=proposal.pending_parent_proposal_ids,
                        ),
                    ]
                )
            )
        approved_edge_type = edge_type if edge_type in self._ALLOWED_EDGE_TYPES else proposal.edge_type
        if approved_edge_type not in self._ALLOWED_EDGE_TYPES:
            approved_edge_type = "requires"
        approved_tags = list(dict.fromkeys([*proposal.tags, *(tags or [])]))

        created_topic_id = proposal.created_topic_id
        topic = next((item for item in state.curriculum.topics if item.topic_id == created_topic_id), None) if created_topic_id else None
        if topic is None:
            created_topic_id = self._new_topic_id(state, approved_title)
            topic = TopicNode(
                topic_id=created_topic_id,
                title=approved_title,
                difficulty=max(1, min(5, difficulty)),
                parent_ids=list(approved_parents) if approved_edge_type != "requires" else [],
                prerequisite_ids=list(dict.fromkeys(
                    pid for pid in (
                        *(approved_parents if approved_edge_type == "requires" else []),
                        *(p for p in getattr(proposal, "prerequisite_node_ids", []) if p in valid_topic_ids)
                    )
                    if pid != created_topic_id  # never self-reference
                )),
                tags=list(dict.fromkeys([*approved_tags, "resource-approved", "active"])),
            )
            state.curriculum.topics.append(topic)
            state.learning.mastery_map.setdefault(created_topic_id, NodeMastery(mastery_state="unknown"))
        else:
            topic.title = approved_title
            topic.difficulty = max(1, min(5, difficulty))
            if approved_edge_type == "requires":
                topic.prerequisite_ids = list(dict.fromkeys([*(getattr(topic, "prerequisite_ids", [])), *approved_parents]))
            else:
                topic.parent_ids = list(dict.fromkeys([*(getattr(topic, "parent_ids", [])), *approved_parents]))
            topic.prerequisite_ids = list(dict.fromkeys(
                pid for pid in (
                    *(getattr(topic, "prerequisite_ids", [])),
                    *(p for p in getattr(proposal, "prerequisite_node_ids", []) if p in valid_topic_ids)
                )
                if pid != topic.topic_id  # never self-reference
            ))
            topic.tags = list(dict.fromkeys([*topic.tags, *approved_tags, "resource-approved", "active"]))

        proposal.title = approved_title
        proposal.summary = approved_summary
        proposal.tags = approved_tags
        proposal.parent_node_ids = approved_parents
        if parent_override:
            proposal.pending_parent_proposal_ids = []
        proposal.edge_type = approved_edge_type
        proposal.created_topic_id = created_topic_id
        self._activate_proposal_record(proposal, reason=(reason or "approved resource proposal")[:80])
        proposal.updated_ts = now
        self._propagate_approved_parent_to_child_proposals(
            state=state,
            parent_proposal_id=proposal_id,
            parent_topic_id=created_topic_id,
            updated_ts=now,
        )
        self.save_app_state(state)

        relinked_count = self._relink_segments_for_approved_proposal(proposal_id=proposal_id, topic_id=created_topic_id)
        rescanned_count = self._rescan_segments_for_topic(topic_id=created_topic_id)
        self.append_learning_event(
            kind="graph_proposal_approved",
            payload={
                "proposal_id": proposal_id,
                "topic_id": created_topic_id,
                "title": approved_title,
                "relinked_segment_count": relinked_count,
                "rescanned_segment_count": rescanned_count,
            },
        )
        return self.load_app_state(include_history=False), proposal, topic, relinked_count, rescanned_count

    def reject_graph_proposal(self, *, proposal_id: str, reason: str | None = None) -> tuple[AppState, GraphProposalRecord, int]:
        state = self.load_app_state(include_history=False)
        proposal = self._find_graph_proposal(state, proposal_id)
        if proposal is None:
            raise ValueError(f"proposal not found: {proposal_id}")
        if proposal.status != "rejected":
            self._transition_proposal_record(proposal, to_status="rejected", reason=(reason or "rejected resource proposal")[:80])
            proposal.updated_ts = datetime.datetime.now(timezone.utc).isoformat()
            self.save_app_state(state)
        updated_count = self._mark_segments_for_rejected_proposal(proposal_id=proposal_id, reason=proposal.reason)
        self.append_learning_event(
            kind="graph_proposal_rejected",
            payload={"proposal_id": proposal_id, "updated_segment_count": updated_count, "reason": proposal.reason},
        )
        return self.load_app_state(include_history=False), proposal, updated_count

    @staticmethod
    def _find_graph_proposal(state: AppState, proposal_id: str) -> GraphProposalRecord | None:
        return next((rec for rec in state.learning.graph_proposals if rec.proposal_id == proposal_id), None)

    @staticmethod
    def _resolve_pending_parent_topic_ids(*, state: AppState, pending_parent_proposal_ids: list[str]) -> list[str]:
        valid_topic_ids = {topic.topic_id for topic in state.curriculum.topics}
        proposal_by_id = {proposal.proposal_id: proposal for proposal in state.learning.graph_proposals}
        resolved: list[str] = []
        for proposal_id in pending_parent_proposal_ids:
            parent_proposal = proposal_by_id.get(proposal_id)
            if parent_proposal is None or not parent_proposal.created_topic_id:
                continue
            if parent_proposal.created_topic_id in valid_topic_ids:
                resolved.append(parent_proposal.created_topic_id)
        return list(dict.fromkeys(resolved))

    @staticmethod
    def _propagate_approved_parent_to_child_proposals(
        *,
        state: AppState,
        parent_proposal_id: str,
        parent_topic_id: str,
        updated_ts: str,
    ) -> None:
        topic_by_id = {topic.topic_id: topic for topic in state.curriculum.topics}
        for proposal in state.learning.graph_proposals:
            if parent_proposal_id not in proposal.pending_parent_proposal_ids:
                continue
            if parent_topic_id not in proposal.parent_node_ids:
                proposal.parent_node_ids.append(parent_topic_id)
                proposal.updated_ts = updated_ts
            if parent_proposal_id in proposal.pending_parent_proposal_ids:
                proposal.pending_parent_proposal_ids = [
                    item for item in proposal.pending_parent_proposal_ids if item != parent_proposal_id
                ]
                proposal.updated_ts = updated_ts
            if not proposal.created_topic_id:
                continue
            topic = topic_by_id.get(proposal.created_topic_id)
            if topic is not None:
                if proposal.edge_type == "requires":
                    if parent_topic_id not in topic.prerequisite_ids:
                        topic.prerequisite_ids.append(parent_topic_id)
                else:
                    if parent_topic_id not in getattr(topic, "parent_ids", []):
                        if not hasattr(topic, "parent_ids"):
                            topic.parent_ids = []
                        topic.parent_ids.append(parent_topic_id)

    def _activate_proposal_record(self, rec: GraphProposalRecord, *, reason: str) -> None:
        if rec.status == "proposed":
            self._transition_proposal_record(rec, to_status="validated", reason=reason)
        if rec.status == "validated":
            self._transition_proposal_record(rec, to_status="shadow", reason=reason)
        if rec.status == "shadow":
            self._transition_proposal_record(rec, to_status="active", reason=reason)
        if rec.status == "active":
            rec.reason = reason

    @staticmethod
    def _new_topic_id(state: AppState, title: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", title).strip("_").lower()[:32]
        base = f"auto_{slug}" if slug else "auto_topic"
        existing = {topic.topic_id for topic in state.curriculum.topics}
        if base not in existing:
            return base
        index = 2
        while f"{base}_{index}" in existing:
            index += 1
        return f"{base}_{index}"

    def _relink_segments_for_approved_proposal(self, *, proposal_id: str, topic_id: str) -> int:
        updated = 0
        for resource in self.list_all_resources():
            changed = False
            for segment in resource.segments:
                if segment.proposal_id != proposal_id:
                    continue
                segment.status = "classified"
                segment.decision = "link"
                segment.topic_id = topic_id
                segment.confidence = max(segment.confidence, 0.75)
                segment.reason = "proposal approved and linked to new topic"
                changed = True
                updated += 1
            if changed:
                self.replace_resource_segments(resource.resource_id, resource.segments)
        return updated

    def _mark_segments_for_rejected_proposal(self, *, proposal_id: str, reason: str) -> int:
        updated = 0
        for resource in self.list_all_resources():
            changed = False
            for segment in resource.segments:
                if segment.proposal_id != proposal_id:
                    continue
                segment.status = "unclassified"
                segment.decision = "unclassified"
                segment.topic_id = None
                segment.proposal_id = None
                segment.reason = reason or "proposal rejected"
                changed = True
                updated += 1
            if changed:
                self.replace_resource_segments(resource.resource_id, resource.segments)
        return updated

    def _rescan_segments_for_topic(self, *, topic_id: str) -> int:
        state = self.load_app_state(include_history=False)
        topics = state.curriculum.topics
        if not any(topic.topic_id == topic_id for topic in topics):
            return 0

        updated = 0
        for resource in self.list_all_resources():
            changed = False
            for segment in resource.segments:
                if segment.topic_id or segment.status not in {"unclassified", "proposed"}:
                    continue
                text = (segment.text or "").strip()
                if not text:
                    continue
                try:
                    result = self.llm_skill.classify_or_propose_resource_chunk(
                        chunk_text=text,
                        topics=topics,
                        default_parent_topic_id=topic_id,
                    )
                except Exception:
                    continue
                if not isinstance(result, dict):
                    continue
                if result.get("decision") != "link" or result.get("topic_id") != topic_id:
                    continue
                try:
                    confidence = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
                except (TypeError, ValueError):
                    confidence = 0.0
                if confidence < 0.55:
                    continue
                segment.status = "classified"
                segment.decision = "link"
                segment.topic_id = topic_id
                segment.confidence = confidence
                segment.reason = str(result.get("reason") or "linked after proposal approval")[:80]
                if isinstance(result.get("guiding_question"), str):
                    segment.guiding_question = str(result["guiding_question"]).strip()[:60] or segment.guiding_question
                if isinstance(result.get("teaching_hint"), str):
                    segment.teaching_hint = str(result["teaching_hint"]).strip()[:80] or segment.teaching_hint
                changed = True
                updated += 1
            if changed:
                self.replace_resource_segments(resource.resource_id, resource.segments)
        return updated

    def transcribe_audio(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""

        self._save_audio_artifact(audio_bytes, bucket="incoming", suffix=".wav")

        text = self.voice_skill.transcribe(audio_bytes)
        return text if text else "（哎呀，没听清，能再说一遍吗？）"

    def synthesize_reply_audio(self, text: str) -> bytes:
        if not text:
            return b""
        
        # ⚠️ 修复：移除原本导致 asyncio 冲突的同步调用
        # 前端已切换至流式接口 (synthesize_reply_audio_stream)
        # 此处仅作打桩兼容，直接返回空字节流即可避免事件循环崩溃
        return b""

    async def synthesize_reply_audio_stream(
        self,
        text: str,
        *,
        stop_signal,
    ) -> AsyncIterator[bytes]:
        if not text:
            return

        voice = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
        chunk_collector = bytearray()
        try:
            async for chunk in self.voice_skill.synthesize_plain_stream(text, voice=voice):
                if stop_signal is not None and stop_signal.is_set():
                    break
                if not chunk:
                    continue
                chunk_collector.extend(chunk)
                yield chunk
        except Exception as exc:
            print(f"流式语音合成失败: {exc}")
            return

        if chunk_collector:
            self._save_audio_artifact(bytes(chunk_collector), bucket="outgoing", suffix=".mp3")

    def evaluate_and_speak(self, user_text: str) -> tuple[str, int, bytes]:
        reply_text, earned_points = self.evaluate_text_turn(user_text)
        reply_audio = self.synthesize_reply_audio(reply_text)
        return reply_text, earned_points, reply_audio

    def evaluate_text_turn(self, user_text: str) -> tuple[str, int]:
        if self.agent_orchestrator is not None:
            return self._evaluate_text_turn_agent(user_text)
        return self.evaluate_student_answer(user_text)

    def _evaluate_and_speak_agent(self, user_text: str) -> tuple[str, int, bytes]:
        reply_text, earned_points = self._evaluate_text_turn_agent(user_text)
        reply_audio = self.synthesize_reply_audio(reply_text)
        return reply_text, earned_points, reply_audio

    def _evaluate_text_turn_agent(self, user_text: str) -> tuple[str, int]:
        state = self.load_app_state()
        window_ended_now = self._consume_explore_window_expiry(state)
        decision = self.agent_orchestrator.process_turn(state=state, user_text=user_text)

        if decision.transition_from_topic_id != decision.transition_to_topic_id:
            self._append_learning_event(
                state=state,
                kind="topic_transition",
                payload={
                    "from": decision.transition_from_topic_id,
                    "to": decision.transition_to_topic_id,
                    "trace": decision.routing.trace,
                },
            )

        if decision.should_answer_directly:
            earned_points = max(0, decision.earned_points)
            if earned_points:
                state.learning.total_score += earned_points
            if decision.proposal is not None:
                self._upsert_graph_proposal(state=state, proposal=decision.proposal)
                self._append_learning_event(
                    state=state,
                    kind="graph_proposal",
                    payload={
                        "proposal_id": decision.proposal.proposal_id,
                        "title": decision.proposal.title,
                        "status": decision.proposal.status.value,
                        "reason": decision.proposal.reason,
                        "created_topic_id": decision.proposal.created_topic_id,
                    },
                )
            self.save_app_state(state)
            self._append_decision_log(
                intent=UserIntent.SUBMIT_ANSWER,
                action_kind="AGENT_DIRECT_REPLY",
                trace=decision.routing.trace,
            )
            reply_text = decision.reply_hint or "这个问题很有趣，我们先记下来，稍后深入探索。"
        else:
            self.save_app_state(state)
            reply_text, earned_points = self.evaluate_student_answer(user_text)
            if decision.reply_hint:
                reply_text = f"{decision.reply_hint}\n\n{reply_text}"

        if window_ended_now:
            reply_text = f"探索时间结束啦，我们回到主线继续学习。\n\n{reply_text}"
        return reply_text, earned_points

    def _save_audio_artifact(self, audio_bytes: bytes, *, bucket: str, suffix: str) -> Path | None:
        if not audio_bytes:
            return None

        try:
            bucket_dir = self.audio_artifact_root / bucket
            bucket_dir.mkdir(parents=True, exist_ok=True)
            file_name = f"{bucket}_{int(time.time() * 1000)}{suffix}"
            file_path = bucket_dir / file_name
            file_path.write_bytes(audio_bytes)
            return file_path
        except Exception as exc:
            print(f"音频保存失败: {exc}")
            return None

    def generate_proactive_question(self) -> str:
        state = self.load_app_state()
        topic_title = state.curriculum.topics[0].title if state.curriculum.topics else "新知识"
        return f"准备好探索【{topic_title}】了吗？看视频的时候要仔细哦，一会我要考考你！"

    def evaluate_student_answer(self, user_text: str) -> tuple[str, int]:
        state = self.load_app_state()
        question = state.learning.pending_question or PendingQuestion(question_id="demo_q_01", stem="恐龙为什么会灭绝？", expected_format="open")
        topic_id = state.learning.current_topic_id or question.question_id
        try:
            eval_result = self.llm_skill.evaluate_answer(question=question, user_answer=user_text)
            is_correct = eval_result.is_correct
            state.learning.last_evaluation = eval_result
            reply_text = getattr(eval_result, "feedback_text", "说得太棒了！" if is_correct else "差一点点，再想想？") 
        except Exception as exc:
            print(f"[SessionBackend] 评估失败，启用兜底: {exc}")
            is_correct = "陨石" in user_text or "火山" in user_text
            reply_text = "有道理！跟陨石或火山有关哦！" if is_correct else "好像不太对，是不是跟陨石有关？"

        self._apply_answer_outcome(state=state, question=question, is_correct=is_correct)
        earned_points = 20 if is_correct else 5
        state.learning.total_score += earned_points

        mastery_update = self.mastery_engine.update_from_answer(
            state=state.learning,
            topic_id=topic_id,
            user_text=user_text,
            is_correct=is_correct,
        )
        if mastery_update.mastered_now:
            reply_text = f"{reply_text}\n\n你已经开始会结合应用这个知识点了！"

        if mastery_update.should_open_explore_window:
            opened = self._open_explore_window(state)
            if opened:
                reply_text = f"{reply_text}\n\n🎁 奖励时间开启：接下来 {self.explore_window_minutes} 分钟你可以自由探索提问。"
            else:
                reply_text = f"{reply_text}\n\n你又有新进步了！探索奖励在冷却中，我们继续主线挑战。"

        expanded_count = 0
        if self.agent_orchestrator is not None and mastery_update.true_mastered_now:
            expanded_count = self._auto_expand_from_mastery(state=state, topic_id=topic_id)
            if expanded_count > 0:
                reply_text = f"{reply_text}\n\n我还为你自动扩展了 {expanded_count} 个进阶分支，我们可以继续挑战更深入的问题。"

        shadow_lifecycle = None
        if self.agent_orchestrator is not None:
            shadow_lifecycle = self._update_shadow_lifecycle(state=state, topic_id=topic_id, is_correct=is_correct)
            if shadow_lifecycle.get("rolled_back"):
                reply_text = f"{reply_text}\n\n这个新分支我们先放回观察区，等你准备好再挑战。"

        if self.agent_orchestrator is not None:
            promoted = bool(shadow_lifecycle and shadow_lifecycle.get("promoted"))
            if promoted:
                reply_text = f"{reply_text}\n\n你已经把这个新知识点学稳了，我已将它转入主学习网。"

        decision = self.engine.evaluate(
            state=state.learning,
            curriculum=state.curriculum,
            intent=UserIntent.SUBMIT_ANSWER,
            user_answer_text=user_text,
        )
        if decision.state_delta.patch_learning:
            for k, v in decision.state_delta.patch_learning.items():
                setattr(state.learning, k, v)

        self._append_decision_log(
            intent=UserIntent.SUBMIT_ANSWER,
            action_kind=str(decision.action.kind),
            trace=decision.trace,
        )
        self._append_learning_event(
            state=state,
            kind="mastery_update",
            payload={
                "topic_id": topic_id,
                "mastered_now": mastery_update.mastered_now,
                "true_mastered_now": mastery_update.true_mastered_now,
                "open_explore_window": mastery_update.should_open_explore_window,
                "mastery_state": state.learning.mastery_map.get(topic_id).mastery_state if topic_id in state.learning.mastery_map else None,
                "auto_expanded": expanded_count,
                "shadow_observation_count": state.learning.shadow_observation_map.get(topic_id, 0),
                "shadow_wrong_streak": state.learning.shadow_wrong_streak_map.get(topic_id, 0),
                "shadow_rolled_back": bool(shadow_lifecycle and shadow_lifecycle.get("rolled_back")),
            },
        )
        self.save_app_state(state)
        return reply_text, earned_points

    def append_learning_event(self, *, kind: str, payload: dict[str, object], audio_file_path: str | None = None) -> int:
        event = LearningEvent(
            ts=datetime.datetime.now(timezone.utc).isoformat(),
            kind=kind,
            payload=payload,
            audio_file_path=audio_file_path,
        )
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            return self._insert_event_row(conn, event)

    def get_learning_events(self, *, after: int, limit: int) -> tuple[int, int, list[LearningEvent]]:
        start = max(0, after)
        capped_limit = min(max(1, limit), 200)
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            rows = conn.execute(
                """
                SELECT event_id, ts, kind, payload_json, audio_file_path
                FROM learning_events
                WHERE event_id > ?
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (start, capped_limit),
            ).fetchall()

        events = [self._event_from_row(row) for row in rows]
        next_cursor = int(rows[-1]["event_id"]) if rows else start
        return start, next_cursor, events

    def get_learning_event_count(self, *, kind: str | None = None) -> int:
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            if kind:
                row = conn.execute(
                    "SELECT COUNT(*) FROM learning_events WHERE kind = ?",
                    (kind,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM learning_events").fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _apply_answer_outcome(*, state: AppState, question: PendingQuestion, is_correct: bool) -> None:
        if is_correct:
            state.learning.consecutive_correct += 1
            state.learning.consecutive_wrong = 0
            return

        state.learning.consecutive_wrong += 1
        state.learning.consecutive_correct = 0
        existing_ids = [e.topic_id for e in state.learning.error_book]
        if question.question_id not in existing_ids:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            state.learning.error_book.append(
                ErrorRecord(topic_id=question.question_id, stem=question.stem, first_error_time=now_str)
            )

    def _append_decision_log(self, *, intent: UserIntent, action_kind: str, trace: str) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            log_entry = {"intent": str(intent), "action_kind": action_kind, "trace": trace}
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def _append_learning_event(self, *, state: AppState, kind: str, payload: dict[str, object]) -> None:
        event = LearningEvent(
            ts=datetime.datetime.now(timezone.utc).isoformat(),
            kind=kind,
            payload=payload,
        )
        state.learning.history_logs.append(event)
        with self._db_connection() as conn:
            self._ensure_storage_initialized(conn)
            self._insert_event_row(conn, event)

    def _open_explore_window(self, state: AppState) -> bool:
        now = datetime.datetime.now(timezone.utc)
        cooldown_until = self._parse_iso_datetime(state.learning.explore_window_cooldown_until)
        if cooldown_until is not None and cooldown_until > now:
            self._append_learning_event(
                state=state,
                kind="explore_window_open_blocked",
                payload={
                    "reason": "cooldown_active",
                    "cooldown_until": state.learning.explore_window_cooldown_until,
                },
            )
            return False

        until = now + datetime.timedelta(minutes=max(1, self.explore_window_minutes))
        state.learning.explore_window_until = until.isoformat()
        state.learning.explore_window_cooldown_until = None
        return True

    def force_close_explore_window(self, *, source: str) -> AppState:
        state = self.load_app_state()
        if state.learning.explore_window_until is None:
            return state

        state.learning.explore_window_until = None
        state.learning.explore_window_cooldown_until = self._next_cooldown_until()
        self._append_learning_event(
            state=state,
            kind="explore_window_closed",
            payload={
                "source": source,
                "cooldown_until": state.learning.explore_window_cooldown_until,
            },
        )
        self.save_app_state(state)
        return state

    def _upsert_graph_proposal(self, *, state: AppState, proposal) -> None:
        now = datetime.datetime.now(timezone.utc).isoformat()
        target_status = proposal.status.value
        for rec in state.learning.graph_proposals:
            if rec.proposal_id == proposal.proposal_id:
                rec.title = proposal.title
                rec.summary = proposal.summary
                rec.tags = list(dict.fromkeys(proposal.tags))
                rec.parent_node_ids = list(proposal.parent_node_ids)
                rec.prerequisite_node_ids = list(dict.fromkeys(getattr(proposal, "prerequisite_node_ids", [])))
                rec.pending_parent_proposal_ids = list(dict.fromkeys(proposal.pending_parent_proposal_ids))
                rec.edge_type = proposal.edge_type.value
                self._transition_proposal_record(rec, to_status=target_status, reason=proposal.reason)
                rec.reason = proposal.reason
                rec.created_topic_id = proposal.created_topic_id
                rec.updated_ts = now
                return

        state.learning.graph_proposals.append(
            GraphProposalRecord(
                proposal_id=proposal.proposal_id,
                title=proposal.title,
                summary=proposal.summary,
                trigger=proposal.trigger,
                tags=list(dict.fromkeys(proposal.tags)),
                parent_node_ids=list(proposal.parent_node_ids),
                prerequisite_node_ids=list(dict.fromkeys(getattr(proposal, "prerequisite_node_ids", []))),
                pending_parent_proposal_ids=list(dict.fromkeys(proposal.pending_parent_proposal_ids)),
                edge_type=proposal.edge_type.value,
                status=target_status,
                reason=proposal.reason,
                created_topic_id=proposal.created_topic_id,
                created_ts=now,
                updated_ts=now,
            )
        )

    def _mark_proposal_active_for_topic(self, *, state: AppState, topic_id: str) -> None:
        now = datetime.datetime.now(timezone.utc).isoformat()
        for rec in state.learning.graph_proposals:
            if rec.created_topic_id == topic_id and rec.status in {"shadow", "validated", "proposed"}:
                self._transition_proposal_record(rec, to_status="active", reason="promoted by mastery evidence")
                rec.observation_count = max(rec.observation_count, state.learning.shadow_observation_map.get(topic_id, 0))
                rec.updated_ts = now

    def _mark_proposal_rejected_for_topic(self, *, state: AppState, topic_id: str, reason: str) -> None:
        now = datetime.datetime.now(timezone.utc).isoformat()
        for rec in state.learning.graph_proposals:
            if rec.created_topic_id != topic_id:
                continue
            if rec.status in {"active", "rejected"}:
                continue
            self._transition_proposal_record(rec, to_status="rejected", reason=reason)
            rec.updated_ts = now

    def _update_shadow_lifecycle(self, *, state: AppState, topic_id: str, is_correct: bool) -> dict[str, object]:
        topic = next((item for item in state.curriculum.topics if item.topic_id == topic_id), None)
        if topic is None or "shadow" not in topic.tags:
            state.learning.shadow_observation_map.pop(topic_id, None)
            state.learning.shadow_wrong_streak_map.pop(topic_id, None)
            return {"promoted": False, "rolled_back": False}

        if is_correct:
            obs = state.learning.shadow_observation_map.get(topic_id, 0) + 1
            state.learning.shadow_observation_map[topic_id] = obs
            state.learning.shadow_wrong_streak_map[topic_id] = 0

            promoted = False
            if obs >= self.shadow_activate_observation_turns:
                promoted = self.agent_orchestrator.curator.promote_shadow_topic(
                    topic_id=topic_id,
                    curriculum=state.curriculum,
                    mastery_map=state.learning.mastery_map,
                )
                if promoted:
                    self._mark_proposal_active_for_topic(state=state, topic_id=topic_id)
                    self._append_learning_event(
                        state=state,
                        kind="graph_promotion",
                        payload={
                            "topic_id": topic_id,
                            "to": "active",
                            "observation_count": obs,
                        },
                    )
            return {
                "promoted": promoted,
                "rolled_back": False,
                "observation_count": obs,
            }

        wrong_streak = state.learning.shadow_wrong_streak_map.get(topic_id, 0) + 1
        state.learning.shadow_wrong_streak_map[topic_id] = wrong_streak
        rolled_back = False
        if wrong_streak >= self.shadow_rollback_wrong_streak:
            rolled_back = self._rollback_shadow_topic(state=state, topic_id=topic_id)
            if rolled_back:
                self._append_learning_event(
                    state=state,
                    kind="graph_shadow_rollback",
                    payload={
                        "topic_id": topic_id,
                        "wrong_streak": wrong_streak,
                        "threshold": self.shadow_rollback_wrong_streak,
                    },
                )

        return {
            "promoted": False,
            "rolled_back": rolled_back,
            "wrong_streak": wrong_streak,
        }

    def _rollback_shadow_topic(self, *, state: AppState, topic_id: str) -> bool:
        topic = next((item for item in state.curriculum.topics if item.topic_id == topic_id), None)
        if topic is None or "shadow" not in topic.tags:
            return False

        state.curriculum.topics = [item for item in state.curriculum.topics if item.topic_id != topic_id]
        state.learning.shadow_observation_map.pop(topic_id, None)
        state.learning.shadow_wrong_streak_map.pop(topic_id, None)
        state.learning.mastery_map.pop(topic_id, None)
        if state.learning.current_topic_id == topic_id:
            state.learning.current_topic_id = None

        self._mark_proposal_rejected_for_topic(
            state=state,
            topic_id=topic_id,
            reason="rolled back due to repeated failures during shadow observation",
        )
        return True

    def _auto_expand_from_mastery(self, *, state: AppState, topic_id: str) -> int:
        if self.agent_orchestrator is None:
            return 0

        topic = next((item for item in state.curriculum.topics if item.topic_id == topic_id), None)
        if topic is None:
            return 0

        proposals = self.agent_orchestrator.curator.propose_mastery_followups(
            topic=topic,
            curriculum=state.curriculum,
            limit=1,
        )
        if not proposals:
            return 0

        expanded = 0
        for proposal in proposals:
            applied, created_topic_id = self.agent_orchestrator.curator.auto_review_and_apply(
                proposal=proposal,
                curriculum=state.curriculum,
            )
            self._upsert_graph_proposal(state=state, proposal=proposal)
            self._append_learning_event(
                state=state,
                kind="graph_auto_expand",
                payload={
                    "proposal_id": proposal.proposal_id,
                    "trigger": proposal.trigger,
                    "title": proposal.title,
                    "status": proposal.status.value,
                    "created_topic_id": created_topic_id,
                    "reason": proposal.reason,
                },
            )
            if applied and created_topic_id:
                expanded += 1
        return expanded

    def _transition_proposal_record(self, rec: GraphProposalRecord, *, to_status: str, reason: str) -> bool:
        if rec.status == to_status:
            rec.reason = reason
            return True

        allowed = self._PROPOSAL_RECORD_TRANSITIONS.get(rec.status, set())
        if to_status not in allowed:
            return False

        rec.status = to_status
        rec.reason = reason
        return True

    def _consume_explore_window_expiry(self, state: AppState) -> bool:
        until_text = state.learning.explore_window_until
        if not until_text:
            return False

        try:
            until = datetime.datetime.fromisoformat(until_text)
        except Exception:
            state.learning.explore_window_until = None
            state.learning.explore_window_cooldown_until = self._next_cooldown_until()
            return True

        if until > datetime.datetime.now(timezone.utc):
            return False

        state.learning.explore_window_until = None
        state.learning.explore_window_cooldown_until = self._next_cooldown_until()
        self._append_learning_event(
            state=state,
            kind="explore_window_closed",
            payload={
                "closed_at": datetime.datetime.now(timezone.utc).isoformat(),
                "source": "window_expired",
                "cooldown_until": state.learning.explore_window_cooldown_until,
                "return_hint": "探索时间结束啦，我们回到主线继续学习。",
            },
        )
        self.save_app_state(state)
        return True

    def _db_path(self) -> Path:
        if self.state_db_file:
            return Path(self.state_db_file)
        return self.state_file.with_suffix(".db")

    def _db_connection(self) -> sqlite3.Connection:
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_storage_initialized(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
                state_json TEXT NOT NULL,
                updated_ts TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                audio_file_path TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_events_kind
            ON learning_events(kind)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_library (
                resource_id TEXT PRIMARY KEY,
                topic_id TEXT NOT NULL,
                resource_name TEXT NOT NULL,
                category TEXT NOT NULL,
                media_type TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_ts TEXT NOT NULL,
                ingestion_status TEXT NOT NULL DEFAULT 'pending',
                ingestion_error TEXT,
                segments_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_resource_library_topic
            ON resource_library(topic_id, created_ts DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_segments (
                segment_id TEXT PRIMARY KEY,
                resource_id TEXT NOT NULL,
                sequence_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                locator_json TEXT NOT NULL,
                topic_id TEXT,
                proposal_id TEXT,
                proposed_topic_title TEXT,
                decision TEXT NOT NULL DEFAULT 'link',
                guiding_question TEXT,
                teaching_hint TEXT,
                confidence REAL NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_ts TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_resource_segments_resource
            ON resource_segments(resource_id, sequence_index)
            """
        )
        self._ensure_resource_segment_columns(conn)
        self._ensure_resource_library_columns(conn)
        conn.commit()

    @staticmethod
    def _ensure_resource_segment_columns(conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(resource_segments)").fetchall()
            if row["name"] is not None
        }
        if "proposal_id" not in columns:
            conn.execute("ALTER TABLE resource_segments ADD COLUMN proposal_id TEXT")
        if "proposed_topic_title" not in columns:
            conn.execute("ALTER TABLE resource_segments ADD COLUMN proposed_topic_title TEXT")
        if "decision" not in columns:
            conn.execute("ALTER TABLE resource_segments ADD COLUMN decision TEXT NOT NULL DEFAULT 'link'")
        if "guiding_question" not in columns:
            conn.execute("ALTER TABLE resource_segments ADD COLUMN guiding_question TEXT")
        if "teaching_hint" not in columns:
            conn.execute("ALTER TABLE resource_segments ADD COLUMN teaching_hint TEXT")

    @staticmethod
    def _ensure_resource_library_columns(conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(resource_library)").fetchall()
            if row["name"] is not None
        }
        if "ingestion_status" not in columns:
            conn.execute("ALTER TABLE resource_library ADD COLUMN ingestion_status TEXT NOT NULL DEFAULT 'pending'")
        if "ingestion_error" not in columns:
            conn.execute("ALTER TABLE resource_library ADD COLUMN ingestion_error TEXT")

    def _load_state_row(self, conn: sqlite3.Connection) -> AppState | None:
        row = conn.execute("SELECT state_json FROM app_state WHERE state_id = 1").fetchone()
        if row is None:
            return None
        try:
            return AppState.model_validate_json(row["state_json"])
        except Exception as exc:
            print(f"读取数据库状态异常: {exc}")
            return None

    def _save_state_row(self, conn: sqlite3.Connection, state: AppState) -> None:
        state_copy = state.model_copy(deep=True)
        state_copy.learning.history_logs = []
        now = datetime.datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO app_state(state_id, state_json, updated_ts)
            VALUES(1, ?, ?)
            ON CONFLICT(state_id)
            DO UPDATE SET state_json=excluded.state_json, updated_ts=excluded.updated_ts
            """,
            (state_copy.model_dump_json(), now),
        )
        conn.commit()

    def _migrate_legacy_events(self, conn: sqlite3.Connection, state: AppState) -> None:
        existing_count = conn.execute("SELECT COUNT(*) FROM learning_events").fetchone()
        if existing_count and int(existing_count[0]) > 0:
            return

        migrated = 0
        for event in state.learning.history_logs:
            self._insert_event_row(conn, event)
            migrated += 1

        if migrated:
            conn.commit()

    def _load_legacy_or_default_state(self) -> AppState:
        if self.state_file.exists():
            try:
                return AppState.model_validate_json(self.state_file.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"读取旧版存档异常: {exc}")

        return AppState(
            profile=UserProfile(student_id="user_01", display_name="演示同学"),
            learning=LearningState(current_phase=LearningPhase.NOT_STARTED, total_score=0),
            curriculum=CurriculumConfig(
                topics=[TopicNode(topic_id="demo_01", title="恐龙为什么会灭绝？", difficulty=1, prerequisite_ids=[], tags=[])]
            ),
        )

    def _fetch_recent_events(self, conn: sqlite3.Connection, *, limit: int) -> list[LearningEvent]:
        if limit <= 0:
            return []

        rows = conn.execute(
            """
            SELECT event_id, ts, kind, payload_json, audio_file_path
            FROM learning_events
            ORDER BY event_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        rows = list(reversed(rows))
        return [self._event_from_row(row) for row in rows]

    def _insert_event_row(self, conn: sqlite3.Connection, event: LearningEvent) -> int:
        payload_text = json.dumps(event.payload, ensure_ascii=False)
        cursor = conn.execute(
            """
            INSERT INTO learning_events(ts, kind, payload_json, audio_file_path)
            VALUES(?, ?, ?, ?)
            """,
            (event.ts, event.kind, payload_text, event.audio_file_path),
        )
        conn.commit()
        return int(cursor.lastrowid)

    def _insert_resource_row(self, conn: sqlite3.Connection, record: ResourceRecord) -> None:
        conn.execute(
            """
            INSERT INTO resource_library(
                resource_id, topic_id, resource_name, category, media_type, mime_type,
                original_filename, stored_path, size_bytes, created_ts, ingestion_status, ingestion_error, segments_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.resource_id,
                record.topic_id,
                record.resource_name,
                record.category,
                record.media_type,
                record.mime_type,
                record.original_filename,
                record.stored_path,
                record.size_bytes,
                record.created_ts,
                record.ingestion_status,
                record.ingestion_error,
                json.dumps([segment.model_dump() for segment in record.segments], ensure_ascii=False),
            ),
        )
        conn.commit()

    def _insert_resource_segment_row(self, conn: sqlite3.Connection, resource_id: str, segment: ResourceSegment) -> None:
        conn.execute(
            """
            INSERT INTO resource_segments(
                segment_id, resource_id, sequence_index, text, locator_json,
                topic_id, proposal_id, proposed_topic_title, decision,
                guiding_question, teaching_hint, confidence, status, reason, created_ts
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment.segment_id,
                resource_id,
                segment.sequence_index,
                segment.text or "",
                json.dumps(segment.locator, ensure_ascii=False),
                segment.topic_id,
                segment.proposal_id,
                segment.proposed_topic_title,
                segment.decision,
                segment.guiding_question,
                segment.teaching_hint,
                segment.confidence,
                segment.status,
                segment.reason,
                datetime.datetime.now(timezone.utc).isoformat(),
            ),
        )

    def _load_resource_segments(self, conn: sqlite3.Connection, resource_id: str) -> list[ResourceSegment]:
        rows = conn.execute(
            """
            SELECT segment_id, resource_id, sequence_index, text, locator_json,
                   topic_id, proposal_id, proposed_topic_title, decision,
                   guiding_question, teaching_hint, confidence, status, reason
            FROM resource_segments
            WHERE resource_id = ?
            ORDER BY sequence_index ASC, segment_id ASC
            """,
            (resource_id,),
        ).fetchall()
        if rows:
            return [self._resource_segment_from_row(row) for row in rows]
        return []

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> LearningEvent:
        payload_obj = {}
        payload_text = row["payload_json"]
        if payload_text:
            try:
                parsed = json.loads(payload_text)
                if isinstance(parsed, dict):
                    payload_obj = parsed
            except Exception:
                payload_obj = {}

        return LearningEvent(
            ts=str(row["ts"]),
            kind=str(row["kind"]),
            payload=payload_obj,
            audio_file_path=row["audio_file_path"],
        )

    def _resource_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> ResourceRecord:
        segments = self._load_resource_segments(conn, str(row["resource_id"]))
        segments_text = row["segments_json"]
        if not segments and segments_text:
            try:
                parsed = json.loads(segments_text)
                if isinstance(parsed, list):
                    segments = [ResourceSegment.model_validate(item) for item in parsed if isinstance(item, dict)]
            except Exception:
                segments = []

        return ResourceRecord(
            resource_id=str(row["resource_id"]),
            topic_id=str(row["topic_id"]),
            resource_name=str(row["resource_name"]),
            category=str(row["category"]),
            media_type=str(row["media_type"]),
            mime_type=str(row["mime_type"]),
            original_filename=str(row["original_filename"]),
            stored_path=str(row["stored_path"]),
            size_bytes=int(row["size_bytes"]),
            created_ts=str(row["created_ts"]),
            ingestion_status=str(row["ingestion_status"] or "pending"),
            ingestion_error=str(row["ingestion_error"]) if row["ingestion_error"] is not None else None,
            segments=segments,
        )

    @staticmethod
    def _resource_segment_from_row(row: sqlite3.Row) -> ResourceSegment:
        locator: dict[str, object] = {}
        locator_text = row["locator_json"]
        if locator_text:
            try:
                parsed = json.loads(locator_text)
                if isinstance(parsed, dict):
                    locator = parsed
            except Exception:
                locator = {}

        return ResourceSegment(
            segment_id=str(row["segment_id"]),
            start_ms=0,
            end_ms=None,
            label="chunk",
            status=str(row["status"]),
            sequence_index=int(row["sequence_index"]),
            text=str(row["text"]),
            locator=locator,
            topic_id=str(row["topic_id"]) if row["topic_id"] is not None else None,
            proposal_id=str(row["proposal_id"]) if row["proposal_id"] is not None else None,
            proposed_topic_title=(
                str(row["proposed_topic_title"]) if row["proposed_topic_title"] is not None else None
            ),
            decision=str(row["decision"] or "link"),
            guiding_question=str(row["guiding_question"]) if row["guiding_question"] is not None else None,
            teaching_hint=str(row["teaching_hint"]) if row["teaching_hint"] is not None else None,
            confidence=float(row["confidence"]),
            reason=str(row["reason"]),
        )

    def _next_cooldown_until(self) -> str | None:
        if self.explore_window_cooldown_minutes <= 0:
            return None
        until = datetime.datetime.now(timezone.utc) + datetime.timedelta(minutes=self.explore_window_cooldown_minutes)
        return until.isoformat()

    @staticmethod
    def _parse_iso_datetime(value: str | None) -> datetime.datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(value)
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _bounded_int_env(name: str, *, default: int, lower: int, upper: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(lower, min(upper, parsed))
