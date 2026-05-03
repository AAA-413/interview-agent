from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass

from app.modules.knowledge_base.models import KnowledgeChunkEntity
from app.config import settings
from app.common.exception import EmbeddingFailedException

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1536  # 阿里云百炼 text-embedding-v2 的维度


@dataclass
class ChunkBuildResult:
    chunk_index: int
    content: str
    title: str | None
    metadata: dict
    embedding: list[float]


class KnowledgeBaseVectorService:
    def __init__(self):
        self._use_real_embedding = True  # 是否使用真实 Embedding
        try:
            from dashscope import TextEmbedding
            self._text_embedding = TextEmbedding
            logger.info("向量化服务初始化: 使用阿里云百炼 Embedding API (text-embedding-v2, 1536维)")
        except ImportError:
            self._text_embedding = None
            self._use_real_embedding = False
            logger.warning("dashscope not installed, fallback to hash vector (16-dim)")

    def split_text(self, text: str, *, chunk_size: int = 900, overlap: int = 120, doc_type: str = "general") -> list[ChunkBuildResult]:
        """
        语义切分文本

        Args:
            text: 原始文本
            chunk_size: 块大小（根据文档类型自适应）
            overlap: 重叠大小
            doc_type: 文档类型 (general/code/table)
        """
        # 根据文档类型自适应调整参数
        if doc_type == "code":
            chunk_size = 1200  # 代码块通常更长
            overlap = 150
        elif doc_type == "table":
            chunk_size = 600   # 表格需要保持完整性
            overlap = 50

        normalized = self._normalize_text(text)
        if not normalized:
            return []

        # 使用语义分隔符进行递归切分
        separators = ["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " ", ""]
        chunks = self._recursive_split(normalized, chunk_size, overlap, separators)

        logger.info("语义切分完成: doc_type=%s, chunk_size=%d, chunks=%d", doc_type, chunk_size, len(chunks))
        return chunks

    def _recursive_split(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
        separators: list[str]
    ) -> list[ChunkBuildResult]:
        """递归语义切分"""
        if not separators:
            # 没有分隔符了，强制按字符切分
            return self._split_by_chars(text, chunk_size, overlap)

        separator = separators[0]
        remaining_separators = separators[1:]

        # 按当前分隔符分割
        if separator:
            splits = text.split(separator)
        else:
            splits = list(text)

        chunks: list[ChunkBuildResult] = []
        current = ""
        current_start = 0
        cursor = 0

        for i, split in enumerate(splits):
            # 重新添加分隔符（除了最后一个）
            if separator and i < len(splits) - 1:
                split = split + separator

            # 如果单个分割就超过 chunk_size，递归使用下一个分隔符
            if len(split) > chunk_size:
                if current:
                    chunks.append(self._build_chunk(len(chunks), current, current_start))
                    current = ""

                # 递归切分
                sub_chunks = self._recursive_split(split, chunk_size, overlap, remaining_separators)
                for sub_chunk in sub_chunks:
                    sub_chunk.chunk_index = len(chunks)
                    chunks.append(sub_chunk)

                cursor += len(split)
                current_start = cursor
                continue

            # 尝试合并到当前块
            candidate = f"{current}{split}" if current else split
            if len(candidate) <= chunk_size:
                if not current:
                    current_start = cursor
                current = candidate
                cursor += len(split)
            else:
                # 当前块已满，保存并开始新块
                if current:
                    chunks.append(self._build_chunk(len(chunks), current, current_start))
                    # 添加重叠
                    overlap_text = current[-overlap:] if overlap > 0 else ""
                    current = f"{overlap_text}{split}".strip()
                    current_start = max(0, cursor - len(overlap_text))
                else:
                    current = split
                    current_start = cursor
                cursor += len(split)

        # 保存最后一个块
        if current.strip():
            chunks.append(self._build_chunk(len(chunks), current, current_start))

        return chunks

    def _split_by_chars(self, text: str, chunk_size: int, overlap: int) -> list[ChunkBuildResult]:
        """按字符强制切分（最后的降级方案）"""
        chunks: list[ChunkBuildResult] = []
        start = 0
        step = max(1, chunk_size - overlap)

        while start < len(text):
            end = min(len(text), start + chunk_size)
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(self._build_chunk(len(chunks), chunk_text, start))
            if end >= len(text):
                break
            start += step

        return chunks

    def to_entities(self, chunks: list[ChunkBuildResult]) -> list[KnowledgeChunkEntity]:
        entities: list[KnowledgeChunkEntity] = []
        for chunk in chunks:
            entities.append(
                KnowledgeChunkEntity(
                    chunk_index=chunk.chunk_index,
                    title=chunk.title,
                    content=chunk.content,
                    content_preview=chunk.content[:180],
                    metadata_json=json.dumps(chunk.metadata, ensure_ascii=False),
                    embedding_json=json.dumps(chunk.embedding, ensure_ascii=False),
                    embedding=chunk.embedding,  # 保存到 pgvector 列
                )
            )
        return entities

    def cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def embed_text(self, text: str) -> list[float]:
        """生成文本向量"""
        if self._use_real_embedding and self._text_embedding:
            try:
                return self._embed_with_api(text)
            except Exception as e:
                logger.warning("Embedding API 调用失败，降级到哈希向量: %s", e)
                # 如果是关键场景（如用户查询），抛出异常；否则降级
                if len(text) < 100:  # 短文本（如查询）不降级
                    raise EmbeddingFailedException(f"文档向量化失败: {str(e)}")
                return self._embed_with_hash(text)
        else:
            return self._embed_with_hash(text)

    def _embed_with_api(self, text: str) -> list[float]:
        """使用阿里云百炼 Embedding API"""
        try:
            response = self._text_embedding.call(
                model='text-embedding-v2',
                input=text,
                api_key=settings.ai.embedding_api_key or settings.ai.bailian_api_key
            )

            if response.status_code == 200:
                embedding = response.output['embeddings'][0]['embedding']
                logger.debug("Embedding API 调用成功: text_length=%d, embedding_dim=%d",
                            len(text), len(embedding))
                return embedding
            else:
                error_msg = f"Embedding API 返回错误: {response.message}"
                logger.error(error_msg)
                raise EmbeddingFailedException(error_msg)
        except Exception as e:
            if isinstance(e, EmbeddingFailedException):
                raise
            logger.error("Embedding API 调用异常: %s", e)
            raise EmbeddingFailedException(f"向量化服务异常: {str(e)}")

    def _embed_with_hash(self, text: str) -> list[float]:
        """降级方案：使用 SHA-256 哈希生成 1536 维向量（与 pgvector 列定义匹配）"""
        values: list[float] = []
        round_index = 0
        while len(values) < EMBEDDING_DIMENSIONS:
            seed = f"{text}:{round_index}".encode("utf-8")
            digest = hashlib.sha256(seed).digest()
            for i in range(0, len(digest) - 1, 2):
                if len(values) >= EMBEDDING_DIMENSIONS:
                    break
                segment = digest[i : i + 2]
                number = int.from_bytes(segment, byteorder="big", signed=False)
                values.append((number / 65535.0) * 2 - 1)
            round_index += 1
        return values

    def _build_chunk(self, chunk_index: int, content: str, start: int) -> ChunkBuildResult:
        normalized = content.strip()
        title = normalized.splitlines()[0][:80] if normalized else None
        metadata = {
            "chunk_index": chunk_index,
            "char_start": start,
            "char_end": start + len(normalized),
            "length": len(normalized),
        }
        return ChunkBuildResult(
            chunk_index=chunk_index,
            content=normalized,
            title=title,
            metadata=metadata,
            embedding=self.embed_text(normalized),
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
        collapsed: list[str] = []
        previous_blank = False
        for line in lines:
            if not line.strip():
                if not previous_blank:
                    collapsed.append("")
                previous_blank = True
                continue
            collapsed.append(line.strip())
            previous_blank = False
        return "\n".join(collapsed).strip()

    def _split_long_paragraph(self, paragraph: str, chunk_size: int, overlap: int) -> list[tuple[str, int]]:
        slices: list[tuple[str, int]] = []
        start = 0
        step = max(1, chunk_size - overlap)
        while start < len(paragraph):
            end = min(len(paragraph), start + chunk_size)
            slices.append((paragraph[start:end].strip(), start))
            if end >= len(paragraph):
                break
            start += step
        return [(text, offset) for text, offset in slices if text]


knowledge_base_vector_service = KnowledgeBaseVectorService()
