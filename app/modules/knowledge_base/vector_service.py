from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass

from app.modules.knowledge_base.models import KnowledgeChunkEntity

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 16


@dataclass
class ChunkBuildResult:
    chunk_index: int
    content: str
    title: str | None
    metadata: dict
    embedding: list[float]


class KnowledgeBaseVectorService:
    def split_text(self, text: str, *, chunk_size: int = 900, overlap: int = 120) -> list[ChunkBuildResult]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
        chunks: list[ChunkBuildResult] = []
        current = ""
        current_start = 0
        cursor = 0

        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) <= chunk_size:
                if not current:
                    current_start = cursor
                current = candidate
                cursor += len(paragraph) + 2
                continue

            if current:
                chunks.append(self._build_chunk(len(chunks), current, current_start))
                overlap_text = current[-overlap:] if overlap > 0 else ""
                current = f"{overlap_text}\n\n{paragraph}".strip()
                current_start = max(0, cursor - len(overlap_text))
            else:
                slices = self._split_long_paragraph(paragraph, chunk_size, overlap)
                for item, start in slices:
                    chunks.append(self._build_chunk(len(chunks), item, cursor + start))
                current = ""
                current_start = cursor
            cursor += len(paragraph) + 2

        if current.strip():
            chunks.append(self._build_chunk(len(chunks), current, current_start))

        logger.info("知识库文本分块完成: chunks=%d", len(chunks))
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
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = []
        for index in range(EMBEDDING_DIMENSIONS):
            start = index * 2
            segment = digest[start : start + 2]
            number = int.from_bytes(segment, byteorder="big", signed=False)
            values.append((number / 65535.0) * 2 - 1)
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
