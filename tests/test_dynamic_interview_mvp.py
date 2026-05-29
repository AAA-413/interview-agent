import json
from datetime import datetime

from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service
from app.modules.interview.dynamic_service import (
    CoachInterviewPolicy,
    DynamicAnswerEvaluationService,
    DynamicInterviewReportService,
    DynamicRagCoachService,
    InterviewPlanService,
)
from app.modules.interview.jd_parse_service import jd_parse_service
from app.modules.interview.models import InterviewSessionEntity, InterviewTopicEntity, InterviewTurnEntity
from app.modules.interview.schemas import (
    DynamicInterviewCreateRequest,
    DynamicInterviewCreateResponse,
    DynamicRagCitationDTO,
    DynamicTopicDTO,
    DynamicTurnDTO,
    StructuredJD,
)
from app.modules.resume.schemas import AnalysisHistoryDTO, ProjectInfo, ResumeDetailDTO, ResumeProfile, TechStack


def _resume_detail(project: ProjectInfo) -> ResumeDetailDTO:
    return ResumeDetailDTO(
        id=16,
        filename="resume.pdf",
        file_size=2048,
        uploaded_at=datetime(2026, 5, 28, 9, 0, 0),
        resume_text=f"{project.name} {project.description}",
        analyses=[
            AnalysisHistoryDTO(
                id=9,
                analyzed_at=datetime(2026, 5, 28, 9, 30, 0),
                profile=ResumeProfile(
                    projects=[project],
                    tech_stacks=[TechStack(name="FastAPI", proficiency="熟悉", context="后端接口")],
                    experience_level="intern",
                    has_projects=True,
                    summary="有 AI 应用后端项目经验",
                ),
            )
        ],
    )


def test_interview_plan_builds_four_coach_topics_and_keeps_jd_only_mcp_non_project():
    jd = "AI Agent 开发实习生，负责知识库系统后端开发，要求熟悉 MCP 工具接入和接口稳定性。"
    structured = jd_parse_service.parse(jd, target_role="AI Agent 开发实习生", skill_id="ai-agent")
    project = ProjectInfo(
        name="智能面试系统",
        role="后端开发",
        tech_stack=["FastAPI", "Redis"],
        description="支持简历解析、模拟面试和报告生成。",
        highlights=["完成异步任务流水线", "优化接口响应"],
    )
    request = DynamicInterviewCreateRequest(
        resume_id=16,
        target_role="AI Agent 开发实习生",
        jd_text=jd,
        skill_id="ai-agent",
    )

    topics, plan_summary = InterviewPlanService().build_plan(request, structured, _resume_detail(project))

    assert len(topics) == 4
    assert [topic.question_type for topic in topics].count("PROJECT") == 2
    assert [topic.question_type for topic in topics].count("KNOWLEDGE") == 1
    assert [topic.question_type for topic in topics].count("SYSTEM_DESIGN") == 1
    assert all(topic.evidence_snippet for topic in topics if topic.question_type == "PROJECT")
    assert any(topic.topic_key == "mcp_tool_integration" and topic.question_type == "KNOWLEDGE" for topic in topics)
    assert not any(topic.topic_key == "mcp_tool_integration" and topic.question_type == "PROJECT" for topic in topics)
    assert plan_summary["question_type_mix"] == {"PROJECT": 2, "KNOWLEDGE": 1, "SYSTEM_DESIGN": 1}


def test_coach_mode_first_answer_returns_retry_hint_without_full_answer():
    topic = DynamicTopicDTO(
        topic_key="rag_multi_channel_retrieval",
        topic_title="RAG 多通道检索",
        skill_key="rag",
        question_type="PROJECT",
        source_type="resume",
        evidence_snippet="智能问答项目：向量检索 + BM25 多路召回，Cross-Encoder 重排序。",
        main_question="请讲清楚 RAG 多通道检索链路和你的贡献。",
        topic_order=1,
    )
    turn = DynamicTurnDTO(turn_type="MAIN", turn_order=1, question=topic.main_question)
    evaluator = DynamicAnswerEvaluationService()

    evaluation = evaluator.evaluate(topic, turn, "用了 RAG，效果还可以。", [])
    hint = evaluator.coach_hint(topic, evaluation)
    decision = CoachInterviewPolicy().decide(
        topic=topic,
        turn=turn,
        evaluation=evaluation,
        answered_turns_after_current=[turn.model_copy(update={"answer": "用了 RAG，效果还可以。", "ability_score": evaluation.ability_score})],
        has_next_topic=True,
        coach_hint=hint,
    )

    assert decision.action == "COACH_RETRY"
    assert decision.hint
    assert "guardrail" in decision.hint
    assert "完整可照抄答案" in decision.hint["guardrail"]
    assert decision.next_question == topic.main_question


def test_turn_to_dto_keeps_missing_coach_hint_as_none():
    turn = InterviewTurnEntity(
        id=7,
        session_id=1,
        topic_id=1,
        user_id=1,
        turn_type="MAIN",
        turn_order=1,
        question="请介绍你的 RAG 项目。",
        coach_hint_json=None,
    )

    dto = dynamic_interview_persistence_service.turn_to_dto(turn)

    assert dto.coach_hint is None
    assert dto.signals == {}


def test_dynamic_create_response_can_represent_planning_without_first_turn():
    response = DynamicInterviewCreateResponse(
        session_id="dyn-planning",
        status="PLANNING",
        structured_jd=StructuredJD(),
        current_topic=None,
        current_turn=None,
        plan_summary={
            "generation_stages": [
                {"key": "JD_PARSE", "label": "正在匹配 JD 重点", "status": "ACTIVE"},
            ]
        },
    )

    assert response.status == "PLANNING"
    assert response.current_topic is None
    assert response.current_turn is None


def test_fallback_coach_hint_stays_structural_when_hint_generation_fails():
    topic = DynamicTopicDTO(
        topic_key="project_metric_validation",
        topic_title="项目指标验证",
        skill_key="project",
        question_type="PROJECT",
        evidence_snippet="推荐系统项目提升召回率。",
        main_question="请讲清楚项目指标。",
        topic_order=1,
    )
    evaluation = DynamicAnswerEvaluationService().fallback_evaluation(topic)
    hint = DynamicAnswerEvaluationService().fallback_coach_hint(topic, evaluation)

    assert hint["type"] == "STRUCTURE_HINT"
    assert "完整可照抄答案" in hint["guardrail"]
    assert "结果指标" in hint["structure"]


async def test_rag_insight_returns_no_kb_hit_without_forced_citations():
    service = DynamicRagCoachService()

    async def fake_search(_db, _topic, _user_id):
        return []

    service._search_personal_knowledge = fake_search
    topic = InterviewTopicEntity(
        id=10,
        session_id=1,
        user_id=1,
        topic_key="rag_multi_channel_retrieval",
        topic_title="RAG 多通道检索",
        skill_key="rag",
        question_type="KNOWLEDGE",
        source_type="jd",
        main_question="请解释 RAG 多通道检索。",
        topic_order=1,
    )

    insight = await service.build_topic_insight(None, topic=topic, turns=[], user_id=1)

    assert insight.source_status == "NO_KB_HIT"
    assert insight.citations == []
    assert insight.fallback_reason
    assert "未引用知识库资料" in insight.explanation


async def test_rag_insight_uses_personal_kb_only_when_confidence_is_high():
    service = DynamicRagCoachService()
    citation = DynamicRagCitationDTO(
        knowledge_base_id=3,
        chunk_id=9,
        source_name="RAG 笔记",
        title="多路召回",
        content_preview="RAG 多路召回通常包含 BM25、向量检索和重排序。",
        score=0.62,
    )

    async def fake_search(_db, _topic, _user_id):
        return [citation]

    service._search_personal_knowledge = fake_search
    topic = InterviewTopicEntity(
        id=11,
        session_id=1,
        user_id=1,
        topic_key="rag_multi_channel_retrieval",
        topic_title="RAG 多通道检索",
        skill_key="rag",
        question_type="KNOWLEDGE",
        source_type="jd",
        main_question="请解释 RAG 多通道检索。",
        topic_order=1,
    )

    insight = await service.build_topic_insight(None, topic=topic, turns=[], user_id=1)

    assert insight.source_status == "PERSONAL_KB_HIT"
    assert insight.retrieval_confidence == 0.62
    assert insight.citations == [citation]
    assert "RAG 笔记" in insight.recommended_materials[0]


def test_dynamic_report_summarizes_topics_and_tomorrow_three_tasks():
    session = InterviewSessionEntity(user_id=1, session_id="dyn-1", skill_id="ai-agent")
    project_topic = InterviewTopicEntity(
        id=1,
        session_id=1,
        user_id=1,
        topic_key="rag_multi_channel_retrieval",
        topic_title="RAG 多通道检索",
        skill_key="rag",
        question_type="PROJECT",
        source_type="resume",
        evidence_snippet="智能问答项目使用 RAG。",
        main_question="请讲 RAG 项目。",
        topic_order=1,
    )
    knowledge_topic = InterviewTopicEntity(
        id=2,
        session_id=1,
        user_id=1,
        topic_key="mcp_tool_integration",
        topic_title="MCP 工具集成",
        skill_key="mcp",
        question_type="KNOWLEDGE",
        source_type="jd",
        evidence_snippet="JD 要求 MCP。",
        main_question="请解释 MCP。",
        topic_order=2,
    )
    system_topic = InterviewTopicEntity(
        id=3,
        session_id=1,
        user_id=1,
        topic_key="workflow_orchestration_design",
        topic_title="工作流编排设计",
        skill_key="workflow",
        question_type="SYSTEM_DESIGN",
        source_type="jd",
        evidence_snippet="目标岗位需要 Agent 编排。",
        main_question="请设计 Agent 工作流。",
        topic_order=3,
    )
    turns = [
        _turn(1, 1, "MAIN", 62, ["能说明整体链路"], ["缺少结果指标"], ["简历证据连接不够"]),
        _turn(2, 1, "COACH_RETRY", 78, ["重答后有明显补充"], ["缺少技术取舍"], []),
        _turn(3, 2, "MAIN", 58, [], ["缺少概念定义"], ["回答过短"]),
        _turn(4, 3, "MAIN", 66, ["覆盖了架构模块"], ["缺少成本延迟权衡"], []),
    ]

    report = DynamicInterviewReportService().build_report(
        session,
        [project_topic, knowledge_topic, system_topic],
        turns,
    )

    assert report.type_scores["project"] == 78
    assert report.topic_summaries[0].score_delta == 16
    assert len(report.top_risks) == 3
    assert len(report.tomorrow_tasks) == 3
    assert {task.status for task in report.tomorrow_tasks} == {"TODO"}


def _turn(
    turn_id: int,
    topic_id: int,
    turn_type: str,
    score: int,
    strengths: list[str],
    gaps: list[str],
    risks: list[str],
) -> InterviewTurnEntity:
    return InterviewTurnEntity(
        id=turn_id,
        session_id=1,
        topic_id=topic_id,
        user_id=1,
        turn_type=turn_type,
        turn_order=turn_id,
        question="问题",
        answer="回答",
        ability_score=score,
        signals_json=json.dumps({"strengths": strengths, "gaps": gaps, "risks": risks}, ensure_ascii=False),
        evaluation_json=json.dumps(
            {
                "dimension_scores": {
                    "authenticity": score,
                    "technical_depth": score - 2,
                    "knowledge_accuracy": score - 4,
                    "system_thinking": score - 6,
                    "communication_structure": score - 1,
                }
            },
            ensure_ascii=False,
        ),
    )
