"""测试向量检索流程"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.database import async_session_factory
from app.modules.knowledge_base.vector_service import knowledge_base_vector_service
from app.modules.knowledge_base.search_channel import VectorSearchChannel, SearchContext, MultiChannelRetrievalEngine
from app.modules.knowledge_base.rag_service import knowledge_base_rag_service


async def test_vector_search():
    """测试向量检索"""
    async with async_session_factory() as db:
        # 1. 生成查询向量
        question = "什么是异步编程？"
        print(f"\n查询问题: {question}")

        query_embedding = knowledge_base_vector_service.embed_text(question)
        print(f"查询向量维度: {len(query_embedding)}")
        print(f"查询向量前5个值: {query_embedding[:5]}")

        # 2. 创建检索通道
        vector_channel = VectorSearchChannel(
            knowledge_base_rag_service,
            knowledge_base_vector_service,
            db
        )

        # 3. 创建检索上下文
        context = SearchContext(
            question=question,
            kb_id=3,
            top_k=8,  # 召回更多候选
            query_embedding=query_embedding,
            rewritten_query=question
        )

        # 4. 执行检索
        print(f"\n执行向量检索...")
        result = await vector_channel.search(context)

        print(f"\n检索结果:")
        print(f"  通道名称: {result.channel_name}")
        print(f"  结果数量: {len(result.chunks)}")
        print(f"  置信度: {result.confidence}")
        print(f"  耗时: {result.latency_ms}ms")

        if result.chunks:
            print(f"\n前3个结果:")
            for i, chunk in enumerate(result.chunks[:3], 1):
                print(f"\n  [{i}] chunk_id={chunk.chunk_id}, score={chunk.score:.4f}")
                print(f"      title={chunk.title}")
                print(f"      preview={chunk.content_preview[:100]}...")
        else:
            print("\n  ⚠️ 没有检索到任何结果！")

            # 检查数据库中是否有数据
            from app.modules.knowledge_base.models import KnowledgeChunkEntity
            from sqlalchemy import select, func

            stmt = select(func.count()).select_from(KnowledgeChunkEntity).where(
                KnowledgeChunkEntity.knowledge_base_id == 3
            )
            result = await db.execute(stmt)
            total_chunks = result.scalar()
            print(f"\n  数据库中 kb_id=3 的 chunks 总数: {total_chunks}")

            # 检查有多少 chunks 有 embedding
            stmt = select(func.count()).select_from(KnowledgeChunkEntity).where(
                KnowledgeChunkEntity.knowledge_base_id == 3,
                KnowledgeChunkEntity.embedding.isnot(None)
            )
            result = await db.execute(stmt)
            chunks_with_embedding = result.scalar()
            print(f"  有 embedding 的 chunks 数量: {chunks_with_embedding}")


if __name__ == "__main__":
    asyncio.run(test_vector_search())
