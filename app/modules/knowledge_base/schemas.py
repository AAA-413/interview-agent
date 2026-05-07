from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.common.model import AsyncTaskStatus
from app.modules.knowledge_base.models import RagChatStatus


class KnowledgeBaseCreateResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    filename: str
    file_size: int | None = None
    content_type: str | None = None
    storage_url: str | None = None
    source_text: str | None = None
    chunk_count: int = 0
    document_count: int = 1
    index_status: AsyncTaskStatus = AsyncTaskStatus.PENDING
    index_error: str | None = None
    last_indexed_at: datetime | None = None
    created_at: datetime


class KnowledgeBaseListItemDTO(BaseModel):
    id: int
    name: str
    description: str | None = None
    filename: str
    file_size: int | None = None
    chunk_count: int = 0
    document_count: int = 1
    index_status: AsyncTaskStatus = AsyncTaskStatus.PENDING
    index_error: str | None = None
    last_indexed_at: datetime | None = None
    created_at: datetime


class KnowledgeChunkDTO(BaseModel):
    id: int
    chunk_index: int
    title: str | None = None
    content: str
    content_preview: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagReferenceDTO(BaseModel):
    chunk_id: int
    chunk_index: int
    title: str | None = None
    content: str = ""
    content_preview: str = ""
    score: float
    source_name: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagChatDTO(BaseModel):
    id: int
    session_id: str
    question: str
    rewritten_query: str | None = None
    answer: str | None = None
    references: list[RagReferenceDTO] = Field(default_factory=list)
    status: RagChatStatus = RagChatStatus.PENDING
    error_message: str | None = None
    created_at: datetime


class KnowledgeBaseDetailDTO(BaseModel):
    id: int
    name: str
    description: str | None = None
    filename: str
    file_size: int | None = None
    content_type: str | None = None
    storage_url: str | None = None
    source_text: str | None = None
    chunk_count: int = 0
    document_count: int = 1
    index_status: AsyncTaskStatus = AsyncTaskStatus.PENDING
    index_error: str | None = None
    last_indexed_at: datetime | None = None
    created_at: datetime
    chunks: list[KnowledgeChunkDTO] = Field(default_factory=list)
    recent_chats: list[RagChatDTO] = Field(default_factory=list)


class CreateKnowledgeBaseRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class FetchDocumentRequest(BaseModel):
    url: HttpUrl
    name: str | None = None
    description: str | None = None
    max_length: int = Field(default=50000, ge=1000, le=100000)


class AskKnowledgeBaseRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    top_k: int = Field(default=4, ge=1, le=20)


class RagAnswerDTO(BaseModel):
    session_id: str
    rewritten_query: str
    answer: str
    references: list[RagReferenceDTO] = Field(default_factory=list)


class RagChatListItemDTO(BaseModel):
    id: int
    session_id: str
    question: str
    status: RagChatStatus
    created_at: datetime


class KnowledgeBaseReindexResponse(BaseModel):
    id: int
    index_status: AsyncTaskStatus
    index_error: str | None = None
