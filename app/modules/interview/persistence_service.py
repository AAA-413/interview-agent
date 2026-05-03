import json
import logging
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_persistence_service import safe_json_loads
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.common.model import AsyncTaskStatus
from app.modules.interview.models import InterviewAnswerEntity, InterviewSessionEntity, SessionStatus
from app.modules.interview.schemas import (
    HistoricalQuestion,
    InterviewDetailDTO,
    InterviewQuestionDTO,
    InterviewReportDTO,
    SessionListItemDTO,
)

logger = logging.getLogger(__name__)


class InterviewPersistenceService:
    async def save_session(
        self,
        db: AsyncSession,
        session_id: str,
        resume_id: int | None,
        total_questions: int,
        questions: list[InterviewQuestionDTO],
        llm_provider: str,
        skill_id: str,
        difficulty: str,
        user_id: int = 0,
    ) -> InterviewSessionEntity:
        entity = InterviewSessionEntity(
            user_id=user_id,
            session_id=session_id,
            resume_id=resume_id,
            total_questions=total_questions,
            current_question_index=0,
            status=SessionStatus.CREATED,
            questions_json=json.dumps([q.model_dump() for q in questions], ensure_ascii=False),
            llm_provider=llm_provider,
            skill_id=skill_id,
            difficulty=difficulty,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def find_by_session_id(self, db: AsyncSession, session_id: str, user_id: int | None = None) -> InterviewSessionEntity | None:
        stmt = select(InterviewSessionEntity).where(InterviewSessionEntity.session_id == session_id)
        if user_id is not None:
            stmt = stmt.where(InterviewSessionEntity.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_session_id_or_throw(self, db: AsyncSession, session_id: str, user_id: int | None = None) -> InterviewSessionEntity:
        entity = await self.find_by_session_id(db, session_id, user_id)
        if entity is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)
        return entity

    async def find_all(self, db: AsyncSession, user_id: int | None = None) -> list[InterviewSessionEntity]:
        query = select(InterviewSessionEntity).order_by(InterviewSessionEntity.created_at.desc())
        if user_id is not None:
            query = query.where(InterviewSessionEntity.user_id == user_id)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def find_unfinished_session(self, db: AsyncSession, resume_id: int, user_id: int | None = None) -> InterviewSessionEntity | None:
        query = (
            select(InterviewSessionEntity)
            .where(
                InterviewSessionEntity.resume_id == resume_id,
                InterviewSessionEntity.status.in_([SessionStatus.CREATED, SessionStatus.IN_PROGRESS]),
            )
            .order_by(InterviewSessionEntity.created_at.desc())
            .limit(1)
        )
        if user_id is not None:
            query = query.where(InterviewSessionEntity.user_id == user_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def update_session_status(self, db: AsyncSession, session_id: str, status: SessionStatus) -> None:
        await db.execute(
            update(InterviewSessionEntity)
            .where(InterviewSessionEntity.session_id == session_id)
            .values(status=status)
        )
        await db.flush()

    async def update_current_question_index(self, db: AsyncSession, session_id: str, index: int) -> None:
        await db.execute(
            update(InterviewSessionEntity)
            .where(InterviewSessionEntity.session_id == session_id)
            .values(current_question_index=index)
        )
        await db.flush()

    async def update_evaluate_status(
        self, db: AsyncSession, session_id: str, status: str | None, error: str | None = None
    ) -> None:
        values: dict = {"evaluate_status": status}
        if error is not None:
            values["evaluate_error"] = error[:500] if error else None
        await db.execute(
            update(InterviewSessionEntity).where(InterviewSessionEntity.session_id == session_id).values(**values)
        )
        await db.flush()

    async def save_answer(
        self,
        db: AsyncSession,
        session_entity_id: int,
        question_index: int,
        question: str,
        category: str | None,
        answer: str,
    ) -> InterviewAnswerEntity:
        result = await db.execute(
            select(InterviewAnswerEntity).where(
                InterviewAnswerEntity.session_id == session_entity_id,
                InterviewAnswerEntity.question_index == question_index,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.user_answer = answer
            await db.flush()
            return existing

        entity = InterviewAnswerEntity(
            session_id=session_entity_id,
            question_index=question_index,
            question=question,
            category=category,
            user_answer=answer,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def find_answers_by_session_id(self, db: AsyncSession, session_id: str) -> list[InterviewAnswerEntity]:
        entity = await self.find_by_session_id(db, session_id)
        if entity is None:
            return []
        result = await db.execute(
            select(InterviewAnswerEntity)
            .where(InterviewAnswerEntity.session_id == entity.id)
            .order_by(InterviewAnswerEntity.question_index)
        )
        return list(result.scalars().all())

    async def save_report(self, db: AsyncSession, session_id: str, report: InterviewReportDTO) -> None:
        values = {
            "overall_score": report.overall_score,
            "overall_feedback": report.overall_feedback,
            "strengths_json": json.dumps(report.strengths, ensure_ascii=False),
            "improvements_json": json.dumps(report.improvements, ensure_ascii=False),
            "reference_answers_json": json.dumps(
                [r.model_dump() for r in report.reference_answers], ensure_ascii=False
            ),
            "status": SessionStatus.EVALUATED,
            "completed_at": datetime.now(),
        }
        await db.execute(
            update(InterviewSessionEntity).where(InterviewSessionEntity.session_id == session_id).values(**values)
        )

        entity = await self.find_by_session_id(db, session_id)
        if entity:
            for qa in report.question_evaluations:
                await db.execute(
                    update(InterviewAnswerEntity)
                    .where(
                        InterviewAnswerEntity.session_id == entity.id,
                        InterviewAnswerEntity.question_index == qa.question_index,
                    )
                    .values(score=qa.score, feedback=qa.feedback)
                )

        await db.flush()

    async def delete_session(self, db: AsyncSession, session_id: str, user_id: int | None = None) -> None:
        entity = await self.find_by_session_id_or_throw(db, session_id, user_id)
        await db.execute(delete(InterviewAnswerEntity).where(InterviewAnswerEntity.session_id == entity.id))
        await db.delete(entity)
        await db.flush()

    async def get_historical_questions(
        self, db: AsyncSession, skill_id: str, resume_id: int | None = None, user_id: int | None = None
    ) -> list[HistoricalQuestion]:
        query = (
            select(InterviewSessionEntity)
            .where(InterviewSessionEntity.skill_id == skill_id)
            .order_by(InterviewSessionEntity.created_at.desc())
            .limit(5)
        )
        if resume_id is not None:
            query = query.where(InterviewSessionEntity.resume_id == resume_id)
        if user_id is not None:
            query = query.where(InterviewSessionEntity.user_id == user_id)

        result = await db.execute(query)
        sessions = list(result.scalars().all())

        historical: list[HistoricalQuestion] = []
        for session in sessions:
            if not session.questions_json:
                continue
            try:
                questions_data = json.loads(session.questions_json)
                for q in questions_data:
                    if not q.get("is_follow_up", False):
                        historical.append(
                            HistoricalQuestion(
                                question=q.get("question", ""),
                                type=q.get("type", "GENERAL"),
                                category=q.get("category"),
                                topic_summary=q.get("topic_summary"),
                            )
                        )
            except (json.JSONDecodeError, KeyError):
                continue

        return historical

    def parse_questions_json(self, questions_json: str | None) -> list[InterviewQuestionDTO]:
        data = safe_json_loads(questions_json, [])
        return [InterviewQuestionDTO(**q) for q in data] if data else []

    def to_session_list_item(self, entity: InterviewSessionEntity) -> SessionListItemDTO:
        return SessionListItemDTO(
            id=entity.id,
            session_id=entity.session_id,
            skill_id=entity.skill_id,
            difficulty=entity.difficulty,
            resume_id=entity.resume_id,
            total_questions=entity.total_questions,
            current_question_index=entity.current_question_index,
            status=entity.status.value if entity.status else "CREATED",
            evaluate_status=entity.evaluate_status,
            evaluate_error=entity.evaluate_error,
            overall_score=entity.overall_score,
            created_at=entity.created_at,
            completed_at=entity.completed_at,
        )

    def to_detail_dto(self, entity: InterviewSessionEntity) -> InterviewDetailDTO:
        questions = self.parse_questions_json(entity.questions_json)
        strengths = safe_json_loads(entity.strengths_json, [])
        improvements = safe_json_loads(entity.improvements_json, [])

        raw_refs = safe_json_loads(entity.reference_answers_json, [])
        reference_answers = []
        if raw_refs:
            from app.modules.interview.schemas import ReferenceAnswerDTO
            reference_answers = [ReferenceAnswerDTO(**r) for r in raw_refs]

        question_evaluations = []
        for answer in entity.answers:
            question_evaluations.append(
                {
                    "question_index": answer.question_index,
                    "question": answer.question,
                    "category": answer.category,
                    "user_answer": answer.user_answer,
                    "score": answer.score or 0,
                    "feedback": answer.feedback,
                }
            )

        return InterviewDetailDTO(
            session_id=entity.session_id,
            skill_id=entity.skill_id,
            difficulty=entity.difficulty,
            resume_id=entity.resume_id,
            total_questions=entity.total_questions,
            current_question_index=entity.current_question_index,
            status=entity.status.value if entity.status else "CREATED",
            evaluate_status=entity.evaluate_status,
            evaluate_error=entity.evaluate_error,
            overall_score=entity.overall_score,
            overall_feedback=entity.overall_feedback,
            strengths=strengths,
            improvements=improvements,
            questions=questions,
            question_evaluations=question_evaluations,
            reference_answers=reference_answers,
            created_at=entity.created_at,
            completed_at=entity.completed_at,
        )


interview_persistence_service = InterviewPersistenceService()
