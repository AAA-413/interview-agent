import logging
from pathlib import Path
import asyncio
from asyncio import Semaphore

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.common.ai.structured_output import structured_output_invoker
from app.common.error_code import ErrorCode
from app.common.prompt_utils import load_prompt, render_template
from app.modules.interview.schemas import (
    CategoryScoreDTO,
    InterviewReportDTO,
    KeyPoint,
    ProjectDimensionsDTO,
    QuestionEvaluationDTO,
    ReferenceAnswerDTO,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
MAX_REFERENCE_CONTEXT_CHARS = 6000


class _KnowledgeEvalDTO(BaseModel):
    score: int
    coveredPoints: list[str] = []
    missedPoints: list[str] = []
    errors: list[str] = []
    feedback: str


class _ProjectDimensionsDTO(BaseModel):
    authenticity: int = 0
    technical_depth: int = 0
    depth: int = 0
    expression: int = 0


class _ProjectEvalDTO(BaseModel):
    score: int
    dimensions: _ProjectDimensionsDTO = _ProjectDimensionsDTO()
    feedback: str


class _QuestionEvalDTO(BaseModel):
    questionIndex: int
    score: int
    feedback: str
    referenceAnswer: str = ""
    keyPoints: list[str] | None = None
    questionType: str = "knowledge"
    coveredPoints: list[str] | None = None
    missedPoints: list[str] | None = None
    errors: list[str] | None = None
    dimensions: _ProjectDimensionsDTO | None = None


class _BatchReportDTO(BaseModel):
    overallScore: int = 0
    overallFeedback: str = ""
    strengths: list[str] | None = None
    improvements: list[str] | None = None
    questionEvaluations: list[_QuestionEvalDTO] | None = None


class _SummaryDTO(BaseModel):
    overallFeedback: str = ""
    strengths: list[str] | None = None
    improvements: list[str] | None = None


class QaRecord(BaseModel):
    question_index: int
    question: str
    category: str | None = None
    user_answer: str | None = None
    question_type: str = "knowledge"
    reference_answer: str | None = None
    key_points: list[KeyPoint] | None = None
    is_follow_up: bool = False
    parent_question_index: int | None = None


class UnifiedEvaluationService:
    def __init__(self):
        self._system_prompt = load_prompt(_PROMPTS_DIR, "interview-evaluation-system.md")
        self._user_prompt = load_prompt(_PROMPTS_DIR, "interview-evaluation-user.md")
        self._knowledge_eval_system = load_prompt(_PROMPTS_DIR, "eval-knowledge-system.md")
        self._knowledge_eval_user = load_prompt(_PROMPTS_DIR, "eval-knowledge-user.md")
        self._project_eval_system = load_prompt(_PROMPTS_DIR, "eval-project-system.md")
        self._project_eval_user = load_prompt(_PROMPTS_DIR, "eval-project-user.md")
        self._summary_system_prompt = load_prompt(_PROMPTS_DIR, "interview-evaluation-summary-system.md")
        self._summary_user_prompt = load_prompt(_PROMPTS_DIR, "interview-evaluation-summary-user.md")
        self._batch_size = 8
        self._max_concurrent_batches = 3

    async def evaluate(
        self,
        chat_model: ChatOpenAI,
        session_id: str,
        qa_records: list[QaRecord],
        resume_text: str | None = None,
        reference_context: str | None = None,
    ) -> InterviewReportDTO:
        logger.info("开始评估面试: sessionId=%s, 共%d题", session_id, len(qa_records))

        resume_context = resume_text or ""
        if len(resume_context) > 3000:
            resume_context = resume_context[:3000] + "\n...(简历内容过长，已截断)"

        reference_baseline = (reference_context or "").strip()
        if len(reference_baseline) > MAX_REFERENCE_CONTEXT_CHARS:
            reference_baseline = reference_baseline[:MAX_REFERENCE_CONTEXT_CHARS] + "\n...(参考基线过长，已截断)"

        # Evaluate questions individually based on type
        evaluations = await self._evaluate_by_type(chat_model, session_id, qa_records, resume_context)

        # Build summary
        summary = await self._summarize_batch_results(
            chat_model, session_id, resume_context, reference_baseline,
            qa_records, evaluations, "", [], [],
        )

        return self._build_report(session_id, qa_records, evaluations, summary.overallFeedback, summary.strengths or [], summary.improvements or [])

    async def _evaluate_by_type(
        self, chat_model: ChatOpenAI, session_id: str,
        qa_records: list[QaRecord], resume_context: str,
    ) -> list[_QuestionEvalDTO]:
        """Evaluate questions individually based on type (knowledge vs project)"""
        semaphore = Semaphore(self._max_concurrent_batches)
        evaluations: list[_QuestionEvalDTO | None] = [None] * len(qa_records)

        async def evaluate_one(index: int, qa: QaRecord):
            async with semaphore:
                if not qa.user_answer or not qa.user_answer.strip():
                    evaluations[index] = _QuestionEvalDTO(
                        questionIndex=qa.question_index, score=0, feedback="未作答"
                    )
                    return

                # Determine evaluation strategy
                effective_type = qa.question_type
                if qa.is_follow_up and qa.parent_question_index is not None:
                    # Follow-up inherits parent's type
                    for parent_qa in qa_records:
                        if parent_qa.question_index == qa.parent_question_index:
                            effective_type = parent_qa.question_type
                            break

                if effective_type == "project" or (not qa.reference_answer and not qa.key_points):
                    # Project evaluation
                    result = await self.evaluate_project_question(
                        chat_model, qa.question, qa.user_answer, resume_context,
                    )
                    if result:
                        evaluations[index] = _QuestionEvalDTO(
                            questionIndex=qa.question_index,
                            score=result.score,
                            feedback=result.feedback,
                            questionType="project",
                            dimensions=_ProjectDimensionsDTO(
                                authenticity=result.dimensions.authenticity,
                                technical_depth=result.dimensions.technical_depth,
                                depth=result.dimensions.depth,
                                expression=result.dimensions.expression,
                            ),
                        )
                    else:
                        evaluations[index] = _QuestionEvalDTO(
                            questionIndex=qa.question_index, score=0, feedback="评估失败", questionType="project"
                        )
                else:
                    # Knowledge evaluation with key_points
                    if qa.reference_answer and qa.key_points:
                        result = await self.evaluate_knowledge_question(
                            chat_model, qa.question, qa.user_answer,
                            qa.reference_answer, qa.key_points,
                        )
                        if result:
                            evaluations[index] = _QuestionEvalDTO(
                                questionIndex=qa.question_index,
                                score=result.score,
                                feedback=result.feedback,
                                questionType="knowledge",
                                referenceAnswer=qa.reference_answer,
                                keyPoints=[kp.point for kp in qa.key_points] if qa.key_points else [],
                                coveredPoints=result.coveredPoints,
                                missedPoints=result.missedPoints,
                                errors=result.errors,
                            )
                        else:
                            evaluations[index] = _QuestionEvalDTO(
                                questionIndex=qa.question_index, score=0, feedback="评估失败", questionType="knowledge"
                            )
                    else:
                        # Fallback to basic evaluation
                        evaluations[index] = _QuestionEvalDTO(
                            questionIndex=qa.question_index, score=0, feedback="无参考答案"
                        )

        tasks = [evaluate_one(i, qa) for i, qa in enumerate(qa_records)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Fill in any remaining None evaluations
        for i in range(len(evaluations)):
            if evaluations[i] is None:
                evaluations[i] = _QuestionEvalDTO(
                    questionIndex=i, score=0, feedback="评估异常"
                )

        return evaluations

    async def _evaluate_in_batches(
        self, chat_model: ChatOpenAI, session_id: str, resume_context: str,
        qa_records: list[QaRecord], reference_context: str,
    ) -> list[_BatchReportDTO | None]:
        """并行执行批次评估，使用 Semaphore 限流"""
        semaphore = Semaphore(self._max_concurrent_batches)

        async def evaluate_with_limit(batch_index: int, batch: list[QaRecord]):
            async with semaphore:
                logger.info("开始评估批次 %d/%d: sessionId=%s",
                           batch_index + 1,
                           (len(qa_records) + self._batch_size - 1) // self._batch_size,
                           session_id)
                return await self._evaluate_batch(chat_model, session_id, resume_context, reference_context, batch)

        # 创建所有批次任务
        tasks = []
        for start in range(0, len(qa_records), self._batch_size):
            batch = qa_records[start : start + self._batch_size]
            batch_index = start // self._batch_size
            tasks.append(evaluate_with_limit(batch_index, batch))

        # 并行执行所有批次
        logger.info("开始并行评估 %d 个批次: sessionId=%s, max_concurrent=%d",
                   len(tasks), session_id, self._max_concurrent_batches)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("批次 %d 评估失败: sessionId=%s, error=%s", i, session_id, result)
                valid_results.append(None)
            else:
                valid_results.append(result)

        logger.info("批次评估完成: sessionId=%s, 成功=%d, 失败=%d",
                   session_id,
                   sum(1 for r in valid_results if r is not None),
                   sum(1 for r in valid_results if r is None))

        return valid_results

    async def _evaluate_batch(
        self, chat_model: ChatOpenAI, session_id: str, resume_context: str,
        reference_context: str, batch: list[QaRecord],
    ) -> _BatchReportDTO | None:
        qa_text = self._build_qa_records(batch)

        variables = {
            "resumeText": resume_context,
            "qaRecords": qa_text,
            "referenceContext": reference_context if reference_context else "无",
        }

        user_prompt = render_template(self._user_prompt, variables)

        try:
            return await structured_output_invoker.invoke(
                chat_model=chat_model,
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                output_model=_BatchReportDTO,
                error_code=ErrorCode.INTERVIEW_EVALUATION_FAILED,
                error_prefix="批次评估失败：",
                log_context="批次评估",
            )
        except Exception as e:
            logger.error("批次评估失败: sessionId=%s, batchSize=%d, error=%s", session_id, len(batch), e)
            return None

    async def _summarize_batch_results(
        self, chat_model: ChatOpenAI, session_id: str, resume_context: str,
        reference_context: str, qa_records: list[QaRecord],
        evaluations: list[_QuestionEvalDTO], fallback_feedback: str,
        fallback_strengths: list[str], fallback_improvements: list[str],
    ) -> _SummaryDTO:
        try:
            variables = {
                "resumeText": resume_context,
                "referenceContext": reference_context if reference_context else "无",
                "categorySummary": self._build_category_summary(qa_records, evaluations),
                "questionHighlights": self._build_question_highlights(qa_records, evaluations),
                "fallbackOverallFeedback": fallback_feedback,
                "fallbackStrengths": "\n".join(fallback_strengths),
                "fallbackImprovements": "\n".join(fallback_improvements),
            }

            user_prompt = render_template(self._summary_user_prompt, variables)

            dto = await structured_output_invoker.invoke(
                chat_model=chat_model,
                system_prompt=self._summary_system_prompt,
                user_prompt=user_prompt,
                output_model=_SummaryDTO,
                error_code=ErrorCode.INTERVIEW_EVALUATION_FAILED,
                error_prefix="总结评估失败：",
                log_context="总结评估",
            )

            feedback = dto.overallFeedback if dto and dto.overallFeedback else fallback_feedback
            strengths = self._sanitize_items(dto.strengths if dto else None, fallback_strengths)
            improvements = self._sanitize_items(dto.improvements if dto else None, fallback_improvements)
            return _SummaryDTO(overallFeedback=feedback, strengths=strengths, improvements=improvements)
        except Exception as e:
            logger.warning("二次汇总评估失败，降级到批次聚合结果: sessionId=%s, error=%s", session_id, e)
            return _SummaryDTO(overallFeedback=fallback_feedback, strengths=fallback_strengths, improvements=fallback_improvements)

    def _merge_question_evaluations(self, batch_results: list[_BatchReportDTO | None]) -> list[_QuestionEvalDTO]:
        merged = []
        for report in batch_results:
            if report and report.questionEvaluations:
                merged.extend(report.questionEvaluations)
        return merged

    def _merge_overall_feedback(self, batch_results: list[_BatchReportDTO | None]) -> str:
        parts = [r.overallFeedback for r in batch_results if r and r.overallFeedback]
        return "\n\n".join(parts) if parts else "本次面试已完成分批评估，但未生成有效综合评语。"

    def _merge_list_items(self, batch_results: list[_BatchReportDTO | None], strengths_mode: bool) -> list[str]:
        seen = set()
        result = []
        for r in batch_results:
            if not r:
                continue
            items = r.strengths if strengths_mode else r.improvements
            if not items:
                continue
            for item in items:
                if item and item.strip() and item.strip() not in seen:
                    seen.add(item.strip())
                    result.append(item.strip())
        return result[:8]

    @staticmethod
    def _sanitize_items(primary: list[str] | None, fallback: list[str]) -> list[str]:
        source = primary if primary else fallback
        if not source:
            return []
        seen = set()
        result = []
        for item in source:
            if item and item.strip() and item.strip() not in seen:
                seen.add(item.strip())
                result.append(item.strip())
        return result[:8]

    def _build_report(
        self, session_id: str, qa_records: list[QaRecord],
        evaluations: list[_QuestionEvalDTO], overall_feedback: str,
        strengths: list[str], improvements: list[str],
    ) -> InterviewReportDTO:
        question_details = []
        reference_answers = []
        category_scores_map: dict[str, list[int]] = {}

        for i, q in enumerate(qa_records):
            eval_dto = evaluations[i] if i < len(evaluations) else None
            has_answer = bool(q.user_answer and q.user_answer.strip())
            score = eval_dto.score if has_answer and eval_dto else 0
            feedback = eval_dto.feedback if eval_dto else "该题未成功生成评估反馈。"
            ref_answer = eval_dto.referenceAnswer if eval_dto else ""
            key_points = eval_dto.keyPoints if eval_dto else []

            question_details.append(
                QuestionEvaluationDTO(
                    question_index=q.question_index,
                    question=q.question,
                    category=q.category,
                    user_answer=q.user_answer,
                    score=score,
                    feedback=feedback,
                    question_type=eval_dto.questionType if eval_dto else "knowledge",
                    covered_points=eval_dto.coveredPoints if eval_dto else None,
                    missed_points=eval_dto.missedPoints if eval_dto else None,
                    errors=eval_dto.errors if eval_dto else None,
                    dimensions=ProjectDimensionsDTO(
                        authenticity=eval_dto.dimensions.authenticity,
                        technical_depth=eval_dto.dimensions.technical_depth,
                        depth=eval_dto.dimensions.depth,
                        expression=eval_dto.dimensions.expression,
                    ) if eval_dto and eval_dto.dimensions else None,
                )
            )
            reference_answers.append(
                ReferenceAnswerDTO(
                    question_index=q.question_index,
                    question=q.question,
                    reference_answer=ref_answer,
                    key_points=key_points,
                )
            )
            cat = q.category or "GENERAL"
            category_scores_map.setdefault(cat, []).append(score)

        category_scores = [
            CategoryScoreDTO(category=cat, average_score=int(sum(scores) / len(scores)), question_count=len(scores))
            for cat, scores in category_scores_map.items()
        ]

        answered_count = sum(1 for q in qa_records if q.user_answer and q.user_answer.strip())
        overall_score = int(sum(d.score for d in question_details) / len(question_details)) if question_details else 0

        return InterviewReportDTO(
            session_id=session_id,
            total_questions=len(qa_records),
            overall_score=overall_score,
            category_scores=category_scores,
            question_evaluations=question_details,
            overall_feedback=overall_feedback,
            strengths=strengths,
            improvements=improvements,
            reference_answers=reference_answers,
        )

    @staticmethod
    def _build_qa_records(batch: list[QaRecord]) -> str:
        lines = []
        for q in batch:
            lines.append(f"问题{q.question_index + 1} [{q.category or 'GENERAL'}]: {q.question}")
            lines.append(f"回答: {q.user_answer or '(未回答)'}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_category_summary(qa_records: list[QaRecord], evaluations: list[_QuestionEvalDTO]) -> str:
        category_scores: dict[str, list[int]] = {}
        for i, q in enumerate(qa_records):
            eval_dto = evaluations[i] if i < len(evaluations) else None
            score = eval_dto.score if eval_dto and q.user_answer else 0
            category_scores.setdefault(q.category or "GENERAL", []).append(score)

        lines = []
        for cat, scores in sorted(category_scores.items()):
            avg = int(sum(scores) / len(scores))
            lines.append(f"- {cat}: 平均分 {avg}, 题数 {len(scores)}")
        return "\n".join(lines)

    @staticmethod
    def _build_question_highlights(qa_records: list[QaRecord], evaluations: list[_QuestionEvalDTO]) -> str:
        highlights = []
        for i, q in enumerate(qa_records):
            eval_dto = evaluations[i] if i < len(evaluations) else None
            score = eval_dto.score if eval_dto else 0
            feedback = eval_dto.feedback if eval_dto else ""
            short_q = q.question[:50] + "..." if len(q.question) > 50 else q.question
            short_f = feedback[:80] + "..." if len(feedback) > 80 else feedback
            highlights.append(f"- Q{q.question_index + 1} | {short_q} | 分数:{score} | 反馈:{short_f}")
        return "\n".join(highlights[:20])

    async def evaluate_knowledge_question(
        self, chat_model: ChatOpenAI, question: str, user_answer: str,
        reference_answer: str, key_points: list[KeyPoint],
    ) -> _KnowledgeEvalDTO | None:
        if not user_answer or not user_answer.strip():
            return _KnowledgeEvalDTO(score=0, feedback="未作答")

        key_points_text = "\n".join([
            f"- {kp.point} (分数段: {kp.score_range}, 重要程度: {kp.weight})"
            for kp in key_points
        ])

        variables = {
            "question": question,
            "userAnswer": user_answer,
            "referenceAnswer": reference_answer,
            "keyPoints": key_points_text,
        }

        user_prompt = render_template(self._knowledge_eval_user, variables)

        try:
            return await structured_output_invoker.invoke(
                chat_model=chat_model,
                system_prompt=self._knowledge_eval_system,
                user_prompt=user_prompt,
                output_model=_KnowledgeEvalDTO,
                error_code=ErrorCode.INTERVIEW_EVALUATION_FAILED,
                error_prefix="知识题评估失败：",
                log_context="知识题评估",
            )
        except Exception as e:
            logger.error("知识题评估失败: %s", e)
            return None

    async def evaluate_project_question(
        self, chat_model: ChatOpenAI, question: str, user_answer: str,
        project_context: str = "",
    ) -> _ProjectEvalDTO | None:
        if not user_answer or not user_answer.strip():
            return _ProjectEvalDTO(score=0, feedback="未作答")

        variables = {
            "question": question,
            "userAnswer": user_answer,
            "projectContext": project_context or "无项目上下文",
        }

        user_prompt = render_template(self._project_eval_user, variables)

        try:
            return await structured_output_invoker.invoke(
                chat_model=chat_model,
                system_prompt=self._project_eval_system,
                user_prompt=user_prompt,
                output_model=_ProjectEvalDTO,
                error_code=ErrorCode.INTERVIEW_EVALUATION_FAILED,
                error_prefix="项目题评估失败：",
                log_context="项目题评估",
            )
        except Exception as e:
            logger.error("项目题评估失败: %s", e)
            return None


unified_evaluation_service = UnifiedEvaluationService()
