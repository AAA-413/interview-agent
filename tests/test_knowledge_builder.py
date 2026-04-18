"""
测试智能知识库构建 Agent

测试流程：
1. 用户输入："帮我下载 Python 官方文档"
2. Agent 识别意图
3. 规划下载策略
4. 调用 MCP 服务下载
5. 添加到知识库
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_knowledge_builder():
    """测试智能知识库构建"""
    logger.info("\n" + "=" * 80)
    logger.info("测试智能知识库构建 Agent")
    logger.info("=" * 80)

    from app.common.ai.llm_provider import llm_registry
    from app.common.ai.llm_adapter import LLMProviderAdapter
    from app.common.mcp import MCPService
    from app.modules.agent_orchestration.agents.knowledge_builder_agent import (
        KnowledgeBuilderAgent,
    )

    # 初始化 LLM
    langchain_model = llm_registry.default
    llm_provider = LLMProviderAdapter(langchain_model)

    # Mock DocumentFetcher（避免依赖问题）
    class MockDocumentFetcher:
        async def fetch(self, url, max_length=10000):
            logger.info(f"  📥 Mock 抓取: {url}")
            return f"这是从 {url} 抓取的内容（模拟数据）"

    # 初始化 MCP 服务
    document_fetcher = MockDocumentFetcher()
    mcp_service = MCPService(document_fetcher=document_fetcher)

    # Mock KnowledgeService（测试环境）
    class MockKnowledgeService:
        async def create_knowledge_base(self, name, description):
            logger.info(f"  📚 创建知识库: {name}")
            return type("KB", (), {"id": 999, "name": name})()

        async def add_document(self, kb_id, content, metadata):
            logger.info(f"  📄 添加文档到知识库 {kb_id}")
            return {"chunks_count": 10}

    knowledge_service = MockKnowledgeService()

    # 创建 Agent
    agent = KnowledgeBuilderAgent(
        llm_provider=llm_provider,
        mcp_service=mcp_service,
        knowledge_service=knowledge_service,
    )

    # 测试用例
    test_cases = [
        "帮我下载 Python 官方文档",
        "我想学习 FastAPI，帮我找些资料",
        "找一些关于分布式系统的论文",
    ]

    for i, user_input in enumerate(test_cases, 1):
        logger.info(f"\n{'=' * 80}")
        logger.info(f"测试 {i}: {user_input}")
        logger.info("=" * 80)

        try:
            result = await agent.execute(
                user_input=user_input,
                kb_id=None,
            )

            if result.success:
                logger.info(f"\n✅ 成功: {result.message}")
                logger.info(f"  意图类型: {result.data['intent']['intent_type']}")
                logger.info(f"  目标资源: {result.data['intent']['target_resources']}")
                logger.info(f"  下载步骤: {len(result.data['plan']['steps'])} 个")
                logger.info(f"  下载文件: {len(result.data['downloaded_files'])} 个")
                logger.info(
                    f"  知识片段: {result.data['knowledge_base']['chunks_count']} 个"
                )
            else:
                logger.error(f"\n❌ 失败: {result.message}")

        except Exception as e:
            logger.error(f"\n❌ 测试失败: {e}", exc_info=True)


async def main():
    try:
        await test_knowledge_builder()
        logger.info("\n" + "=" * 80)
        logger.info("✅ 测试完成")
        logger.info("=" * 80)
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
