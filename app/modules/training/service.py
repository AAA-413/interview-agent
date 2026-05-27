from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_persistence_service import safe_json_loads
from app.modules.interview.models import InterviewSessionEntity, SessionStatus
from app.modules.interview.persistence_service import interview_persistence_service
from app.modules.resume.models import ResumeAnalysisEntity, ResumeEntity
from app.modules.resume.persistence_service import resume_persistence_service
from app.modules.training.schemas import (
    CalibrationDimensionDTO,
    CalibrationQuestionDTO,
    PersonalTrainingPlanDTO,
    ScoreCalibrationDTO,
    TrainingDayDTO,
    TrainingTaskDTO,
)

PROJECT_DIMENSION_LABELS = {
    "authenticity": "项目真实性",
    "technical_depth": "技术深度",
    "depth": "回答深度",
    "expression": "表达结构",
}

PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


class TrainingService:
    async def get_score_calibration(self, db: AsyncSession, user_id: int) -> ScoreCalibrationDTO:
        sessions = await interview_persistence_service.find_all(db, user_id=user_id)
        evaluated_sessions = [item for item in sessions if item.status == SessionStatus.EVALUATED]
        baseline = self._average_score([item.overall_score for item in evaluated_sessions])

        question_items: list[CalibrationQuestionDTO] = []
        dimension_scores: dict[str, list[int]] = defaultdict(list)
        for session in evaluated_sessions:
            questions = interview_persistence_service.parse_questions_json(session.questions_json)
            evaluations = interview_persistence_service.build_question_evaluations(session, questions)
            for evaluation in evaluations:
                item = self._build_question_calibration(session, evaluation, baseline)
                question_items.append(item)

                if item.raw_score is not None:
                    dimension_scores[f"题型：{item.category or '综合能力'}"].append(item.raw_score)

                dimensions = evaluation.get("dimensions")
                if isinstance(dimensions, dict):
                    for key, label in PROJECT_DIMENSION_LABELS.items():
                        value = dimensions.get(key)
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
            evaluated_sessions=len(evaluated_sessions),
            total_questions=len(question_items),
            average_raw_score=self._average_score(raw_scores),
            calibrated_score=calibrated_score,
            confidence=confidence,
            confidence_label=self._confidence_label(confidence) if confidence else "暂无",
            review_needed_count=review_needed_count,
            high_risk_count=high_risk_count,
            summary=self._calibration_summary(
                len(evaluated_sessions), len(question_items), calibrated_score, confidence
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

    def _build_question_calibration(
        self,
        session: InterviewSessionEntity,
        evaluation: dict[str, Any],
        baseline: int,
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
        )

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
            tasks.append(
                TrainingTaskDTO(
                    id=f"retry-{item.session_id}-{item.question_index}",
                    day=0,
                    title=f"重练：{self._short_text(item.question, 28)}",
                    task_type="RETRY_LOW_SCORE",
                    priority=item.review_priority,
                    estimate_minutes=25,
                    reason=item.action,
                    source_session_id=item.session_id,
                    question_index=item.question_index,
                    action_path=f"/interviews/{item.session_id}",
                    checklist=["先写 5 点提纲", "补个人决策和证据", "对照 80 分回答再提交"],
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
            key=lambda item: (PRIORITY_ORDER.get(item.priority, 9), item.task_type, item.id),
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
            f"{calibration.evaluated_sessions} 份已评估面试报告",
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
            return "暂无已评估面试报告，完成一次模拟面试后可生成评分校准。"
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
        if average_score < 65:
            return f"{name} 是当前短板，建议每天安排专项口述训练。"
        if weak_count:
            return f"{name} 有 {weak_count} 道题低于 70 分，建议用同题再练拉齐。"
        return f"{name} 表现稳定，继续保持证据密度。"

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


training_service = TrainingService()
