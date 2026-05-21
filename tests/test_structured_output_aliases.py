import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("AI_BAILIAN_API_KEY", "dummy-key")

from app.modules.interview.evaluation_service import _QuestionEvalDTO, _SummaryDTO
from app.modules.interview.question_service import _FollowUpDecisionDTO, _QuestionDTO
from app.modules.resume.grading_service import _AnalysisDTO


def test_interview_question_dto_accepts_llm_camel_case():
    dto = _QuestionDTO.model_validate(
        {
            "question": "解释 asyncio 的事件循环",
            "topicSummary": "asyncio",
            "questionType": "knowledge",
            "referenceAnswer": "事件循环负责调度协程。",
            "keyPoints": [{"point": "事件循环", "scoreRange": "0-10", "weight": "1"}],
        }
    )

    assert dto.topic_summary == "asyncio"
    assert dto.question_type == "knowledge"
    assert dto.reference_answer == "事件循环负责调度协程。"
    assert dto.key_points[0].score_range == "0-10"


def test_follow_up_decision_dto_accepts_llm_camel_case():
    dto = _FollowUpDecisionDTO.model_validate(
        {
            "shouldFollowUp": True,
            "followUpQuestion": "那它如何处理阻塞调用？",
            "referenceAnswer": "需要放到 executor 或改用异步库。",
            "keyPoints": [{"point": "executor", "scoreRange": "0-10", "weight": "1"}],
            "reason": "回答缺少阻塞处理细节",
        }
    )

    assert dto.should_follow_up is True
    assert dto.follow_up_question == "那它如何处理阻塞调用？"
    assert dto.reference_answer == "需要放到 executor 或改用异步库。"
    assert dto.key_points[0].score_range == "0-10"


def test_evaluation_dtos_accept_llm_camel_case():
    question_eval = _QuestionEvalDTO.model_validate(
        {
            "questionIndex": 2,
            "score": 88,
            "feedback": "回答完整",
            "referenceAnswer": "参考答案",
            "keyPoints": ["事件循环"],
            "questionType": "knowledge",
            "coveredPoints": ["事件循环"],
            "missedPoints": ["阻塞处理"],
        }
    )
    summary = _SummaryDTO.model_validate({"overallFeedback": "整体扎实", "strengths": ["基础好"]})

    assert question_eval.question_index == 2
    assert question_eval.reference_answer == "参考答案"
    assert question_eval.covered_points == ["事件循环"]
    assert question_eval.missed_points == ["阻塞处理"]
    assert summary.overall_feedback == "整体扎实"


def test_resume_analysis_dto_accepts_llm_camel_case():
    dto = _AnalysisDTO.model_validate(
        {
            "overallScore": 91,
            "scoreDetail": {
                "projectScore": 36,
                "skillMatchScore": 18,
                "contentScore": 14,
                "structureScore": 13,
                "expressionScore": 10,
            },
            "summary": "候选人项目经验清晰",
            "strengths": ["项目完整"],
            "suggestions": [
                {
                    "category": "表达",
                    "priority": "MEDIUM",
                    "issue": "量化不足",
                    "recommendation": "补充指标",
                }
            ],
            "profile": {
                "projects": [
                    {
                        "name": "面试助手",
                        "role": "后端",
                        "techStack": ["FastAPI"],
                        "description": "AI 面试系统",
                        "highlights": ["RAG"],
                    }
                ],
                "techStacks": [{"name": "Python", "proficiency": "熟练", "context": "后端开发"}],
                "experienceLevel": "mid",
                "hasProjects": True,
                "summary": "后端方向",
            },
        }
    )

    assert dto.overall_score == 91
    assert dto.score_detail.project_score == 36
    assert dto.profile.projects[0].tech_stack == ["FastAPI"]
    assert dto.profile.tech_stacks[0].name == "Python"
    assert dto.profile.experience_level == "mid"
    assert dto.profile.has_projects is True
