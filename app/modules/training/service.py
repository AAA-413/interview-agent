from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_persistence_service import safe_json_loads
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service
from app.modules.interview.models import (
    InterviewEngineType,
    InterviewSessionEntity,
    SessionStatus,
)
from app.modules.interview.persistence_service import interview_persistence_service
from app.modules.resume.models import ResumeAnalysisEntity, ResumeEntity
from app.modules.resume.persistence_service import resume_persistence_service
from app.modules.training.models import TrainingTaskProgressEntity, TrainingTaskStatus
from app.modules.training.schemas import (
    CalibrationDimensionDTO,
    CalibrationQuestionDTO,
    PersonalTrainingPlanDTO,
    ScoreCalibrationDTO,
    TrainingDayDTO,
    TrainingTaskDTO,
    TrainingTaskProgressDTO,
    TrainingTrendDTO,
    TrainingTrendPointDTO,
    UpdateTrainingTaskProgressRequest,
)

PROJECT_DIMENSION_LABELS = {
    "authenticity": "项目真实性",
    "technical_depth": "技术深度",
    "depth": "回答深度",
    "expression": "表达结构",
}

DYNAMIC_ABILITY_LABELS = {
    "authenticity": "动态能力：真实性证据",
    "technical_depth": "动态能力：技术深度",
    "knowledge_accuracy": "动态能力：知识准确性",
    "system_thinking": "动态能力：系统思维",
    "communication_structure": "动态能力：表达结构",
}

DYNAMIC_TYPE_LABELS = {
    "PROJECT": "项目题",
    "KNOWLEDGE": "知识题",
    "SYSTEM_DESIGN": "系统设计",
}

PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


@dataclass
class RetrySummary:
    attempt_count: int = 0
    latest_retry_score: int | None = None
    latest_retry_delta: int | None = None
    latest_retry_session_id: str | None = None
    latest_at: datetime | None = None


class TrainingService:
    async def get_score_calibration(self, db: AsyncSession, user_id: int) -> ScoreCalibrationDTO:
        sessions = await interview_persistence_service.find_all(db, user_id=user_id)
        static_evaluated_sessions = [item for item in sessions if item.status == SessionStatus.EVALUATED]
        primary_static_sessions = [
            item
            for item in static_evaluated_sessions
            if self._retry_source_key(interview_persistence_service.parse_questions_json(item.questions_json)) is None
        ]
        dynamic_report_sessions = [
            item for item in sessions if self._has_dynamic_report(item) and self._dynamic_retry_source_key(item) is None
        ]
        primary_report_sessions = primary_static_sessions + dynamic_report_sessions
        baseline = self._average_score([item.overall_score for item in primary_report_sessions])
        retry_summaries = self._build_retry_summaries(static_evaluated_sessions)

        question_items: list[CalibrationQuestionDTO] = []
        dimension_scores: dict[str, list[int]] = defaultdict(list)
        for session in primary_static_sessions:
            questions = interview_persistence_service.parse_questions_json(session.questions_json)
            evaluations = interview_persistence_service.build_question_evaluations(session, questions)
            for evaluation in evaluations:
                question_index = int(evaluation.get("question_index") or 0)
                item = self._build_question_calibration(
                    session,
                    evaluation,
                    baseline,
                    retry_summaries.get((session.session_id, question_index)),
                )
                question_items.append(item)

                if item.raw_score is not None:
                    dimension_scores[f"题型：{item.category or '综合能力'}"].append(item.raw_score)

                dimensions = evaluation.get("dimensions")
                if isinstance(dimensions, dict):
                    for key, label in PROJECT_DIMENSION_LABELS.items():
                        value = dimensions.get(key)
                        if isinstance(value, int | float) and value > 0:
                            dimension_scores[label].append(round(value))

        for session in dynamic_report_sessions:
            report = safe_json_loads(session.final_report_json, {})
            for item in self._dynamic_topic_calibrations(session, report, baseline):
                question_items.append(item)
                if item.raw_score is not None:
                    dimension_scores[f"题型：{self._dynamic_type_label(item.question_type)}"].append(item.raw_score)

            ability_scores = report.get("ability_scores") if isinstance(report, dict) else None
            if isinstance(ability_scores, dict):
                for key, label in DYNAMIC_ABILITY_LABELS.items():
                    value = ability_scores.get(key)
                    if isinstance(value, int | float) and value > 0:
                        dimension_scores[label].append(round(value))

        dimensions = self._build_dimensions(dimension_scores)
        question_items = sorted(
            question_items,
            key=lambda item: (
                PRIORITY_ORDER.get(item.review_priority, 9),
                item.confidence,
                item.raw_score if item.raw_score is not None else 999,
            ),
        )
        raw_scores = [item.raw_score for item in question_items if item.raw_score is not None]
        calibrated_scores = [item.calibrated_score for item in question_items if item.calibrated_score is not None]
        confidence_scores = [item.confidence for item in question_items]
        review_needed_count = sum(1 for item in question_items if item.review_priority in {"HIGH", "MEDIUM"})
        high_risk_count = sum(1 for item in question_items if item.review_priority == "HIGH")
        confidence = self._average_score(confidence_scores)
        calibrated_score = self._average_score(calibrated_scores)

        return ScoreCalibrationDTO(
            total_sessions=len(sessions),
            evaluated_sessions=len(primary_report_sessions),
            total_questions=len(question_items),
            average_raw_score=self._average_score(raw_scores),
            calibrated_score=calibrated_score,
            confidence=confidence,
            confidence_label=self._confidence_label(confidence) if confidence else "暂无",
            review_needed_count=review_needed_count,
            high_risk_count=high_risk_count,
            summary=self._calibration_summary(
                len(primary_report_sessions), len(question_items), calibrated_score, confidence
            ),
            questions=question_items,
            dimensions=dimensions,
            next_actions=self._calibration_actions(question_items, dimensions),
        )

    async def get_personal_training_plan(
        self,
        db: AsyncSession,
        user_id: int,
        days: int = 7,
    ) -> PersonalTrainingPlanDTO:
        days = min(max(days, 1), 14)
        calibration = await self.get_score_calibration(db, user_id)
        resumes = await resume_persistence_service.find_all(db, user_id=user_id)
        analyses = [analysis for resume in resumes if (analysis := self._latest_analysis(resume))]

        tasks = self._build_candidate_tasks(calibration, resumes, analyses, days)
        dynamic_tasks = await self._build_dynamic_tomorrow_tasks(db, user_id)
        tasks.extend(dynamic_tasks)
        progress = await self._get_progress_by_task_id(db, user_id)
        tasks = [self._apply_progress(task, progress.get(task.id)) for task in tasks]
        plan = self._schedule_tasks(tasks, days)
        resume_score = self._average_score([analysis.overall_score for analysis in analyses])
        readiness_score = self._readiness_score(calibration, resume_score)

        return PersonalTrainingPlanDTO(
            days=days,
            generated_from=self._generated_from(resumes, analyses, calibration),
            readiness_score=readiness_score,
            summary=self._plan_summary(readiness_score, calibration),
            calibration=calibration,
            plan=plan,
            quick_wins=self._quick_wins(calibration, analyses),
        )

    async def update_task_progress(
        self,
        db: AsyncSession,
        user_id: int,
        request: UpdateTrainingTaskProgressRequest,
    ) -> TrainingTaskProgressDTO:
        status = TrainingTaskStatus(request.status)
        task_lookup = await self._build_current_task_lookup(db, user_id)
        task = task_lookup.get(request.task_id)
        if task is None:
            raise BusinessException(ErrorCode.BAD_REQUEST, "训练任务不存在或已过期，请刷新计划后重试。")

        result = await db.execute(
            select(TrainingTaskProgressEntity).where(
                TrainingTaskProgressEntity.user_id == user_id,
                TrainingTaskProgressEntity.task_id == request.task_id,
            )
        )
        entity = result.scalar_one_or_none()
        completed_at = datetime.now(timezone.utc) if status == TrainingTaskStatus.COMPLETED else None

        if entity is None:
            entity = TrainingTaskProgressEntity(
                user_id=user_id,
                task_id=request.task_id,
                title=task.title,
                task_type=task.task_type,
                source_session_id=task.source_session_id,
                question_index=task.question_index,
                status=status,
                notes=request.notes,
                completed_at=completed_at,
            )
            db.add(entity)
        else:
            entity.title = task.title
            entity.task_type = task.task_type
            entity.source_session_id = task.source_session_id
            entity.question_index = task.question_index
            entity.status = status
            entity.notes = request.notes
            entity.completed_at = completed_at

        await db.flush()
        return self._progress_dto(entity)

    async def get_training_trend(self, db: AsyncSession, user_id: int) -> TrainingTrendDTO:
        sessions = await interview_persistence_service.find_all(db, user_id=user_id)
        resumes = await resume_persistence_service.find_all(db, user_id=user_id)
        progress_items = await self._get_progress_items(db, user_id)
        task_lookup = await self._build_current_task_lookup(db, user_id, days=14)
        completed_progress = [
            item
            for item in progress_items
            if item.status == TrainingTaskStatus.COMPLETED and item.task_id in task_lookup
        ]
        retry_summaries = self._build_retry_summaries(
            [item for item in sessions if item.status == SessionStatus.EVALUATED]
        )

        points: list[TrainingTrendPointDTO] = []
        for session in sessions:
            if self._has_dynamic_report(session):
                at = session.completed_at or session.created_at
                points.append(
                    TrainingTrendPointDTO(
                        date=self._date_label(at),
                        occurred_at=self._datetime_label(at),
                        label=f"动态面试报告 {session.session_id[:6]}",
                        metric_type="INTERVIEW_SCORE",
                        score=session.overall_score,
                        source_id=session.session_id,
                    )
                )
                continue

            if session.status != SessionStatus.EVALUATED or session.overall_score is None:
                continue

            questions = interview_persistence_service.parse_questions_json(session.questions_json)
            if self._retry_source_key(questions) is not None:
                continue
            at = session.completed_at or session.created_at
            points.append(
                TrainingTrendPointDTO(
                    date=self._date_label(at),
                    occurred_at=self._datetime_label(at),
                    label=f"面试报告 {session.session_id[:6]}",
                    metric_type="INTERVIEW_SCORE",
                    score=session.overall_score,
                    source_id=session.session_id,
                )
            )

        for resume in resumes:
            for analysis in resume.analyses:
                if analysis.overall_score is None:
                    continue
                points.append(
                    TrainingTrendPointDTO(
                        date=self._date_label(analysis.analyzed_at),
                        occurred_at=self._datetime_label(analysis.analyzed_at),
                        label=f"简历评分 {resume.original_filename}",
                        metric_type="RESUME_SCORE",
                        score=analysis.overall_score,
                        source_id=str(resume.id),
                    )
                )

        for key, summary in retry_summaries.items():
            if summary.latest_retry_delta is None:
                continue
            points.append(
                TrainingTrendPointDTO(
                    date=self._date_label(summary.latest_at),
                    occurred_at=self._datetime_label(summary.latest_at),
                    label=self._retry_trend_label(summary.latest_retry_delta),
                    metric_type="RETRY_DELTA",
                    score=summary.latest_retry_score,
                    delta=summary.latest_retry_delta,
                    source_id=summary.latest_retry_session_id or f"{key[0]}:{key[1]}",
                )
            )

        completed_by_date: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "latest_at": None})
        for item in completed_progress:
            if item.completed_at:
                bucket = completed_by_date[self._date_label(item.completed_at)]
                bucket["count"] += 1
                if self._datetime_sort_value(item.completed_at) >= self._datetime_sort_value(bucket["latest_at"]):
                    bucket["latest_at"] = item.completed_at
        for date, bucket in completed_by_date.items():
            points.append(
                TrainingTrendPointDTO(
                    date=date,
                    occurred_at=self._datetime_label(bucket["latest_at"]),
                    label="训练完成",
                    metric_type="TRAINING_DONE",
                    completed_tasks=bucket["count"],
                )
            )

        points = sorted(points, key=self._trend_sort_key)
        latest_interview_score = self._latest_score(points, "INTERVIEW_SCORE")
        latest_resume_score = self._latest_score(points, "RESUME_SCORE")
        latest_retry_delta = self._latest_delta(points, "RETRY_DELTA")

        return TrainingTrendDTO(
            summary=self._trend_summary(
                latest_interview_score,
                latest_resume_score,
                latest_retry_delta,
                len(completed_progress),
            ),
            latest_interview_score=latest_interview_score,
            latest_resume_score=latest_resume_score,
            latest_retry_delta=latest_retry_delta,
            completed_task_count=len(completed_progress),
            trend=points[-20:],
        )

    async def _get_progress_by_task_id(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> dict[str, TrainingTaskProgressEntity]:
        return {item.task_id: item for item in await self._get_progress_items(db, user_id)}

    async def _get_progress_items(self, db: AsyncSession, user_id: int) -> list[TrainingTaskProgressEntity]:
        result = await db.execute(
            select(TrainingTaskProgressEntity)
            .where(TrainingTaskProgressEntity.user_id == user_id)
            .order_by(TrainingTaskProgressEntity.updated_at.desc())
        )
        return list(result.scalars().all())

    async def _build_current_task_lookup(
        self,
        db: AsyncSession,
        user_id: int,
        days: int = 14,
    ) -> dict[str, TrainingTaskDTO]:
        calibration = await self.get_score_calibration(db, user_id)
        resumes = await resume_persistence_service.find_all(db, user_id=user_id)
        analyses = [analysis for resume in resumes if (analysis := self._latest_analysis(resume))]
        tasks = self._build_candidate_tasks(calibration, resumes, analyses, days)
        tasks.extend(await self._build_dynamic_tomorrow_tasks(db, user_id))
        return {task.id: task for task in tasks}

    def _apply_progress(
        self,
        task: TrainingTaskDTO,
        progress: TrainingTaskProgressEntity | None,
    ) -> TrainingTaskDTO:
        if progress is None:
            return task
        return task.model_copy(
            update={
                "status": progress.status.value,
                "completed_at": self._datetime_label(progress.completed_at),
            }
        )

    def _build_retry_summaries(
        self,
        evaluated_sessions: list[InterviewSessionEntity],
    ) -> dict[tuple[str, int], RetrySummary]:
        source_scores: dict[tuple[str, int], int] = {}
        parsed_questions: dict[str, list] = {}
        parsed_evaluations: dict[str, list[dict]] = {}

        for session in evaluated_sessions:
            questions = interview_persistence_service.parse_questions_json(session.questions_json)
            evaluations = interview_persistence_service.build_question_evaluations(session, questions)
            parsed_questions[session.session_id] = questions
            parsed_evaluations[session.session_id] = evaluations
            for evaluation in evaluations:
                score = self._score_or_none(evaluation.get("score"))
                if score is not None:
                    source_scores[(session.session_id, int(evaluation.get("question_index") or 0))] = score

        summaries: dict[tuple[str, int], RetrySummary] = {}
        for session in evaluated_sessions:
            source_key = self._retry_source_key(parsed_questions.get(session.session_id, []))
            if source_key is None:
                continue

            retry_evaluation = self._evaluation_by_index(parsed_evaluations.get(session.session_id, []), 0)
            retry_score = self._score_or_none(retry_evaluation.get("score"))
            source_score = source_scores.get(source_key)
            score_delta = retry_score - source_score if retry_score is not None and source_score is not None else None
            at = session.completed_at or session.created_at

            summary = summaries.setdefault(source_key, RetrySummary())
            summary.attempt_count += 1
            if summary.latest_at is None or self._datetime_sort_value(at) >= self._datetime_sort_value(
                summary.latest_at
            ):
                summary.latest_at = at if isinstance(at, datetime) else None
                summary.latest_retry_score = retry_score
                summary.latest_retry_delta = score_delta
                summary.latest_retry_session_id = session.session_id
        return summaries

    @staticmethod
    def _retry_source_key(questions: list) -> tuple[str, int] | None:
        if not questions:
            return None
        question = questions[0]
        source_session_id = getattr(question, "retry_source_session_id", None)
        source_question_index = getattr(question, "retry_source_question_index", None)
        if source_session_id and source_question_index is not None:
            return source_session_id, source_question_index
        return None

    def _build_question_calibration(
        self,
        session: InterviewSessionEntity,
        evaluation: dict[str, Any],
        baseline: int,
        retry_summary: RetrySummary | None = None,
    ) -> CalibrationQuestionDTO:
        score = self._score_or_none(evaluation.get("score"))
        reasons: list[str] = []
        missing_count = 0

        if score is None:
            reasons.append("缺少有效分数")
            missing_count += 1
        if not self._non_empty_text(evaluation.get("feedback")):
            reasons.append("缺少文字反馈")
            missing_count += 1
        if not self._non_empty_text(evaluation.get("user_answer")):
            reasons.append("缺少用户回答")
            missing_count += 1
        elif len(str(evaluation.get("user_answer")).strip()) < 30:
            reasons.append("回答样本较短")

        question_type = str(evaluation.get("question_type") or "knowledge")
        dimensions = evaluation.get("dimensions")
        if question_type == "project" and not isinstance(dimensions, dict):
            reasons.append("缺少项目维度评分")
            missing_count += 1
        if question_type != "project" and not self._has_any_list(
            evaluation,
            ("covered_points", "missed_points", "answer_framework"),
        ):
            reasons.append("缺少要点覆盖信息")
            missing_count += 1

        evidence_count = self._evidence_count(evaluation)
        confidence = self._clamp(62 + evidence_count * 7 - len(reasons) * 12, 35, 95)
        if score is None:
            confidence = min(confidence, 45)
        calibrated_score = self._calibrated_question_score(score, baseline, confidence)

        return CalibrationQuestionDTO(
            session_id=session.session_id,
            question_index=int(evaluation.get("question_index") or 0),
            question=str(evaluation.get("question") or ""),
            category=evaluation.get("category"),
            question_type=question_type,
            raw_score=score,
            calibrated_score=calibrated_score,
            confidence=confidence,
            confidence_label=self._confidence_label(confidence),
            review_priority=self._review_priority(score, confidence),
            score_band=self._score_band(score),
            reasons=reasons,
            evidence_count=evidence_count,
            missing_count=missing_count,
            action=self._question_action(score, confidence),
            retry_attempt_count=retry_summary.attempt_count if retry_summary else 0,
            latest_retry_score=retry_summary.latest_retry_score if retry_summary else None,
            latest_retry_delta=retry_summary.latest_retry_delta if retry_summary else None,
            retry_signal=self._retry_signal(retry_summary.latest_retry_delta) if retry_summary else None,
        )

    def _dynamic_topic_calibrations(
        self,
        session: InterviewSessionEntity,
        report: dict[str, Any],
        baseline: int,
    ) -> list[CalibrationQuestionDTO]:
        topic_summaries = report.get("topic_summaries") if isinstance(report, dict) else None
        if not isinstance(topic_summaries, list):
            return []

        items: list[CalibrationQuestionDTO] = []
        for index, summary in enumerate(topic_summaries):
            if not isinstance(summary, dict):
                continue

            score = self._score_or_none(summary.get("final_score"))
            reasons: list[str] = []
            missing_count = 0
            if score is None:
                reasons.append("缺少有效分数")
                missing_count += 1
            if not self._has_any_summary_list(summary, ("strengths", "gaps", "risks")):
                reasons.append("缺少动态复盘信号")
                missing_count += 1

            evidence_count = self._dynamic_evidence_count(summary)
            confidence = self._clamp(70 + evidence_count * 4 - len(reasons) * 10, 45, 95)
            if score is None:
                confidence = min(confidence, 45)

            question_type = str(summary.get("question_type") or "DYNAMIC")
            question = str(summary.get("main_question") or summary.get("topic_title") or "动态面试 topic")
            topic_id = summary.get("topic_id")
            question_index = topic_id if isinstance(topic_id, int) else index
            calibrated_score = self._calibrated_question_score(score, baseline, confidence)

            items.append(
                CalibrationQuestionDTO(
                    session_id=session.session_id,
                    question_index=question_index,
                    question=question,
                    category=str(summary.get("topic_title") or self._dynamic_type_label(question_type)),
                    question_type=f"dynamic_{question_type.lower()}",
                    raw_score=score,
                    calibrated_score=calibrated_score,
                    confidence=confidence,
                    confidence_label=self._confidence_label(confidence),
                    review_priority=self._review_priority(score, confidence),
                    score_band=self._score_band(score),
                    reasons=reasons,
                    evidence_count=evidence_count,
                    missing_count=missing_count,
                    action=self._dynamic_question_action(score, summary),
                )
            )
        return items

    def _build_dimensions(self, dimension_scores: dict[str, list[int]]) -> list[CalibrationDimensionDTO]:
        dimensions = []
        for name, scores in dimension_scores.items():
            if not scores:
                continue
            average_score = self._average_score(scores)
            weak_count = sum(1 for score in scores if score < 70)
            dimensions.append(
                CalibrationDimensionDTO(
                    name=name,
                    average_score=average_score,
                    question_count=len(scores),
                    weak_count=weak_count,
                    suggested_action=self._dimension_action(name, average_score, weak_count),
                )
            )
        return sorted(dimensions, key=lambda item: (item.average_score, -item.weak_count, item.name))

    def _build_candidate_tasks(
        self,
        calibration: ScoreCalibrationDTO,
        resumes: list[ResumeEntity],
        analyses: list[ResumeAnalysisEntity],
        days: int,
    ) -> list[TrainingTaskDTO]:
        tasks: list[TrainingTaskDTO] = []

        for item in calibration.questions[:8]:
            if item.review_priority == "LOW" and (item.raw_score or 0) >= 75:
                continue
            is_dynamic = item.question_type.startswith("dynamic_")
            priority = self._task_priority(item)
            tasks.append(
                TrainingTaskDTO(
                    id=f"{'dyn-topic' if is_dynamic else 'retry'}-{item.session_id}-{item.question_index}",
                    day=0,
                    title=f"重练：{self._short_text(item.question, 28)}",
                    task_type="RETRY_TOPIC" if is_dynamic else "RETRY_LOW_SCORE",
                    priority=priority,
                    estimate_minutes=25,
                    reason=self._task_reason(item),
                    source_session_id=item.session_id,
                    question_index=item.question_index,
                    action_path=(
                        f"/interview?sessionId={item.session_id}&mode=dynamic"
                        if is_dynamic
                        else f"/interviews/{item.session_id}"
                    ),
                    checklist=self._task_checklist(item),
                    retry_attempt_count=item.retry_attempt_count,
                    latest_retry_delta=item.latest_retry_delta,
                    retry_signal=item.retry_signal,
                )
            )

        for dimension in calibration.dimensions[:4]:
            if dimension.average_score >= 72 and dimension.weak_count == 0:
                continue
            tasks.append(
                TrainingTaskDTO(
                    id=f"dimension-{dimension.name}",
                    day=0,
                    title=f"专项补强：{dimension.name}",
                    task_type="DIMENSION_DRILL",
                    priority="HIGH" if dimension.average_score < 65 else "MEDIUM",
                    estimate_minutes=20,
                    reason=dimension.suggested_action,
                    action_path="/interview-hub",
                    checklist=["准备 1 个真实案例", "写出取舍和结果", "用 2 分钟口述一遍"],
                )
            )

        for resume in resumes[:3]:
            analysis = self._latest_analysis(resume)
            if not analysis:
                continue
            suggestions = safe_json_loads(analysis.suggestions_json, [])
            for index, suggestion in enumerate(suggestions[:3]):
                if not isinstance(suggestion, dict):
                    continue
                priority = str(suggestion.get("priority") or "MEDIUM").upper()
                if priority not in {"HIGH", "MEDIUM", "LOW"}:
                    priority = "MEDIUM"
                tasks.append(
                    TrainingTaskDTO(
                        id=f"resume-{resume.id}-{index}",
                        day=0,
                        title=f"简历改稿：{suggestion.get('category') or '表达优化'}",
                        task_type="RESUME_FIX",
                        priority=priority,
                        estimate_minutes=20,
                        reason=str(suggestion.get("issue") or suggestion.get("recommendation") or "补齐简历证据"),
                        action_path=f"/resumes/{resume.id}",
                        checklist=[
                            str(suggestion.get("recommendation") or "补充 STAR 结构"),
                            "补一个可验证指标",
                            "同步到项目介绍回答",
                        ],
                    )
                )

        if not resumes:
            tasks.append(
                TrainingTaskDTO(
                    id="bootstrap-upload-resume",
                    day=0,
                    title="上传并解析第一份简历",
                    task_type="BOOTSTRAP_RESUME",
                    priority="HIGH",
                    estimate_minutes=15,
                    reason="训练计划需要候选人画像作为输入",
                    action_path="/upload",
                    checklist=["上传简历", "等待分析完成", "查看高优先级建议"],
                )
            )
        if calibration.evaluated_sessions == 0:
            tasks.append(
                TrainingTaskDTO(
                    id="bootstrap-first-interview",
                    day=0,
                    title="完成一次模拟面试",
                    task_type="MOCK_INTERVIEW",
                    priority="HIGH",
                    estimate_minutes=30,
                    reason="评分校准需要至少一份已评估报告",
                    action_path="/interview-hub",
                    checklist=["选择面试方向", "完成至少 3 道题", "查看报告"],
                )
            )

        self._fill_daily_tasks(tasks, days)
        return self._dedupe_tasks(tasks)

    def _schedule_tasks(self, tasks: list[TrainingTaskDTO], days: int) -> list[TrainingDayDTO]:
        ordered_tasks = sorted(
            tasks,
            key=lambda item: (
                PRIORITY_ORDER.get(item.priority, 9),
                self._retry_delta_rank(item.latest_retry_delta),
                item.task_type,
                item.id,
            ),
        )
        buckets: list[list[TrainingTaskDTO]] = [[] for _ in range(days)]
        for index, task in enumerate(ordered_tasks[: days * 3]):
            day_index = min(index // 3, days - 1)
            buckets[day_index].append(task.model_copy(update={"day": day_index + 1}))

        plan = []
        for index, bucket in enumerate(buckets, start=1):
            focus = self._day_focus(bucket, index)
            plan.append(
                TrainingDayDTO(
                    day=index,
                    title=f"第 {index} 天",
                    focus=focus,
                    total_minutes=sum(task.estimate_minutes for task in bucket),
                    tasks=bucket,
                )
            )
        return plan

    async def _build_dynamic_tomorrow_tasks(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> list[TrainingTaskDTO]:
        """Pull tomorrow_tasks from recent dynamic interview reports into the training plan."""
        tasks: list[TrainingTaskDTO] = []

        session_result = await db.execute(
            select(InterviewSessionEntity)
            .where(
                InterviewSessionEntity.user_id == user_id,
                InterviewSessionEntity.engine_type == InterviewEngineType.DYNAMIC.value,
                InterviewSessionEntity.status == SessionStatus.COMPLETED.value,
            )
            .order_by(InterviewSessionEntity.completed_at.desc())
            .limit(3)
        )
        dynamic_sessions = list(session_result.scalars().all())

        for session in dynamic_sessions:
            report_data = safe_json_loads(session.final_report_json, {})
            tomorrow_items = report_data.get("tomorrow_tasks", [])
            if not isinstance(tomorrow_items, list):
                continue

            for idx, item in enumerate(tomorrow_items):
                if not isinstance(item, dict):
                    continue
                tasks.append(
                    TrainingTaskDTO(
                        id=f"dyn-{session.session_id}-{idx}",
                        day=0,
                        title=str(item.get("title") or f"训练任务 {idx + 1}"),
                        task_type=str(item.get("task_type", "RETRY_TOPIC")),
                        priority=item.get("priority_score", 0.5) > 0.6 and "HIGH" or "MEDIUM",
                        estimate_minutes=20,
                        reason=str(item.get("reason") or item.get("action", "")),
                        source_session_id=session.session_id,
                        question_index=None,
                        action_path=f"/interview?sessionId={session.session_id}&mode=dynamic",
                        checklist=[
                            str(item.get("action", "完成练习")),
                            "对照报告中的参考答案自查",
                            "记录一个改进点",
                        ],
                    )
                )

        topic_profile = await dynamic_interview_persistence_service.get_user_topic_profile(db, user_id)
        for topic_key in topic_profile.get("low_score_topics", [])[:3]:
            topic_info = topic_profile.get("topic_counts", {}).get(topic_key, {})
            avg_score = topic_info.get("avg_score", 0) or 0
            tasks.append(
                TrainingTaskDTO(
                    id=f"dyn-retry-{topic_key}",
                    day=0,
                    title=f"重练低分 topic：{topic_key}",
                    task_type="RETRY_TOPIC",
                    priority="HIGH",
                    estimate_minutes=25,
                    reason=f"历史均分 {avg_score}，需要再练巩固",
                    source_session_id=None,
                    question_index=None,
                    action_path="/interview-hub",
                    checklist=["复习 topic 相关知识", "准备一个完整回答", "在教练模式下重练"],
                )
            )

        return tasks

    def _fill_daily_tasks(self, tasks: list[TrainingTaskDTO], days: int) -> None:
        templates = [
            ("daily-project-story", "口述项目闭环", "DAILY_REVIEW", "把目标、方案、结果压缩到 2 分钟"),
            ("daily-metric", "补一个量化指标", "DAILY_REVIEW", "为项目结果补充可验证数字"),
            ("daily-risk", "准备一个失败兜底回答", "DAILY_REVIEW", "覆盖异常、重试、降级和告警"),
            ("daily-question", "录音回答一道高频题", "DAILY_REVIEW", "训练表达结构和时间控制"),
        ]
        target_count = max(days * 2, days)
        cursor = 0
        while len(tasks) < target_count:
            key, title, task_type, reason = templates[cursor % len(templates)]
            tasks.append(
                TrainingTaskDTO(
                    id=f"{key}-{cursor}",
                    day=0,
                    title=title,
                    task_type=task_type,
                    priority="LOW",
                    estimate_minutes=15,
                    reason=reason,
                    action_path="/interview-hub",
                    checklist=["先写提纲", "口述并计时", "记录一个可改进点"],
                )
            )
            cursor += 1

    def _quick_wins(
        self,
        calibration: ScoreCalibrationDTO,
        analyses: list[ResumeAnalysisEntity],
    ) -> list[str]:
        wins = list(calibration.next_actions[:3])
        for analysis in analyses[:2]:
            suggestions = safe_json_loads(analysis.suggestions_json, [])
            for suggestion in suggestions:
                if isinstance(suggestion, dict) and suggestion.get("recommendation"):
                    wins.append(str(suggestion["recommendation"]))
                if len(wins) >= 5:
                    return wins
        return wins[:5]

    @staticmethod
    def _progress_dto(entity: TrainingTaskProgressEntity) -> TrainingTaskProgressDTO:
        return TrainingTaskProgressDTO(
            task_id=entity.task_id,
            status=entity.status.value,
            completed_at=TrainingService._datetime_label(entity.completed_at),
            notes=entity.notes,
        )

    @staticmethod
    def _latest_analysis(resume: ResumeEntity) -> ResumeAnalysisEntity | None:
        if not resume.analyses:
            return None
        return max(resume.analyses, key=lambda item: item.analyzed_at.timestamp() if item.analyzed_at else 0)

    @staticmethod
    def _dedupe_tasks(tasks: list[TrainingTaskDTO]) -> list[TrainingTaskDTO]:
        seen: set[str] = set()
        unique: list[TrainingTaskDTO] = []
        for task in tasks:
            if task.id in seen:
                continue
            seen.add(task.id)
            unique.append(task)
        return unique

    @staticmethod
    def _generated_from(
        resumes: list[ResumeEntity],
        analyses: list[ResumeAnalysisEntity],
        calibration: ScoreCalibrationDTO,
    ) -> list[str]:
        return [
            f"{len(resumes)} 份简历",
            f"{len(analyses)} 份简历分析",
            f"{calibration.evaluated_sessions} 份可训练面试报告",
            f"{calibration.total_questions} 道已评分题",
        ]

    @staticmethod
    def _calibration_summary(
        evaluated_sessions: int,
        total_questions: int,
        calibrated_score: int,
        confidence: int,
    ) -> str:
        if evaluated_sessions == 0 or total_questions == 0:
            return "暂无可用于评分校准的面试报告，完成一次开始面试或固定题模拟后可生成。"
        return f"已基于 {evaluated_sessions} 份报告、{total_questions} 道题生成校准视图，校准后均分 {calibrated_score}，可信度 {confidence}。"

    @staticmethod
    def _plan_summary(readiness_score: int, calibration: ScoreCalibrationDTO) -> str:
        if calibration.evaluated_sessions == 0:
            return "当前训练计划以建立首份评估样本为主。"
        if readiness_score >= 80:
            return "个人训练闭环已比较稳定，重点放在高质量复述和可验证指标。"
        if readiness_score >= 65:
            return "已具备训练闭环，优先补低分题、低可信评分和简历证据。"
        return "闭环已启动，但样本与证据还偏少，先补首轮报告和关键项目表达。"

    @staticmethod
    def _readiness_score(calibration: ScoreCalibrationDTO, resume_score: int) -> int:
        if calibration.total_questions == 0 and resume_score == 0:
            return 20
        if calibration.total_questions == 0:
            return max(30, round(resume_score * 0.7))
        score = calibration.calibrated_score * 0.55 + calibration.confidence * 0.25 + resume_score * 0.2
        return min(100, max(20, round(score)))

    @staticmethod
    def _calibration_actions(
        questions: list[CalibrationQuestionDTO],
        dimensions: list[CalibrationDimensionDTO],
    ) -> list[str]:
        actions = []
        high = [item for item in questions if item.review_priority == "HIGH"]
        if high:
            actions.append(f"先复核 {len(high)} 道高风险评分题，并用同题再练验证提升。")
        weak_dimensions = [item for item in dimensions if item.average_score < 70]
        if weak_dimensions:
            actions.append(f"优先补强 {weak_dimensions[0].name}，当前均分 {weak_dimensions[0].average_score}。")
        low_confidence = [item for item in questions if item.confidence < 60]
        if low_confidence:
            actions.append(f"为 {len(low_confidence)} 道低可信题补充要点覆盖或人工复核。")
        if not actions:
            actions.append("继续积累更多已评估回答，观察分数是否稳定。")
        return actions[:4]

    @staticmethod
    def _dimension_action(name: str, average_score: int, weak_count: int) -> str:
        subject = TrainingService._dimension_subject(name)
        if average_score < 65:
            return f"{subject}是当前低分项，建议每天安排专项口述训练。"
        if weak_count:
            return f"{subject}有 {weak_count} 道题低于 70 分，建议用同题再练拉齐。"
        return f"{subject}表现稳定，继续保持证据密度。"

    @staticmethod
    def _dimension_subject(name: str) -> str:
        if name.startswith("题型："):
            label = name.removeprefix("题型：").strip()
            return f"{label}类问题"
        return name

    @staticmethod
    def _question_action(score: int | None, confidence: int) -> str:
        if score is None:
            return "先补齐评分结果"
        if confidence < 60:
            return "先人工复核评分依据，再决定是否重练"
        if score < 60:
            return "立即同题再练，先补结构和关键证据"
        if score < 70:
            return "用 80 分回答模板重组后再练一次"
        if score < 80:
            return "补充量化结果和取舍细节"
        return "沉淀成可复用回答模板"

    @staticmethod
    def _dynamic_question_action(score: int | None, summary: dict[str, Any]) -> str:
        action = summary.get("next_training_action")
        if isinstance(action, str) and action.strip():
            return action.strip()
        if score is None:
            return "先查看动态面试报告，补齐 topic 评分"
        if score < 60:
            return "重练这个 topic，先补个人职责、指标和取舍"
        if score < 75:
            return "补一版结构化回答，再做一次限时复述"
        return "整理成动态面试可复用回答模板"

    @staticmethod
    def _task_priority(item: CalibrationQuestionDTO) -> str:
        delta = item.latest_retry_delta
        if delta is None:
            return item.review_priority
        if delta <= 0:
            return "HIGH"
        if item.latest_retry_score is not None and item.latest_retry_score < 70:
            return "HIGH"
        if delta < 10 or (item.latest_retry_score is not None and item.latest_retry_score < 80):
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _task_reason(item: CalibrationQuestionDTO) -> str:
        delta = item.latest_retry_delta
        if delta is None:
            return item.action
        if delta >= 10:
            return f"上次同题再练提升 {delta} 分，继续沉淀成稳定模板。"
        if delta > 0:
            return f"上次同题再练提升 {delta} 分，但还需要补量化结果和取舍细节。"
        if delta == 0:
            return "上次同题再练分数持平，优先重组回答结构。"
        return f"上次同题再练下降 {abs(delta)} 分，需要先回看 80 分答案再练。"

    @staticmethod
    def _task_checklist(item: CalibrationQuestionDTO) -> list[str]:
        delta = item.latest_retry_delta
        if delta is None:
            return ["先写 5 点提纲", "补个人决策和证据", "对照 80 分回答再提交"]
        if delta >= 10:
            return ["保留本次有效结构", "补 1 个量化指标", "整理成可复述模板"]
        if delta > 0:
            return ["保留提升点", "补充取舍细节", "再做一次限时口述"]
        return ["对照 80 分回答拆结构", "重写开头结论", "补足证据后再练一次"]

    @staticmethod
    def _retry_signal(delta: int | None) -> str | None:
        if delta is None:
            return None
        if delta >= 10:
            return f"重练 +{delta}"
        if delta > 0:
            return f"重练 +{delta}"
        if delta == 0:
            return "重练持平"
        return f"重练 {delta}"

    @staticmethod
    def _review_priority(score: int | None, confidence: int) -> str:
        if score is None or confidence < 55 or (score is not None and score < 60):
            return "HIGH"
        if confidence < 75 or score < 70:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _score_band(score: int | None) -> str:
        if score is None:
            return "无有效评分"
        if score < 60:
            return "风险"
        if score < 70:
            return "待提升"
        if score < 80:
            return "可面试"
        if score < 90:
            return "有竞争力"
        return "优秀"

    @staticmethod
    def _confidence_label(confidence: int) -> str:
        if confidence >= 80:
            return "高"
        if confidence >= 60:
            return "中"
        return "低"

    @staticmethod
    def _calibrated_question_score(score: int | None, baseline: int, confidence: int) -> int | None:
        if score is None:
            return None
        if baseline <= 0:
            return score
        weight = confidence / 100
        return round(score * weight + baseline * (1 - weight))

    @staticmethod
    def _evidence_count(evaluation: dict[str, Any]) -> int:
        keys = (
            "feedback",
            "covered_points",
            "missed_points",
            "errors",
            "dimensions",
            "interviewer_judgement",
            "answer_issues",
            "answer_framework",
            "answer_80",
            "answer_90",
            "next_practice_question",
        )
        return sum(1 for key in keys if TrainingService._has_value(evaluation.get(key)))

    @staticmethod
    def _dynamic_evidence_count(summary: dict[str, Any]) -> int:
        keys = (
            "evidence_snippet",
            "main_question",
            "initial_score",
            "final_score",
            "best_score",
            "score_delta",
            "strengths",
            "risks",
            "gaps",
            "next_training_action",
        )
        return sum(1 for key in keys if TrainingService._has_value(summary.get(key)))

    @staticmethod
    def _has_any_summary_list(summary: dict[str, Any], keys: tuple[str, ...]) -> bool:
        return any(isinstance(summary.get(key), list) and len(summary.get(key)) > 0 for key in keys)

    @staticmethod
    def _has_any_list(evaluation: dict[str, Any], keys: tuple[str, ...]) -> bool:
        return any(isinstance(evaluation.get(key), list) and len(evaluation.get(key)) > 0 for key in keys)

    @staticmethod
    def _has_value(value: Any) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list | dict):
            return bool(value)
        return value is not None

    @staticmethod
    def _non_empty_text(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _score_or_none(value: Any) -> int | None:
        if isinstance(value, int | float) and value > 0:
            return round(value)
        return None

    @staticmethod
    def _average_score(values: list[int | None]) -> int:
        scores = [value for value in values if isinstance(value, int | float) and value > 0]
        return round(mean(scores)) if scores else 0

    @staticmethod
    def _has_dynamic_report(session: InterviewSessionEntity) -> bool:
        return (
            session.engine_type == InterviewEngineType.DYNAMIC.value
            and session.status == SessionStatus.COMPLETED
            and bool(session.final_report_json)
        )

    @staticmethod
    def _dynamic_retry_source_key(session: InterviewSessionEntity) -> str | None:
        plan_summary = safe_json_loads(session.plan_summary_json, {})
        if not isinstance(plan_summary, dict):
            return None
        source = plan_summary.get("retry_source_session_id")
        return str(source) if source else None

    @staticmethod
    def _dynamic_type_label(question_type: str | None) -> str:
        key = str(question_type or "").removeprefix("dynamic_").upper()
        return DYNAMIC_TYPE_LABELS.get(key, key or "动态面试")

    @staticmethod
    def _clamp(value: int, minimum: int, maximum: int) -> int:
        return min(maximum, max(minimum, value))

    @staticmethod
    def _short_text(text: str, limit: int) -> str:
        normalized = " ".join(text.split())
        return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."

    @staticmethod
    def _day_focus(tasks: list[TrainingTaskDTO], day: int) -> str:
        if not tasks:
            return "保持训练节奏"
        if any(task.priority == "HIGH" for task in tasks):
            return "优先处理高风险短板"
        if day <= 2:
            return "补齐项目证据"
        return "稳定表达与复盘"

    @staticmethod
    def _date_label(value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        return datetime.now(timezone.utc).date().isoformat()

    @staticmethod
    def _datetime_label(value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat()
        return None

    @staticmethod
    def _datetime_sort_value(value: Any) -> float:
        if not isinstance(value, datetime):
            return 0
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).timestamp()
        return value.timestamp()

    @staticmethod
    def _trend_sort_key(point: TrainingTrendPointDTO) -> tuple[float, str, str]:
        return (
            TrainingService._iso_datetime_sort_value(point.occurred_at),
            point.metric_type,
            point.label,
        )

    @staticmethod
    def _iso_datetime_sort_value(value: str | None) -> float:
        if not value:
            return 0
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0
        return TrainingService._datetime_sort_value(parsed)

    @staticmethod
    def _latest_score(points: list[TrainingTrendPointDTO], metric_type: str) -> int | None:
        for point in reversed(points):
            if point.metric_type == metric_type and point.score is not None:
                return point.score
        return None

    @staticmethod
    def _latest_delta(points: list[TrainingTrendPointDTO], metric_type: str) -> int | None:
        for point in reversed(points):
            if point.metric_type == metric_type and point.delta is not None:
                return point.delta
        return None

    @staticmethod
    def _trend_summary(
        latest_interview_score: int | None,
        latest_resume_score: int | None,
        latest_retry_delta: int | None,
        completed_task_count: int,
    ) -> str:
        if (
            latest_interview_score is None
            and latest_resume_score is None
            and latest_retry_delta is None
            and completed_task_count == 0
        ):
            return "暂无趋势数据，先完成一次简历分析或模拟面试。"
        parts = []
        if latest_interview_score is not None:
            parts.append(f"最近面试分 {latest_interview_score}")
        if latest_resume_score is not None:
            parts.append(f"最近简历分 {latest_resume_score}")
        if latest_retry_delta is not None:
            parts.append(f"最近重练{TrainingService._delta_text(latest_retry_delta)}")
        if completed_task_count:
            parts.append(f"已完成 {completed_task_count} 个训练任务")
        return "，".join(parts) + "。"

    @staticmethod
    def _retry_delta_rank(delta: int | None) -> int:
        if delta is None:
            return 2
        if delta <= 0:
            return 0
        if delta < 10:
            return 1
        return 3

    @staticmethod
    def _retry_trend_label(delta: int) -> str:
        return f"同题再练{TrainingService._delta_text(delta)}"

    @staticmethod
    def _delta_text(delta: int) -> str:
        if delta > 0:
            return f" +{delta} 分"
        if delta == 0:
            return "持平"
        return f" {delta} 分"

    @staticmethod
    def _evaluation_by_index(evaluations: list[dict], question_index: int) -> dict:
        return next((item for item in evaluations if item.get("question_index") == question_index), {})


training_service = TrainingService()
