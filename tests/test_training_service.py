import json
from datetime import datetime, timezone

import pytest

from app.modules.interview.models import InterviewAnswerEntity, InterviewSessionEntity, SessionStatus
from app.modules.interview.schemas import InterviewQuestionDTO
from app.modules.training.models import TrainingTaskProgressEntity, TrainingTaskStatus
from app.modules.training.schemas import TrainingTaskDTO
from app.modules.training.service import TrainingService


def _session(
    entity_id: int,
    session_id: str,
    *,
    overall_score: int,
    answer_score: int | None = None,
    completed_at: datetime,
    retry_source_session_id: str | None = None,
    retry_source_question_index: int | None = None,
) -> InterviewSessionEntity:
    question = InterviewQuestionDTO(
        question_index=0,
        question=f"{session_id} question",
        category="项目介绍",
        question_type="project",
        retry_source_session_id=retry_source_session_id,
        retry_source_question_index=retry_source_question_index,
    )
    entity = InterviewSessionEntity(
        id=entity_id,
        user_id=1,
        session_id=session_id,
        skill_id="demo",
        difficulty="mid",
        total_questions=1,
        current_question_index=1,
        status=SessionStatus.EVALUATED,
        questions_json=json.dumps([question.model_dump()], ensure_ascii=False),
        overall_score=overall_score,
        completed_at=completed_at,
        created_at=completed_at,
    )
    if answer_score is not None:
        entity.answers = [
            InterviewAnswerEntity(
                session_id=entity_id,
                question_index=0,
                question=question.question,
                category=question.category,
                user_answer="这是一个足够长的回答，用来保证评分校准不会因为回答过短而降低可信度。",
                score=answer_score,
                feedback="反馈完整。",
                key_points_json=json.dumps(
                    {
                        "question_type": "project",
                        "dimensions": {"authenticity": answer_score, "technical_depth": answer_score},
                        "interviewer_judgement": "证据充足。",
                        "answer_issues": ["指标还可以更清楚"],
                        "answer_framework": ["目标", "方案", "结果"],
                        "answer_80": "80 分回答",
                        "answer_90": "90 分回答",
                        "next_practice_question": "继续追问。",
                    },
                    ensure_ascii=False,
                ),
            )
        ]
    else:
        entity.answers = []
    return entity


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 28, hour, minute, tzinfo=timezone.utc)


def test_retry_summary_handles_score_drop():
    service = TrainingService()
    source = _session(1, "source", overall_score=70, answer_score=70, completed_at=_at(9))
    retry = _session(
        2,
        "retry-drop",
        overall_score=60,
        answer_score=60,
        completed_at=_at(10),
        retry_source_session_id="source",
        retry_source_question_index=0,
    )

    summary = service._build_retry_summaries([source, retry])[("source", 0)]

    assert summary.attempt_count == 1
    assert summary.latest_retry_delta == -10
    assert service._retry_signal(summary.latest_retry_delta) == "重练 -10"


def test_retry_summary_handles_flat_retry():
    service = TrainingService()
    source = _session(1, "source", overall_score=70, answer_score=70, completed_at=_at(9))
    retry = _session(
        2,
        "retry-flat",
        overall_score=70,
        answer_score=70,
        completed_at=_at(10),
        retry_source_session_id="source",
        retry_source_question_index=0,
    )

    summary = service._build_retry_summaries([source, retry])[("source", 0)]

    assert summary.latest_retry_delta == 0
    assert service._retry_signal(summary.latest_retry_delta) == "重练持平"


def test_retry_summary_uses_latest_attempt_when_multiple_retries_exist():
    service = TrainingService()
    source = _session(1, "source", overall_score=70, answer_score=70, completed_at=_at(9))
    earlier_retry = _session(
        2,
        "retry-earlier",
        overall_score=65,
        answer_score=65,
        completed_at=_at(10),
        retry_source_session_id="source",
        retry_source_question_index=0,
    )
    later_retry = _session(
        3,
        "retry-later",
        overall_score=82,
        answer_score=82,
        completed_at=_at(11),
        retry_source_session_id="source",
        retry_source_question_index=0,
    )

    summary = service._build_retry_summaries([source, earlier_retry, later_retry])[("source", 0)]

    assert summary.attempt_count == 2
    assert summary.latest_retry_session_id == "retry-later"
    assert summary.latest_retry_delta == 12


@pytest.mark.asyncio
async def test_calibration_baseline_excludes_retry_sessions(monkeypatch):
    service = TrainingService()
    source = _session(1, "source", overall_score=60, answer_score=50, completed_at=_at(9))
    retry = _session(
        2,
        "retry",
        overall_score=100,
        answer_score=100,
        completed_at=_at(10),
        retry_source_session_id="source",
        retry_source_question_index=0,
    )

    async def fake_find_all(db, user_id=None):
        return [retry, source]

    monkeypatch.setattr("app.modules.training.service.interview_persistence_service.find_all", fake_find_all)

    calibration = await service.get_score_calibration(db=None, user_id=1)

    assert calibration.evaluated_sessions == 1
    assert calibration.average_raw_score == 50
    assert calibration.calibrated_score == 50
    assert calibration.questions[0].retry_attempt_count == 1
    assert calibration.questions[0].latest_retry_delta == 50


@pytest.mark.asyncio
async def test_trend_uses_actual_time_for_same_day_interviews(monkeypatch):
    service = TrainingService()
    morning = _session(1, "morning", overall_score=61, completed_at=_at(9))
    evening = _session(2, "evening", overall_score=82, completed_at=_at(18))

    async def fake_find_all_sessions(db, user_id=None):
        return [morning, evening]

    async def fake_find_all_resumes(db, user_id=None):
        return []

    async def fake_progress(db, user_id):
        return []

    async def fake_task_lookup(db, user_id, days=14):
        return {}

    monkeypatch.setattr("app.modules.training.service.interview_persistence_service.find_all", fake_find_all_sessions)
    monkeypatch.setattr("app.modules.training.service.resume_persistence_service.find_all", fake_find_all_resumes)
    monkeypatch.setattr(service, "_get_progress_items", fake_progress)
    monkeypatch.setattr(service, "_build_current_task_lookup", fake_task_lookup)

    trend = await service.get_training_trend(db=None, user_id=1)

    assert trend.latest_interview_score == 82
    assert [point.score for point in trend.trend if point.metric_type == "INTERVIEW_SCORE"] == [61, 82]
    assert trend.trend[-1].occurred_at == evening.completed_at.isoformat()


@pytest.mark.asyncio
async def test_trend_counts_only_current_plan_tasks(monkeypatch):
    service = TrainingService()
    valid_task = TrainingTaskDTO(
        id="retry-source-0",
        day=1,
        title="重练",
        task_type="RETRY_LOW_SCORE",
        priority="HIGH",
        estimate_minutes=25,
        reason="可信任务",
    )
    trusted = TrainingTaskProgressEntity(
        user_id=1,
        task_id="retry-source-0",
        status=TrainingTaskStatus.COMPLETED,
        completed_at=_at(12),
    )
    forged = TrainingTaskProgressEntity(
        user_id=1,
        task_id="client-forged-task",
        status=TrainingTaskStatus.COMPLETED,
        completed_at=_at(13),
    )

    async def fake_find_all_sessions(db, user_id=None):
        return []

    async def fake_find_all_resumes(db, user_id=None):
        return []

    async def fake_progress(db, user_id):
        return [trusted, forged]

    async def fake_task_lookup(db, user_id, days=14):
        return {valid_task.id: valid_task}

    monkeypatch.setattr("app.modules.training.service.interview_persistence_service.find_all", fake_find_all_sessions)
    monkeypatch.setattr("app.modules.training.service.resume_persistence_service.find_all", fake_find_all_resumes)
    monkeypatch.setattr(service, "_get_progress_items", fake_progress)
    monkeypatch.setattr(service, "_build_current_task_lookup", fake_task_lookup)

    trend = await service.get_training_trend(db=None, user_id=1)

    assert trend.completed_task_count == 1
    assert [point.completed_tasks for point in trend.trend if point.metric_type == "TRAINING_DONE"] == [1]
