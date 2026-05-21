import json
from datetime import datetime

from app.modules.interview.models import InterviewAnswerEntity, InterviewSessionEntity
from app.modules.interview.persistence_service import interview_persistence_service
from app.modules.interview.project_drill_schemas import ProjectDrillRequest
from app.modules.interview.project_drill_service import project_drill_service
from app.modules.interview.schemas import InterviewQuestionDTO
from app.modules.resume.schemas import (
    AnalysisHistoryDTO,
    ProjectInfo,
    ResumeDetailDTO,
    ResumeProfile,
    TechStack,
)


def test_project_drill_generates_practical_follow_up_questions():
    resume = ResumeDetailDTO(
        id=11,
        filename="resume.pdf",
        file_size=2048,
        content_type="application/pdf",
        storage_url=None,
        uploaded_at=datetime(2026, 5, 21, 10, 0, 0),
        resume_text="智能面试系统项目 " * 80,
        analyses=[
            AnalysisHistoryDTO(
                id=3,
                overall_score=78,
                analyzed_at=datetime(2026, 5, 21, 11, 0, 0),
                profile=ResumeProfile(
                    projects=[
                        ProjectInfo(
                            name="智能面试系统",
                            role="后端开发",
                            tech_stack=["FastAPI", "PostgreSQL", "Redis"],
                            description="支持简历解析、诊断和模拟面试。",
                            highlights=["完成诊断服务"],
                        )
                    ],
                    tech_stacks=[TechStack(name="FastAPI", proficiency="熟悉", context="后端接口")],
                    experience_level="junior",
                    has_projects=True,
                    summary="有后端项目经验",
                ),
            )
        ],
    )
    request = ProjectDrillRequest(
        resume_id=11,
        target_role="AI 应用后端开发",
        target_company="面试科技",
        jd_text="负责 RAG、Agent、后端接口和服务稳定性。",
    )

    drill = project_drill_service.build_drill(request, resume)

    assert drill.resume_id == 11
    assert drill.selected_project.name == "智能面试系统"
    assert len(drill.questions) >= 6
    assert any(question.category == "技术取舍" for question in drill.questions)
    assert all(question.answer_framework for question in drill.questions)
    assert all(question.red_flags for question in drill.questions)
    assert len(drill.practice_checklist) >= 3

    session_questions = project_drill_service.build_session_questions(drill)

    assert len(session_questions) == len(drill.questions)
    assert session_questions[0].type == "PROJECT_DRILL"
    assert session_questions[0].question_type == "project"
    assert session_questions[0].topic_summary == drill.questions[0].risk
    assert session_questions[0].reference_answer
    assert session_questions[0].key_points
    assert all(question.question_type == "project" for question in session_questions)


def test_project_drill_handles_resume_without_projects():
    resume = ResumeDetailDTO(
        id=12,
        filename="empty.pdf",
        file_size=1024,
        content_type="application/pdf",
        storage_url=None,
        uploaded_at=datetime(2026, 5, 21, 10, 0, 0),
        resume_text="技能：Java、MySQL。",
        analyses=[
            AnalysisHistoryDTO(
                id=4,
                overall_score=55,
                analyzed_at=datetime(2026, 5, 21, 11, 0, 0),
                profile=ResumeProfile(
                    projects=[],
                    tech_stacks=[],
                    experience_level="unknown",
                    has_projects=False,
                    summary="项目信息不足",
                ),
            )
        ],
    )
    request = ProjectDrillRequest(resume_id=12, target_role="Java 后端开发")

    drill = project_drill_service.build_drill(request, resume)

    assert drill.selected_project.name == "待补充核心项目"
    assert "缺少可被追问的项目证据" in drill.risk_summary
    assert len(drill.questions) >= 6


def test_project_question_type_is_restored_in_saved_report_detail():
    entity = InterviewSessionEntity(
        user_id=1,
        session_id="session-1",
        skill_id="project-drill",
        difficulty="校招",
        total_questions=1,
    )
    entity.answers = [
        InterviewAnswerEntity(
            question_index=0,
            question="为什么选择 FastAPI？",
            category="技术取舍",
            user_answer="因为异步支持和接口文档比较适合。",
            score=72,
            feedback="面试官判断：基本说清。当前风险点：缺少对比。80分改法：补充 Flask/Django 对比。下一步追问：并发瓶颈怎么处理？",
            key_points_json=json.dumps(
                {
                    "schema": "interview_evaluation_v1",
                    "question_type": "project",
                    "dimensions": {
                        "authenticity": 70,
                        "technical_depth": 68,
                        "depth": 60,
                        "expression": 75,
                    },
                },
                ensure_ascii=False,
            ),
        )
    ]
    questions = [
        InterviewQuestionDTO(
            question_index=0,
            question="为什么选择 FastAPI？",
            category="技术取舍",
            question_type="project",
        )
    ]

    evaluations = interview_persistence_service.build_question_evaluations(entity, questions)

    assert evaluations[0]["question_type"] == "project"
    assert evaluations[0]["dimensions"]["technical_depth"] == 68
