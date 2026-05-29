from app.modules.interview.topic_registry import topic_registry_service


def test_rag_matches_multi_channel_retrieval_topic():
    result = topic_registry_service.normalize(
        raw_topic="RAG 多通道检索",
        evidence_snippet="向量检索 + BM25 多路召回，并使用 Cross-Encoder 重排序。",
        question_type="PROJECT",
        target_role="AI Agent 开发",
    )

    assert result.topic_key == "rag_multi_channel_retrieval"
    assert result.confidence >= 0.8


def test_mcp_matches_tool_integration_topic():
    result = topic_registry_service.normalize(
        raw_topic="MCP 工具服务接入",
        evidence_snippet="通过 MCP Server 暴露工具，并处理参数校验和调用结果。",
        question_type="PROJECT",
        target_role="AI Agent 开发",
    )

    assert result.topic_key == "mcp_tool_integration"
    assert result.fallback_reason is None


def test_java_redis_cache_does_not_match_agent_memory():
    result = topic_registry_service.normalize(
        raw_topic="Java Redis 缓存一致性",
        evidence_snippet="订单服务中使用 Redis 缓存热点商品，需要处理数据库和缓存双写一致性。",
        question_type="KNOWLEDGE",
        target_role="Java 后端开发",
        skill_id="java-backend",
    )

    assert result.topic_key == "redis_cache_consistency"
    assert result.topic_key != "agent_memory_context"


def test_react_state_management_enters_frontend_pack():
    result = topic_registry_service.normalize(
        raw_topic="React 状态管理",
        evidence_snippet="使用 Hooks、Context 和 Zustand 管理复杂页面状态。",
        question_type="KNOWLEDGE",
        target_role="前端开发",
    )

    assert result.topic_key == "react_state_management"
    assert result.pack == "frontend"


def test_low_confidence_topic_uses_fallback():
    result = topic_registry_service.normalize(
        raw_topic="火星土壤建筑材料烘焙",
        evidence_snippet="完全不属于技术开发岗的主题。",
        question_type="KNOWLEDGE",
    )

    assert result.topic_key == "other_knowledge"
    assert result.fallback_reason
