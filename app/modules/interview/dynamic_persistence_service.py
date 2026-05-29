from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_persistence_service import safe_json_loads
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.modules.interview.models import (
    InterviewEngineType,
    InterviewMode,
    InterviewOperationMetricEntity,
    InterviewSessionEntity,
    InterviewTopicEntity,
    InterviewTurnEntity,
    SessionStatus,
    TopicStatus,
)
from app.modules.interview.schemas import DynamicTopicDTO, DynamicTurnDTO, StructuredJD


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


class DynamicInterviewPersistenceService:
    async def create_planning_session(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: int,
        resume_id: int | None,
        skill_id: str,
        difficulty: str,
        llm_provider: str,
        target_role: str | None,
        target_company: str | None,
        level: str | None,
        jd_text: str | None,
        interview_mode: str = InterviewMode.COACH.value,
        plan_summary: dict | None = None,
    ) -> InterviewSessionEntity:
        entity = InterviewSessionEntity(
            user_id=user_id,
            session_id=session_id,
            resume_id=resume_id,
            skill_id=skill_id,
            difficulty=difficulty,
            total_questions=0,
            current_question_index=0,
            status=SessionStatus.PLANNING,
            questions_json=None,
            llm_provider=llm_provider,
            engine_type=InterviewEngineType.DYNAMIC.value,
            interview_mode=interview_mode,
            target_role=target_role,
            target_company=target_company,
            level=level,
            jd_text=jd_text,
            plan_summary_json=_json_dumps(plan_summary or {}),
        )
        db.add(entity)
        await db.flush()
        return entity

    async def create_session(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: int,
        resume_id: int | None,
        skill_id: str,
        difficulty: str,
        llm_provider: str,
        target_role: str | None,
        target_company: str | None,
        level: str | None,
        jd_text: str | None,
        interview_mode: str = InterviewMode.COACH.value,
        structured_jd: StructuredJD,
        plan_summary: dict,
    ) -> InterviewSessionEntity:
        entity = InterviewSessionEntity(
            user_id=user_id,
            session_id=session_id,
            resume_id=resume_id,
            skill_id=skill_id,
            difficulty=difficulty,
            total_questions=0,
            current_question_index=0,
            status=SessionStatus.INTERVIEWING,
            questions_json=None,
            llm_provider=llm_provider,
            engine_type=InterviewEngineType.DYNAMIC.value,
            interview_mode=interview_mode,
            target_role=target_role,
            target_company=target_company,
            level=level,
            jd_text=jd_text,
            plan_summary_json=_json_dumps({"structured_jd": structured_jd.model_dump(), **plan_summary}),
        )
        db.add(entity)
        await db.flush()
        return entity

    async def complete_planning_session(
        self,
        db: AsyncSession,
        session: InterviewSessionEntity,
        *,
        structured_jd: StructuredJD,
        plan_summary: dict,
    ) -> None:
        session.status = SessionStatus.INTERVIEWING
        session.plan_summary_json = _json_dumps({"structured_jd": structured_jd.model_dump(), **plan_summary})
        await db.flush()

    async def mark_session_failed(
        self,
        db: AsyncSession,
        session: InterviewSessionEntity,
        *,
        message: str,
        plan_summary: dict | None = None,
        structured_jd: StructuredJD | None = None,
    ) -> None:
        data = safe_json_loads(session.plan_summary_json, {})
        if not isinstance(data, dict):
            data = {}
        if plan_summary:
            data.update(plan_summary)
        if structured_jd:
            data["structured_jd"] = structured_jd.model_dump()
        data["generation_status"] = SessionStatus.FAILED.value
        data["generation_error"] = message[:500]
        session.status = SessionStatus.FAILED
        session.evaluate_error = message[:500]
        session.plan_summary_json = _json_dumps(data)
        await db.flush()

    async def create_topic(
        self,
        db: AsyncSession,
        *,
        session_entity_id: int,
        user_id: int,
        resume_id: int | None,
        topic: DynamicTopicDTO,
        evidence_hash: str | None,
    ) -> InterviewTopicEntity:
        entity = InterviewTopicEntity(
            session_id=session_entity_id,
            user_id=user_id,
            resume_id=resume_id,
            topic_key=topic.topic_key,
            topic_title=topic.topic_title,
            skill_key=topic.skill_key,
            question_type=topic.question_type,
            source_type=topic.source_type,
            evidence_snippet=topic.evidence_snippet,
            evidence_hash=evidence_hash,
            main_question=topic.main_question,
            topic_order=topic.topic_order,
            status=topic.status,
            max_turns=topic.max_turns,
            turn_count=topic.turn_count,
            followup_goals_json=_json_dumps(topic.followup_goals),
            exit_criteria_json=_json_dumps(topic.exit_criteria),
            rubric_json=_json_dumps(topic.rubric),
        )
        db.add(entity)
        await db.flush()
        return entity

    async def create_turn(
        self,
        db: AsyncSession,
        *,
        session_entity_id: int,
        topic_id: int,
        user_id: int,
        turn_type: str,
        turn_order: int,
        question: str,
        coach_hint: dict | None = None,
    ) -> InterviewTurnEntity:
        entity = InterviewTurnEntity(
            session_id=session_entity_id,
            topic_id=topic_id,
            user_id=user_id,
            turn_type=turn_type,
            turn_order=turn_order,
            question=question,
            coach_hint_json=_json_dumps(coach_hint) if coach_hint else None,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def find_session(
        self, db: AsyncSession, session_id: str, user_id: int | None = None
    ) -> InterviewSessionEntity | None:
        stmt = select(InterviewSessionEntity).where(
            InterviewSessionEntity.session_id == session_id,
            InterviewSessionEntity.engine_type == InterviewEngineType.DYNAMIC.value,
        )
        if user_id is not None:
            stmt = stmt.where(InterviewSessionEntity.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_session_or_throw(
        self, db: AsyncSession, session_id: str, user_id: int | None = None
    ) -> InterviewSessionEntity:
        entity = await self.find_session(db, session_id, user_id)
        if entity is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)
        return entity

    async def find_topic_or_throw(
        self, db: AsyncSession, topic_id: int, user_id: int | None = None
    ) -> InterviewTopicEntity:
        stmt = select(InterviewTopicEntity).where(InterviewTopicEntity.id == topic_id)
        if user_id is not None:
            stmt = stmt.where(InterviewTopicEntity.user_id == user_id)
        result = await db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND, "动态面试 topic 不存在")
        return entity

    async def find_turn_or_throw(
        self, db: AsyncSession, turn_id: int, session_entity_id: int, user_id: int | None = None
    ) -> InterviewTurnEntity:
        stmt = select(InterviewTurnEntity).where(
            InterviewTurnEntity.id == turn_id,
            InterviewTurnEntity.session_id == session_entity_id,
        )
        if user_id is not None:
            stmt = stmt.where(InterviewTurnEntity.user_id == user_id)
        result = await db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND, "动态面试 turn 不存在")
        return entity

    async def list_topics(self, db: AsyncSession, session_entity_id: int) -> list[InterviewTopicEntity]:
        result = await db.execute(
            select(InterviewTopicEntity)
            .where(InterviewTopicEntity.session_id == session_entity_id)
            .order_by(InterviewTopicEntity.topic_order)
        )
        return list(result.scalars().all())

    async def list_turns(self, db: AsyncSession, session_entity_id: int) -> list[InterviewTurnEntity]:
        result = await db.execute(
            select(InterviewTurnEntity)
            .where(InterviewTurnEntity.session_id == session_entity_id)
            .order_by(InterviewTurnEntity.topic_id, InterviewTurnEntity.turn_order)
        )
        return list(result.scalars().all())

    async def list_turns_by_topic(self, db: AsyncSession, topic_id: int) -> list[InterviewTurnEntity]:
        result = await db.execute(
            select(InterviewTurnEntity)
            .where(InterviewTurnEntity.topic_id == topic_id)
            .order_by(InterviewTurnEntity.turn_order)
        )
        return list(result.scalars().all())

    async def set_current_topic(self, db: AsyncSession, session_entity_id: int, topic_id: int | None) -> None:
        await db.execute(
            update(InterviewSessionEntity)
            .where(InterviewSessionEntity.id == session_entity_id)
            .values(current_topic_id=topic_id)
        )
        await db.flush()

    async def activate_topic(self, db: AsyncSession, topic_id: int, session_entity_id: int) -> None:
        await db.execute(
            update(InterviewTopicEntity)
            .where(
                InterviewTopicEntity.session_id == session_entity_id,
                InterviewTopicEntity.status == TopicStatus.ACTIVE.value,
            )
            .values(status=TopicStatus.COMPLETED.value, completed_at=datetime.now())
        )
        await db.execute(
            update(InterviewTopicEntity)
            .where(InterviewTopicEntity.id == topic_id)
            .values(status=TopicStatus.ACTIVE.value)
        )
        await self.set_current_topic(db, session_entity_id, topic_id)

    async def save_turn_answer(
        self,
        db: AsyncSession,
        turn: InterviewTurnEntity,
        *,
        answer: str,
        ability_score: int,
        feedback: str,
        signals: dict,
        evaluation: dict,
        decision_action: str,
        decision: dict,
        coach_hint: dict | None,
    ) -> None:
        turn.answer = answer
        turn.ability_score = ability_score
        turn.feedback = feedback
        turn.signals_json = _json_dumps(signals)
        turn.evaluation_json = _json_dumps(evaluation)
        turn.decision_action = decision_action
        turn.decision_json = _json_dumps(decision)
        turn.coach_hint_json = _json_dumps(coach_hint) if coach_hint else None
        turn.answered_at = datetime.now()
        await db.flush()

    async def update_topic_after_answer(
        self,
        db: AsyncSession,
        topic: InterviewTopicEntity,
        *,
        turn_count: int,
        best_score: int | None,
        final_score: int | None,
        completed: bool = False,
    ) -> None:
        topic.turn_count = turn_count
        topic.best_score = best_score
        topic.final_score = final_score
        if completed:
            topic.status = TopicStatus.COMPLETED.value
            topic.completed_at = datetime.now()
        await db.flush()

    async def save_report(
        self,
        db: AsyncSession,
        session: InterviewSessionEntity,
        report: dict,
        *,
        project_score: int | None,
        knowledge_score: int | None,
        system_design_score: int | None,
    ) -> None:
        session.status = SessionStatus.COMPLETED
        session.overall_score = report.get("readiness_score") or 0
        session.overall_feedback = "动态面试已生成 topic 级报告和明日 3 件事。"
        session.project_score = project_score
        session.knowledge_score = knowledge_score
        session.system_design_score = system_design_score
        session.final_report_json = _json_dumps(report)
        session.current_topic_id = None
        session.completed_at = datetime.now()
        await db.flush()

    async def record_operation_metric(
        self,
        db: AsyncSession,
        *,
        session_entity_id: int,
        user_id: int,
        operation_type: str,
        topic_id: int | None = None,
        turn_id: int | None = None,
        llm_provider: str | None = None,
        model_name: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: int = 0,
        cost_estimate: float = 0.0,
        success: bool = True,
        error_type: str | None = None,
    ) -> InterviewOperationMetricEntity:
        entity = InterviewOperationMetricEntity(
            session_id=session_entity_id,
            topic_id=topic_id,
            turn_id=turn_id,
            user_id=user_id,
            operation_type=operation_type,
            llm_provider=llm_provider,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost_estimate=cost_estimate,
            success=success,
            error_type=error_type,
        )
        db.add(entity)
        await db.flush()
        return entity

    def topic_to_dto(self, entity: InterviewTopicEntity) -> DynamicTopicDTO:
        return DynamicTopicDTO(
            id=entity.id,
            topic_key=entity.topic_key,
            topic_title=entity.topic_title,
            skill_key=entity.skill_key,
            question_type=entity.question_type,
            source_type=entity.source_type or "mixed",
            evidence_snippet=entity.evidence_snippet,
            main_question=entity.main_question,
            topic_order=entity.topic_order,
            status=entity.status or TopicStatus.PENDING.value,
            max_turns=entity.max_turns or 3,
            turn_count=entity.turn_count or 0,
            best_score=entity.best_score,
            final_score=entity.final_score,
            followup_goals=safe_json_loads(entity.followup_goals_json, []),
            exit_criteria=safe_json_loads(entity.exit_criteria_json, []),
            rubric=safe_json_loads(entity.rubric_json, {}),
        )

    def turn_to_dto(self, entity: InterviewTurnEntity) -> DynamicTurnDTO:
        return DynamicTurnDTO(
            id=entity.id,
            topic_id=entity.topic_id,
            turn_type=entity.turn_type,
            turn_order=entity.turn_order,
            question=entity.question,
            answer=entity.answer,
            ability_score=entity.ability_score,
            decision_action=entity.decision_action,
            feedback=entity.feedback,
            signals=safe_json_loads(entity.signals_json, {}),
            evaluation=safe_json_loads(entity.evaluation_json, {}),
            decision=safe_json_loads(entity.decision_json, {}),
            coach_hint=safe_json_loads(entity.coach_hint_json, {}) if entity.coach_hint_json else None,
            answered_at=entity.answered_at,
        )

    @staticmethod
    def latest_unanswered_turn(turns: list[InterviewTurnEntity]) -> InterviewTurnEntity | None:
        for turn in sorted(turns, key=lambda item: item.created_at or datetime.min, reverse=True):
            if turn.answer is None:
                return turn
        return None

    @staticmethod
    def structured_jd_from_session(session: InterviewSessionEntity) -> StructuredJD | None:
        data = safe_json_loads(session.plan_summary_json, {})
        structured = data.get("structured_jd") if isinstance(data, dict) else None
        if isinstance(structured, dict):
            return StructuredJD(**structured)
        return None

    @staticmethod
    def plan_summary_from_session(session: InterviewSessionEntity) -> dict:
        data = safe_json_loads(session.plan_summary_json, {})
        if not isinstance(data, dict):
            return {}
        return {key: value for key, value in data.items() if key != "structured_jd"}

    async def list_recent_topic_keys(
        self,
        db: AsyncSession,
        user_id: int,
        *,
        lookback_days: int = 7,
        session_count: int = 2,
    ) -> list[dict]:
        """Return topic_key, question_type, final_score from recent completed dynamic sessions."""
        cutoff = datetime.now() - timedelta(days=lookback_days)
        session_stmt = (
            select(InterviewSessionEntity)
            .where(
                InterviewSessionEntity.user_id == user_id,
                InterviewSessionEntity.engine_type == InterviewEngineType.DYNAMIC.value,
                InterviewSessionEntity.status == SessionStatus.COMPLETED.value,
                InterviewSessionEntity.completed_at >= cutoff,
            )
            .order_by(InterviewSessionEntity.completed_at.desc())
            .limit(session_count)
        )
        session_result = await db.execute(session_stmt)
        recent_sessions = list(session_result.scalars().all())
        if not recent_sessions:
            return []

        session_ids = [s.id for s in recent_sessions]
        topic_stmt = (
            select(InterviewTopicEntity)
            .where(InterviewTopicEntity.session_id.in_(session_ids))
            .order_by(InterviewTopicEntity.topic_order)
        )
        topic_result = await db.execute(topic_stmt)
        topics = list(topic_result.scalars().all())

        return [
            {
                "topic_key": t.topic_key,
                "question_type": t.question_type,
                "final_score": t.final_score,
                "evidence_hash": t.evidence_hash,
            }
            for t in topics
        ]

    async def get_user_topic_profile(
        self,
        db: AsyncSession,
        user_id: int,
        *,
        lookback_days: int = 30,
    ) -> dict:
        """Aggregate historical topic data into a simple profile: counts, avg scores, low-score topics."""
        cutoff = datetime.now() - timedelta(days=lookback_days)
        session_stmt = select(InterviewSessionEntity.id).where(
            InterviewSessionEntity.user_id == user_id,
            InterviewSessionEntity.engine_type == InterviewEngineType.DYNAMIC.value,
            InterviewSessionEntity.status == SessionStatus.COMPLETED.value,
            InterviewSessionEntity.completed_at >= cutoff,
        )
        session_result = await db.execute(session_stmt)
        session_ids = [row[0] for row in session_result.fetchall()]
        if not session_ids:
            return {"topic_counts": {}, "low_score_topics": [], "total_sessions": 0}

        topic_stmt = select(InterviewTopicEntity).where(InterviewTopicEntity.session_id.in_(session_ids))
        topic_result = await db.execute(topic_stmt)
        all_topics = list(topic_result.scalars().all())

        topic_counts: dict[str, dict] = {}
        for t in all_topics:
            entry = topic_counts.setdefault(t.topic_key, {"count": 0, "scores": [], "question_types": set()})
            entry["count"] += 1
            entry["question_types"].add(t.question_type)
            if t.final_score is not None:
                entry["scores"].append(t.final_score)

        profile: dict[str, dict] = {}
        for key, entry in topic_counts.items():
            avg = sum(entry["scores"]) / len(entry["scores"]) if entry["scores"] else None
            profile[key] = {
                "count": entry["count"],
                "avg_score": round(avg) if avg is not None else None,
                "question_types": sorted(entry["question_types"]),
            }

        low_score_topics = [
            key for key, entry in profile.items() if entry["avg_score"] is not None and entry["avg_score"] < 60
        ]

        return {
            "topic_counts": profile,
            "low_score_topics": low_score_topics,
            "total_sessions": len(session_ids),
        }


dynamic_interview_persistence_service = DynamicInterviewPersistenceService()
