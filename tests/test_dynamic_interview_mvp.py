import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service
from app.modules.interview.dynamic_service import (
    CoachInterviewPolicy,
    DynamicAnswerEvaluationService,
    DynamicInterviewReportService,
    DynamicRagCoachService,
    InterviewPlanService,
    StrictInterviewPolicy,
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
        answered_turns_after_current=[
            turn.model_copy(update={"answer": "用了 RAG，效果还可以。", "ability_score": evaluation.ability_score})
        ],
        has_next_topic=True,
        coach_hint=hint,
    )

    assert decision.action == "COACH_RETRY"
    assert decision.hint
    assert "guardrail" in decision.hint
    assert "完整可照抄答案" in decision.hint["guardrail"]
    assert decision.next_question == topic.main_question


def test_dynamic_create_request_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        DynamicInterviewCreateRequest(mode="STRICTT")


def test_strict_mode_first_answer_returns_followup_without_hint_or_retry():
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
    evaluation = DynamicAnswerEvaluationService().evaluate(topic, turn, "用了 RAG，效果还可以。", [])

    decision = StrictInterviewPolicy().decide(
        topic=topic,
        turn=turn,
        evaluation=evaluation,
        answered_turns_after_current=[
            turn.model_copy(update={"answer": "用了 RAG，效果还可以。", "ability_score": evaluation.ability_score})
        ],
        has_next_topic=True,
        coach_hint={"message": "不应该出现在严厉模式"},
    )

    assert decision.action == "FOLLOW_UP"
    assert decision.hint is None
    assert decision.next_question
    assert "个人负责" in decision.next_question


def test_project_scoring_keeps_concrete_normal_above_generic_vague():
    evaluator = DynamicAnswerEvaluationService()
    cases = [
        (
            DynamicTopicDTO(
                topic_key="redis_cache_penetration_hotkey",
                topic_title="缓存穿透与热点 Key",
                skill_key="redis",
                question_type="PROJECT",
                source_type="resume",
                evidence_snippet=(
                    "参与电商订单系统开发。设计 Redis 缓存策略（Cache-Aside 模式）处理热点商品查询，"
                    "使用互斥锁和随机过期时间保护热点数据，QPS 从 1200 提升到 8000。"
                ),
                main_question="请讲清楚缓存穿透、击穿、雪崩和热点数据保护。",
                topic_order=1,
            ),
            {
                "strong": "热点商品查询采用 Cache-Aside 模式，读的时候先查 Redis，miss 再查 MySQL 并回写缓存。缓存穿透用布隆过滤器，缓存击穿对热点 key 加互斥锁，缓存雪崩给不同 key 设置随机过期时间。QPS 从 1200 提到 8000。",
                "normal": "我们用了 Redis 做缓存。读请求先查 Redis，没有再查 MySQL。对于热点数据用了互斥锁防止击穿。过期时间设了不同的值防止雪崩。",
                "vague": "Redis 做缓存很好用，我们项目里很多地方都用了。缓存可以大幅提升性能，减少数据库压力。主要是把热点数据放在 Redis 里。",
                "off_topic": "缓存应该用 CDN 来做，CloudFront 可以缓存静态资源，配合 Nginx 做反向代理。",
            },
        ),
        (
            DynamicTopicDTO(
                topic_key="react_state_management",
                topic_title="React 状态管理",
                skill_key="react",
                question_type="PROJECT",
                source_type="resume",
                evidence_snippet=(
                    "使用 React 18 + TypeScript + Tailwind CSS 构建组件库，封装 30+ 通用组件。"
                    "使用 useState、useContext、Redux、Zustand 管理组件状态。"
                ),
                main_question="请讲清楚组件库里的 React 状态管理方案。",
                topic_order=1,
            ),
            {
                "strong": "组件库的状态管理分层：组件内状态用 useState/useReducer，跨组件共享用 Context + useMemo 避免不必要的重渲染。复杂业务状态用 Zustand，服务端状态统一用 React Query 管理缓存和重试策略。",
                "normal": "我们项目用 React 的 useState 和 useContext 管理状态。有一些全局状态用了 Redux，但是后来觉得太重了就换成了 Zustand。",
                "vague": "React 状态管理有很多方案，Redux、MobX、Zustand 都可以。我觉得选一个团队熟悉的就行，重要的是保持一致性。",
                "off_topic": "状态管理不应该在前端做，应该全部放到后端。用数据库存储所有状态，前端只是展示层。",
            },
        ),
        (
            DynamicTopicDTO(
                topic_key="async_task_pipeline",
                topic_title="异步任务流水线",
                skill_key="python",
                question_type="PROJECT",
                source_type="resume",
                evidence_snippet=(
                    "实现异步任务队列（Redis Streams + Consumer Group），支持任务重试、超时和幂等。"
                ),
                main_question="请讲清楚 Redis Streams 异步任务队列的设计。",
                topic_order=1,
            ),
            {
                "strong": "基于 Redis Streams 实现异步任务队列。Producer 用 XADD 发送任务，Consumer Group 用 XREADGROUP 消费。每个任务有唯一 message_id 做幂等，超时任务用 XPENDING 检测，超过 5 分钟未 ACK 自动重试。",
                "normal": "用了 Redis Streams 做任务队列。生产者发消息，消费者从 stream 里读。支持任务重试和超时处理。Consumer Group 可以多个实例并行消费。",
                "vague": "异步任务用消息队列就行，Redis 或者 RabbitMQ 都可以。任务放到队列里，worker 从队列里取出来执行。",
                "off_topic": "异步任务应该用多线程，Python 的 ThreadPoolExecutor 就能搞定。不需要引入 Redis 这么重的组件。",
            },
        ),
        (
            DynamicTopicDTO(
                topic_key="lora_qlora_finetuning",
                topic_title="LoRA/QLoRA 微调实践",
                skill_key="llm_finetuning",
                question_type="PROJECT",
                source_type="resume",
                evidence_snippet="使用 LoRA 对 ChatGLM-6B 做指令微调，在 4 张 A100 上训练。",
                main_question="请讲清楚 LoRA 微调实践。",
                topic_order=1,
            ),
            {
                "strong": "用 LoRA 对 ChatGLM-6B 做指令微调。配置 rank=8, alpha=16, target_modules 包含 q_proj 和 v_proj。数据集 5000 条指令-回答对，训练 3 个 epoch。",
                "normal": "用 LoRA 微调了 ChatGLM，在 A100 上训练。加了 adapter 层，只训练少量参数。效果比全量微调差一点但省了很多资源。",
                "vague": "LoRA 就是低秩适配，可以在不训练全部参数的情况下微调大模型。现在很流行，很多公司都在用。",
                "off_topic": "微调太费资源了，不如直接写 Prompt。现在的模型 zero-shot 能力很强，精心设计 prompt 就能达到微调 80% 的效果。",
            },
        ),
    ]

    for topic, answers in cases:
        turn = DynamicTurnDTO(id=1, topic_id=topic.id, turn_type="MAIN", turn_order=1, question=topic.main_question)
        scores = {label: evaluator.evaluate(topic, turn, answer, []).ability_score for label, answer in answers.items()}

        assert scores["strong"] > scores["normal"] > scores["vague"] > scores["off_topic"]
        assert scores["normal"] >= 60
        assert scores["vague"] <= 60


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
