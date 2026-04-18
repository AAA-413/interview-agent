import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.modules.knowledge_base.models import KnowledgeChunkEntity
from app.modules.knowledge_base.vector_service import knowledge_base_vector_service

async def test_pgvector():
    async with async_session_factory() as db:
        # 生成查询向量
        query = "什么是协程？"
        query_embedding = knowledge_base_vector_service.embed_text(query)
        print(f"查询向量维度: {len(query_embedding)}")

        # 使用 pgvector 查询
        stmt = (
            select(KnowledgeChunkEntity)
            .where(KnowledgeChunkEntity.knowledge_base_id == 3)
            .where(KnowledgeChunkEntity.embedding.isnot(None))
            .order_by(KnowledgeChunkEntity.embedding.cosine_distance(query_embedding))
            .limit(5)
        )
        result = await db.execute(stmt)
        chunks = result.scalars().all()

        print(f"\n检索到 {len(chunks)} 个结果:")
        for chunk in chunks:
            print(f"  - ID: {chunk.id}, Title: {chunk.title[:50]}")

if __name__ == "__main__":
    asyncio.run(test_pgvector())
