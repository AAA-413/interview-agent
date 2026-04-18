"""
重排序服务 - 使用 Cross-Encoder 模型对检索结果进行二次精排
"""
import asyncio
import logging
from typing import List

from app.modules.knowledge_base.schemas import RagReferenceDTO

logger = logging.getLogger(__name__)


class RerankService:
    """重排序服务"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        """
        初始化重排序服务

        Args:
            model_name: Cross-Encoder 模型名称
                - BAAI/bge-reranker-large: 性能最好，但模型较大（~1GB）
                - BAAI/bge-reranker-base: 性能良好，模型适中（~400MB）
        """
        self.model_name = model_name
        self.model = None
        self._enabled = False

        try:
            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(model_name, max_length=512)
            self._enabled = True
            logger.info(f"重排序服务初始化成功: model={model_name}")
        except ImportError:
            logger.warning("sentence-transformers 未安装，重排序功能已禁用")
        except Exception as e:
            logger.warning(f"重排序模型加载失败: {e}，重排序功能已禁用")

    @property
    def enabled(self) -> bool:
        """重排序是否启用"""
        return self._enabled

    async def rerank(
        self,
        query: str,
        chunks: List[RagReferenceDTO],
        top_k: int
    ) -> List[RagReferenceDTO]:
        """
        使用 Cross-Encoder 模型重排序

        Args:
            query: 用户查询
            chunks: 候选文档片段
            top_k: 返回前 K 个结果

        Returns:
            重排序后的文档片段（按相关性降序）
        """
        if not self._enabled or not self.model:
            logger.debug("重排序未启用，跳过")
            return chunks[:top_k]

        if not chunks:
            return []

        try:
            # 1. 构造查询-文档对
            pairs = [(query, chunk.content_preview or chunk.content) for chunk in chunks]

            # 2. 计算相关性分数（在线程池中执行，避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            scores = await loop.run_in_executor(None, self.model.predict, pairs)

            # 3. 按分数排序
            scored_chunks = list(zip(chunks, scores))
            scored_chunks.sort(key=lambda x: x[1], reverse=True)

            # 4. 更新分数并返回 Top-K
            reranked = []
            for chunk, score in scored_chunks[:top_k]:
                chunk.score = round(float(score), 4)
                reranked.append(chunk)

            logger.info(
                f"重排序完成: 候选={len(chunks)}, Top-K={top_k}, "
                f"最高分={reranked[0].score if reranked else 0:.4f}"
            )

            return reranked

        except Exception as e:
            logger.error(f"重排序失败: {e}，降级返回原始结果")
            return chunks[:top_k]


# 全局实例（延迟初始化）
_rerank_service: RerankService | None = None


def get_rerank_service() -> RerankService:
    """获取重排序服务实例（单例）"""
    global _rerank_service
    if _rerank_service is None:
        _rerank_service = RerankService()
    return _rerank_service
