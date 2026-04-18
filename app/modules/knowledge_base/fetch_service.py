"""
知识库文档抓取服务
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.tools.document_fetcher import document_fetcher
from app.modules.knowledge_base.models import KnowledgeBaseEntity
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.knowledge_base.upload_service import knowledge_base_upload_service
from app.common.model import AsyncTaskStatus

logger = logging.getLogger(__name__)


class KnowledgeBaseFetchService:
    """知识库文档抓取服务"""

    async def fetch_and_create(
        self,
        db: AsyncSession,
        url: str,
        name: str | None = None,
        description: str | None = None,
        max_length: int = 50000,
    ) -> KnowledgeBaseEntity:
        """
        从 URL 抓取文档并创建知识库

        Args:
            db: 数据库会话
            url: 文档 URL
            name: 知识库名称（可选，默认使用文档标题）
            description: 知识库描述（可选）
            max_length: 最大内容长度

        Returns:
            创建的知识库实体
        """
        logger.info(f"开始抓取文档: {url}")

        # 抓取文档
        result = await document_fetcher.fetch(url, raw=False)

        if not result["success"]:
            raise ValueError(f"文档抓取失败: {result['error']}")

        # 使用文档标题作为默认名称
        final_name = name or result["title"] or url
        final_description = description or f"从 {url} 抓取的文档"

        # 创建知识库实体
        entity = KnowledgeBaseEntity(
            name=final_name,
            description=final_description,
            file_hash=url,  # 使用 URL 作为哈希
            original_filename=f"{result['title']}.md" if result["title"] else "document.md",
            file_size=len(result["content"]),
            content_type="text/markdown",
            storage_url=url,  # 保存原始 URL
            source_text=result["content"],
            chunk_count=0,
            document_count=1,
            index_status=AsyncTaskStatus.PENDING,
        )

        # 保存到数据库
        entity = await knowledge_base_persistence_service.save(db, entity)
        await db.commit()

        logger.info(f"文档抓取成功，创建知识库 ID: {entity.id}, 名称: {entity.name}")

        # 异步索引（使用 upload_service 的方法）
        await knowledge_base_upload_service._enqueue_index(entity.id)

        return entity


knowledge_base_fetch_service = KnowledgeBaseFetchService()
