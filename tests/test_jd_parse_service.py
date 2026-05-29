from app.modules.interview.jd_parse_service import jd_parse_service


def test_structured_jd_extracts_ai_agent_strategy_inputs():
    jd = """
    AI Agent 开发实习生
    负责 AI Agent 应用开发，建设知识库问答和工具调用链路。
    要求熟悉 Python、FastAPI、RAG、MCP、Prompt，能参与检索效果优化。
    加分项：多 Agent 协作和评估体系经验。
    """

    structured = jd_parse_service.parse(jd, target_role="AI Agent 开发实习生", skill_id="ai-agent")

    assert structured.role_domain == "ai_agent"
    assert structured.seniority == "intern"
    assert "Python" in structured.required_skills
    assert "RAG" in structured.required_skills
    assert "mcp_tool_integration" in structured.topic_weights
    assert "rag_multi_channel_retrieval" in structured.topic_weights
    assert structured.question_type_mix["project"] == 0.5


def test_low_quality_jd_is_downweighted():
    structured = jd_parse_service.parse("招聘 Java 开发，要求熟悉相关技术，有责任心。", target_role=None)

    assert structured.quality_level == "LOW"
    assert structured.quality_score <= 42
    assert structured.missing_parts
    assert all(weight <= 0.55 for weight in structured.topic_weights.values())


def test_jd_only_topic_can_be_used_as_non_project_strategy():
    jd = "后端开发岗位，负责接口和系统设计。要求熟悉 MCP 工具接入和 Agent 任务规划。"

    structured = jd_parse_service.parse(jd, target_role="后端开发")

    assert structured.role_domain == "ai_agent"
    assert structured.topic_weights["mcp_tool_integration"] > 0
    assert structured.topic_weights["agent_planning_execution"] > 0
