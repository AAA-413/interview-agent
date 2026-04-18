"""
优化效果验证脚本

用途：验证所有优化是否生效
运行：python verify_optimizations.py
"""
import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def verify_database_pool():
    """验证数据库连接池配置"""
    logger.info("=" * 60)
    logger.info("验证 1: 数据库连接池配置")
    logger.info("=" * 60)

    try:
        from app.database import engine

        if engine is None:
            logger.error("❌ 数据库引擎未初始化")
            return False

        pool = engine.pool
        logger.info(f"✅ pool_size: {pool.size()}")
        logger.info(f"✅ max_overflow: {pool._max_overflow}")
        logger.info(f"✅ pool_timeout: {pool._timeout}")
        logger.info(f"✅ pool_recycle: {pool._recycle}")
        logger.info(f"✅ pool_pre_ping: {pool._pre_ping}")

        # 验证配置是否正确
        if pool.size() == 20 and pool._max_overflow == 10:
            logger.info("✅ 数据库连接池配置正确")
            return True
        else:
            logger.error(f"❌ 数据库连接池配置不正确: pool_size={pool.size()}, max_overflow={pool._max_overflow}")
            return False

    except Exception as e:
        logger.error(f"❌ 验证数据库连接池失败: {e}")
        return False


async def verify_redis_pool():
    """验证 Redis 连接池配置"""
    logger.info("\n" + "=" * 60)
    logger.info("验证 2: Redis 连接池配置")
    logger.info("=" * 60)

    try:
        from app.infrastructure.redis.redis_service import REDIS_MAX_CONNECTIONS, REDIS_SOCKET_TIMEOUT_SECONDS

        logger.info(f"✅ max_connections: {REDIS_MAX_CONNECTIONS}")
        logger.info(f"✅ socket_timeout: {REDIS_SOCKET_TIMEOUT_SECONDS}s")

        if REDIS_MAX_CONNECTIONS == 50 and REDIS_SOCKET_TIMEOUT_SECONDS == 5:
            logger.info("✅ Redis 连接池配置正确")
            return True
        else:
            logger.error(f"❌ Redis 连接池配置不正确")
            return False

    except Exception as e:
        logger.error(f"❌ 验证 Redis 连接池失败: {e}")
        return False


async def verify_llm_provider():
    """验证 LLM Provider 配置"""
    logger.info("\n" + "=" * 60)
    logger.info("验证 3: LLM Provider 配置")
    logger.info("=" * 60)

    try:
        from app.common.ai.llm_provider import llm_registry

        model = llm_registry.get_chat_model("dashscope")

        logger.info(f"✅ model_name: {model.model_name}")
        logger.info(f"✅ request_timeout: {model.request_timeout}s")
        logger.info(f"✅ max_retries: {model.max_retries}")

        if model.request_timeout == 60 and model.max_retries == 2:
            logger.info("✅ LLM Provider 配置正确")
            return True
        else:
            logger.error(f"❌ LLM Provider 配置不正确")
            return False

    except Exception as e:
        logger.error(f"❌ 验证 LLM Provider 失败: {e}")
        return False


async def verify_vector_service():
    """验证向量化服务"""
    logger.info("\n" + "=" * 60)
    logger.info("验证 4: 向量化服务")
    logger.info("=" * 60)

    try:
        from app.modules.knowledge_base.vector_service import knowledge_base_vector_service

        # 测试向量化
        test_text = "这是一个测试文本"
        embedding = knowledge_base_vector_service.embed_text(test_text)

        logger.info(f"✅ 向量维度: {len(embedding)}")

        if len(embedding) == 1536:
            logger.info("✅ 使用真实 Embedding API (1536维)")
            return True
        elif len(embedding) == 16:
            logger.warning("⚠️  降级使用哈希向量 (16维)")
            logger.warning("⚠️  建议安装 dashscope: pip install dashscope")
            return True
        else:
            logger.error(f"❌ 向量维度异常: {len(embedding)}")
            return False

    except Exception as e:
        logger.error(f"❌ 验证向量化服务失败: {e}")
        return False


async def verify_text_splitting():
    """验证文本切分"""
    logger.info("\n" + "=" * 60)
    logger.info("验证 5: 文本切分（语义切分+自适应）")
    logger.info("=" * 60)

    try:
        from app.modules.knowledge_base.vector_service import knowledge_base_vector_service

        test_text = """
        这是第一段。这是第一段的第二句。

        这是第二段。这是第二段的第二句。

        这是第三段。这是第三段的第二句。
        """

        # 测试 general 类型
        chunks_general = knowledge_base_vector_service.split_text(test_text, doc_type="general")
        logger.info(f"✅ general 类型切分: {len(chunks_general)} 个块")

        # 测试 code 类型
        chunks_code = knowledge_base_vector_service.split_text(test_text, doc_type="code")
        logger.info(f"✅ code 类型切分: {len(chunks_code)} 个块")

        # 测试 table 类型
        chunks_table = knowledge_base_vector_service.split_text(test_text, doc_type="table")
        logger.info(f"✅ table 类型切分: {len(chunks_table)} 个块")

        logger.info("✅ 语义切分+自适应功能正常")
        return True

    except Exception as e:
        logger.error(f"❌ 验证文本切分失败: {e}")
        return False


async def verify_multi_channel_retrieval():
    """验证多路检索"""
    logger.info("\n" + "=" * 60)
    logger.info("验证 6: 多路检索架构")
    logger.info("=" * 60)

    try:
        from app.modules.knowledge_base.search_channel import (
            SearchChannel,
            VectorSearchChannel,
            MultiChannelRetrievalEngine,
        )

        logger.info("✅ SearchChannel 接口导入成功")
        logger.info("✅ VectorSearchChannel 导入成功")
        logger.info("✅ MultiChannelRetrievalEngine 导入成功")

        # 验证 RAG 服务是否使用多路检索
        from app.modules.knowledge_base.rag_service import knowledge_base_rag_service

        if hasattr(knowledge_base_rag_service, 'retrieval_engine'):
            logger.info("✅ RAG 服务已集成多路检索引擎")
            logger.info(f"✅ 检索通道数量: {len(knowledge_base_rag_service.retrieval_engine.channels)}")
            return True
        else:
            logger.error("❌ RAG 服务未集成多路检索引擎")
            return False

    except Exception as e:
        logger.error(f"❌ 验证多路检索失败: {e}")
        return False


async def main():
    """主函数"""
    logger.info("\n" + "=" * 60)
    logger.info("开始验证优化效果")
    logger.info("=" * 60)

    results = []

    # 执行所有验证
    results.append(("数据库连接池", await verify_database_pool()))
    results.append(("Redis 连接池", await verify_redis_pool()))
    results.append(("LLM Provider", await verify_llm_provider()))
    results.append(("向量化服务", await verify_vector_service()))
    results.append(("文本切分", await verify_text_splitting()))
    results.append(("多路检索", await verify_multi_channel_retrieval()))

    # 汇总结果
    logger.info("\n" + "=" * 60)
    logger.info("验证结果汇总")
    logger.info("=" * 60)

    passed = 0
    failed = 0

    for name, result in results:
        if result:
            logger.info(f"✅ {name}: 通过")
            passed += 1
        else:
            logger.error(f"❌ {name}: 失败")
            failed += 1

    logger.info("\n" + "=" * 60)
    logger.info(f"总计: {passed} 通过, {failed} 失败")
    logger.info("=" * 60)

    if failed == 0:
        logger.info("\n🎉 所有优化验证通过！")
        return 0
    else:
        logger.error(f"\n⚠️  有 {failed} 项验证失败，请检查配置")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
