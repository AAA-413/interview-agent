import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.common.model import AsyncTaskStatus
from app.config import settings
from app.modules.interview.evaluation_service import QaRecord, unified_evaluation_service
from app.modules.interview.models import SessionStatus
from app.modules.interview.persistence_service import interview_persistence_service
from app.modules.interview.question_service import interview_question_service
from app.modules.interview.schemas import (
    CreateInterviewRequest,
    InterviewReportDTO,
    InterviewSessionDTO,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from app.modules.interview.skill_service import interview_skill_service

logger = logging.getLogger(__name__)


class InterviewSessionService:
    async def create_session(self, db: AsyncSession, request: CreateInterviewRequest) -> InterviewSessionDTO:
        if request.resume_id and not request.force_create:
            unfinished = await self._find_unfinished_session(db, request.resume_id)
            if unfinished:
                logger.info("检测到未完成的面试会话: resumeId=%d, sessionId=%s", request.resume_id, unfinished.session_id)
                return unfinished

        session_id = uuid.uuid4().hex[:16]
        skill_id = request.skill_id or settings.interview.default_skill_id
        difficulty = request.difficulty or settings.interview.default_difficulty

        logger.info("创建新面试会话: %s, skill: %s, difficulty: %s, questionCount: %d", session_id, skill_id, difficulty, request.question_count)

        historical_questions = await interview_persistence_service.get_historical_questions(db, skill_id, request.resume_id)

        chat_model = llm_registry.get_chat_model(request.llm_provider)

        questions = await interview_question_service.generate_questions(
            chat_model=chat_model,
            skill_id=skill_id,
            difficulty=difficulty,
            resume_text=request.resume_text,
            question_count=request.question_count,
            historical_questions=historical_questions,
            custom_categories=request.custom_categories,
            jd_text=request.jd_text,
        )

        await interview_persistence_service.save_session(
            db=db,
            session_id=session_id,
            resume_id=request.resume_id,
            total_questions=len(questions),
            questions=questions,
            llm_provider=request.llm_provider or "dashscope",
            skill_id=skill_id,
            difficulty=difficulty,
        )

        return InterviewSessionDTO(
            session_id=session_id,
            resume_text=request.resume_text or "",
            total_questions=len(questions),
            current_question_index=0,
            questions=questions,
            status="CREATED",
            evaluate_status=None,
            evaluate_error=None,
        )

    async def get_session(self, db: AsyncSession, session_id: str) -> InterviewSessionDTO:
        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id)
        questions = interview_persistence_service.parse_questions_json(entity.questions_json)

        for answer in entity.answers:
            if 0 <= answer.question_index < len(questions):
                questions[answer.question_index] = questions[answer.question_index].model_copy(update={"answer": answer.user_answer})

        return InterviewSessionDTO(
            session_id=entity.session_id,
            resume_text="",
            total_questions=entity.total_questions or len(questions),
            current_question_index=entity.current_question_index,
            questions=questions,
            status=entity.status.value if entity.status else "CREATED",
            evaluate_status=entity.evaluate_status,
            evaluate_error=entity.evaluate_error,
        )

    async def get_current_question(self, db: AsyncSession, session_id: str) -> dict:
        session_dto = await self.get_session(db, session_id)

        if session_dto.current_question_index >= len(session_dto.questions):
            return {"completed": True, "message": "所有问题已回答完毕"}

        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id)
        if entity.status == SessionStatus.CREATED:
            await interview_persistence_service.update_session_status(db, session_id, SessionStatus.IN_PROGRESS)

        question = session_dto.questions[session_dto.current_question_index]
        return {"completed": False, "question": question.model_dump()}

    async def submit_answer(self, db: AsyncSession, session_id: str, request: SubmitAnswerRequest) -> SubmitAnswerResponse:
        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id)
        questions = interview_persistence_service.parse_questions_json(entity.questions_json)

        index = request.question_index
        if index < 0 or index >= len(questions):
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND, f"无效的问题索引: {index}")

        question = questions[index]
        questions[index] = question.model_copy(update={"answer": request.answer})

        new_index = index + 1
        has_next = new_index < len(questions)
        next_question = questions[new_index] if has_next else None

        new_status = SessionStatus.IN_PROGRESS if has_next else SessionStatus.COMPLETED

        await interview_persistence_service.save_answer(
            db=db,
            session_entity_id=entity.id,
            question_index=index,
            question=question.question,
            category=question.category,
            answer=request.answer,
        )
        await interview_persistence_service.update_current_question_index(db, session_id, new_index)
        await interview_persistence_service.update_session_status(db, session_id, new_status)

        if not has_next:
            await self._enqueue_evaluation(db, session_id)

        logger.info("会话 %s 提交答案: 问题%d, 剩余%d题", session_id, index, len(questions) - new_index)

        return SubmitAnswerResponse(
            has_next_question=has_next,
            next_question=next_question,
            current_question_index=new_index,
            total_questions=len(questions),
        )

    async def save_answer(self, db: AsyncSession, session_id: str, request: SubmitAnswerRequest) -> None:
        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id)
        questions = interview_persistence_service.parse_questions_json(entity.questions_json)

        index = request.question_index
        if index < 0 or index >= len(questions):
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND, f"无效的问题索引: {index}")

        question = questions[index]

        await interview_persistence_service.save_answer(
            db=db,
            session_entity_id=entity.id,
            question_index=index,
            question=question.question,
            category=question.category,
            answer=request.answer,
        )

        if entity.status == SessionStatus.CREATED:
            await interview_persistence_service.update_session_status(db, session_id, SessionStatus.IN_PROGRESS)

        logger.info("会话 %s 暂存答案: 问题%d", session_id, index)

    async def complete_interview(self, db: AsyncSession, session_id: str) -> None:
        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id)

        if entity.status in (SessionStatus.COMPLETED, SessionStatus.EVALUATED):
            raise BusinessException(ErrorCode.INTERVIEW_ALREADY_COMPLETED)

        await interview_persistence_service.update_session_status(db, session_id, SessionStatus.COMPLETED)
        await self._enqueue_evaluation(db, session_id)
        logger.info("会话 %s 提前交卷，评估任务已入队", session_id)

    async def generate_report(self, db: AsyncSession, session_id: str) -> InterviewReportDTO:
        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id)

        if entity.status not in (SessionStatus.COMPLETED, SessionStatus.EVALUATED):
            raise BusinessException(ErrorCode.INTERVIEW_NOT_COMPLETED, "面试尚未完成，无法查看报告")

        if entity.status != SessionStatus.EVALUATED:
            if entity.evaluate_status == AsyncTaskStatus.FAILED.value:
                raise BusinessException(
                    ErrorCode.INTERVIEW_REPORT_GENERATION_FAILED,
                    entity.evaluate_error or "面试报告生成失败",
                )
            raise BusinessException(ErrorCode.INTERVIEW_REPORT_GENERATING, "面试报告生成中，请稍后再试")

        return await self._build_report_dto(db, session_id)

    async def evaluate_session(self, db: AsyncSession, session_id: str) -> InterviewReportDTO:
        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id)

        if entity.status not in (SessionStatus.COMPLETED, SessionStatus.EVALUATED):
            raise BusinessException(ErrorCode.INTERVIEW_NOT_COMPLETED, "面试尚未完成，无法生成报告")

        logger.info("后台生成面试报告: %s", session_id)

        questions = interview_persistence_service.parse_questions_json(entity.questions_json)
        qa_records = []
        for answer in entity.answers:
            q = questions[answer.question_index] if answer.question_index < len(questions) else None
            qa_records.append(
                QaRecord(
                    question_index=answer.question_index,
                    question=answer.question or (q.question if q else ""),
                    category=answer.category or (q.category if q else None),
                    user_answer=answer.user_answer,
                )
            )

        chat_model = llm_registry.get_chat_model(entity.llm_provider)
        reference_context = interview_skill_service.build_evaluation_reference_section_safe(entity.skill_id)

        report = await unified_evaluation_service.evaluate(
            chat_model=chat_model,
            session_id=session_id,
            qa_records=qa_records,
            resume_text=None,
            reference_context=reference_context,
        )

        await interview_persistence_service.save_report(db, session_id, report)
        return report

    async def _build_report_dto(self, db: AsyncSession, session_id: str) -> InterviewReportDTO:
        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id)
        questions = interview_persistence_service.parse_questions_json(entity.questions_json)

        question_evaluations = []
        for answer in sorted(entity.answers, key=lambda item: item.question_index):
            q = questions[answer.question_index] if answer.question_index < len(questions) else None
            question_evaluations.append(
                {
                    "question_index": answer.question_index,
                    "question": answer.question or (q.question if q else ""),
                    "category": answer.category or (q.category if q else None),
                    "user_answer": answer.user_answer,
                    "score": answer.score or 0,
                    "feedback": answer.feedback,
                }
            )

        strengths = json.loads(entity.strengths_json) if entity.strengths_json else []
        improvements = json.loads(entity.improvements_json) if entity.improvements_json else []
        reference_answers = []
        if entity.reference_answers_json:
            try:
                from app.modules.interview.schemas import ReferenceAnswerDTO

                reference_answers = [ReferenceAnswerDTO(**item) for item in json.loads(entity.reference_answers_json)]
            except (json.JSONDecodeError, TypeError, KeyError):
                reference_answers = []

        return InterviewReportDTO(
            session_id=entity.session_id,
            total_questions=entity.total_questions or len(questions),
            overall_score=entity.overall_score or 0,
            question_evaluations=question_evaluations,
            overall_feedback=entity.overall_feedback,
            strengths=strengths,
            improvements=improvements,
            reference_answers=reference_answers,
        )

    async def _enqueue_evaluation(self, db: AsyncSession, session_id: str) -> None:
        await interview_persistence_service.update_evaluate_status(db, session_id, AsyncTaskStatus.PENDING.value, None)
        try:
            from app.infrastructure.redis.redis_service import RedisService, get_redis
            from app.modules.interview.async_tasks import EvaluateStreamProducer

            redis = await get_redis()
            producer = EvaluateStreamProducer(RedisService(redis))
            await producer.send_evaluate_task(session_id)
            logger.info("会话 %s 评估任务已入队", session_id)
        except Exception as e:
            logger.warning("发送评估任务失败: sessionId=%s, error=%s", session_id, e)
            await interview_persistence_service.update_evaluate_status(
                db,
                session_id,
                AsyncTaskStatus.FAILED.value,
                f"评估任务入队失败: {e}",
            )

    async def _find_unfinished_session(self, db: AsyncSession, resume_id: int) -> InterviewSessionDTO | None:
        try:
            entity = await interview_persistence_service.find_unfinished_session(db, resume_id)
            if entity is None:
                return None
            return await self.get_session(db, entity.session_id)
        except Exception as e:
            logger.error("恢复未完成会话失败: %s", e)
            return None


interview_session_service = InterviewSessionService()
