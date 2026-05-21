from datetime import datetime

from app.modules.interview.diagnosis_schemas import InterviewDiagnosisRequest
from app.modules.interview.diagnosis_service import interview_diagnosis_service
from app.modules.resume.schemas import (
    AnalysisHistoryDTO,
    ProjectInfo,
    ResumeDetailDTO,
    ResumeProfile,
    Suggestion,
    TechStack,
)


def test_diagnosis_without_resume_still_returns_practical_tasks():
    request = InterviewDiagnosisRequest(target_role="Java 后端开发", target_company="目标公司")

    diagnosis = interview_diagnosis_service.build_diagnosis(request)

    assert diagnosis.readiness_score < 60
    assert diagnosis.readiness_level == "高风险"
    assert len(diagnosis.weaknesses) >= 3
    assert len(diagnosis.today_tasks) >= 3
    assert len(diagnosis.seven_day_plan) == 7
    assert any("JD" in item.title for item in diagnosis.weaknesses)


def test_diagnosis_uses_resume_profile_for_project_risks():
    analysis = AnalysisHistoryDTO(
        id=1,
        overall_score=76,
        content_score=70,
        structure_score=78,
        skill_match_score=62,
        expression_score=68,
        project_score=60,
        summary="项目经历较完整，但技术取舍和指标表达不足。",
        analyzed_at=datetime(2026, 5, 21, 9, 0, 0),
        strengths=["有完整项目经历"],
        suggestions=[
            Suggestion(
                category="项目经历",
                priority="高",
                issue="项目结果缺少量化指标",
                recommendation="补充性能、规模或业务结果指标。",
            )
        ],
        profile=ResumeProfile(
            projects=[
                ProjectInfo(
                    name="智能面试系统",
                    role="后端开发",
                    tech_stack=["FastAPI", "PostgreSQL"],
                    description="实现简历解析和模拟面试。",
                    highlights=["完成面试会话编排"],
                )
            ],
            tech_stacks=[TechStack(name="FastAPI", proficiency="熟悉", context="项目后端")],
            experience_level="junior",
            has_projects=True,
            summary="后端项目经验",
        ),
    )
    resume = ResumeDetailDTO(
        id=7,
        filename="resume.pdf",
        file_size=1024,
        content_type="application/pdf",
        storage_url=None,
        uploaded_at=datetime(2026, 5, 21, 8, 0, 0),
        resume_text="智能面试系统 " * 80,
        analyses=[analysis],
    )
    request = InterviewDiagnosisRequest(
        resume_id=7,
        target_role="AI 应用后端开发",
        target_company="面试科技",
        jd_text="负责 RAG、Agent、后端接口、数据库设计和服务稳定性。",
    )

    diagnosis = interview_diagnosis_service.build_diagnosis(request, resume)

    assert diagnosis.resume_id == 7
    assert diagnosis.resume_filename == "resume.pdf"
    assert diagnosis.readiness_score >= 60
    assert any("智能面试系统" in item.question for item in diagnosis.resume_risks)
    assert any(item.severity == "HIGH" for item in diagnosis.weaknesses)
    assert any("模型应用链路" == item.title for item in diagnosis.knowledge_gaps)
