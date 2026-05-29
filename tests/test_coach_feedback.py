from app.modules.interview.evaluation_service import (
    QaRecord,
    _KnowledgeEvalDTO,
    unified_evaluation_service,
)
from app.modules.interview.schemas import QuestionEvaluationDTO


def test_fallback_coach_feedback_contains_trainable_answers():
    qa = QaRecord(
        question_index=0,
        question="为什么在项目里选择 Redis？",
        category="技术取舍",
        user_answer="因为 Redis 快。",
        question_type="project",
    )

    fields = unified_evaluation_service._build_fallback_coach_fields(
        qa=qa,
        score=45,
        feedback="回答过短，缺少选型理由。",
        question_type="project",
    )

    assert fields["interviewer_judgement"]
    assert fields["answer_issues"]
    assert "技术取舍" in fields["answer_framework"]
    assert fields["answer_80"]
    assert fields["answer_90"]
    assert fields["next_practice_question"].startswith("请重新回答")


def test_question_evaluation_dto_exposes_coach_fields():
    dto = QuestionEvaluationDTO(
        question_index=0,
        question="什么是索引覆盖？",
        score=68,
        interviewer_judgement="基本理解，但缺少执行计划解释。",
        answer_issues=["缺少 explain 证据"],
        answer_framework=["定义", "原理", "场景"],
        answer_80="覆盖索引是查询字段都能从索引中获取，减少回表。",
        answer_90="在 80 分回答基础上补充执行计划、最左前缀和失效场景。",
        next_practice_question="请解释一次覆盖索引失效的情况。",
    )

    payload = dto.model_dump()

    assert payload["answer_80"].startswith("覆盖索引")
    assert payload["next_practice_question"] == "请解释一次覆盖索引失效的情况。"


async def test_reference_free_knowledge_question_stays_knowledge_and_caps_score(monkeypatch):
    qa = QaRecord(
        question_index=0,
        question="请解释一下 CAP 理论。",
        category="分布式系统",
        user_answer="CAP 是一致性、可用性、分区容错，分布式系统遇到网络分区时要做取舍。",
        question_type="knowledge",
    )

    async def fake_evaluate_reference_free_knowledge_question(*_args, **_kwargs):
        return _KnowledgeEvalDTO(
            score=92,
            covered_points=["CAP 三要素", "分区时取舍"],
            missed_points=["工程场景"],
            errors=[],
            feedback="回答较完整。",
            interviewerJudgement="基础理解到位。",
            answerIssues=[],
            answerFramework=["定义", "取舍", "场景"],
            answer80="通用参考：CAP 描述一致性、可用性、分区容错之间的取舍。",
            answer90="通用参考：结合注册中心、数据库复制等场景说明取舍。",
            nextPracticeQuestion="请举例说明 CP 和 AP 的系统选择。",
        )

    monkeypatch.setattr(
        unified_evaluation_service,
        "evaluate_reference_free_knowledge_question",
        fake_evaluate_reference_free_knowledge_question,
    )

    evaluations = await unified_evaluation_service._evaluate_by_type(
        chat_model=None,
        session_id="session-1",
        qa_records=[qa],
        resume_context="",
    )

    assert evaluations[0].question_type == "knowledge"
    assert evaluations[0].dimensions is None
    assert evaluations[0].score == 75
    assert "保守口径最高计 75 分" in evaluations[0].feedback
