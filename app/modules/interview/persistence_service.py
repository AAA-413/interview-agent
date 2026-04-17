import json
import logging
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    ) -> InterviewSessionEntity:
        entity = InterviewSessionEntity(
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

    async def find_by_session_id(self, db: AsyncSession, session_id: str) -> InterviewSessionEntity | None:
        result = await db.execute(select(InterviewSessionEntity).where(InterviewSessionEntity.session_id == session_id))
        return result.scalar_one_or_none()

    async def find_by_session_id_or_throw(self, db: AsyncSession, session_id: str) -> InterviewSessionEntity:
        entity = await self.find_by_session_id(db, session_id)
        if entity is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)
        return entity

    async def find_all(self, db: AsyncSession) -> list[InterviewSessionEntity]:
        result = await db.execute(select(InterviewSessionEntity).order_by(InterviewSessionEntity.created_at.desc()))
        return list(result.scalars().all())

    async def find_unfinished_session(self, db: AsyncSession, resume_id: int) -> InterviewSessionEntity | None:
        result = await db.execute(
            select(InterviewSessionEntity)
            .where(
                InterviewSessionEntity.resume_id == resume_id,
                InterviewSessionEntity.status.in_([SessionStatus.CREATED, SessionStatus.IN_PROGRESS]),
            )
            .order_by(InterviewSessionEntity.created_at.desc())
            .limit(1)
        )
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

    async def delete_session(self, db: AsyncSession, session_id: str) -> None:
        entity = await self.find_by_session_id(db, session_id)
        if entity is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)
        await db.execute(delete(InterviewAnswerEntity).where(InterviewAnswerEntity.session_id == entity.id))
        await db.delete(entity)
        await db.flush()

    async def get_historical_questions(
        self, db: AsyncSession, skill_id: str, resume_id: int | None = None
    ) -> list[HistoricalQuestion]:
        query = (
            select(InterviewSessionEntity)
            .where(InterviewSessionEntity.skill_id == skill_id)
            .order_by(InterviewSessionEntity.created_at.desc())
            .limit(5)
        )
        if resume_id is not None:
            query = query.where(InterviewSessionEntity.resume_id == resume_id)

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
        if not questions_json:
            return []
        try:
            data = json.loads(questions_json)
            return [InterviewQuestionDTO(**q) for q in data]
        except (json.JSONDecodeError, KeyError):
            return []

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
        strengths = json.loads(entity.strengths_json) if entity.strengths_json else []
        improvements = json.loads(entity.improvements_json) if entity.improvements_json else []
        reference_answers = []
        if entity.reference_answers_json:
            try:
                from app.modules.interview.schemas import ReferenceAnswerDTO

                reference_answers = [ReferenceAnswerDTO(**r) for r in json.loads(entity.reference_answers_json)]
            except (json.JSONDecodeError, KeyError):
                pass

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
