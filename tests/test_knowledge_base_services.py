import asyncio
from types import SimpleNamespace

import pytest

from app.common.model import AsyncTaskStatus
from app.modules.knowledge_base.async_tasks import KnowledgeBaseIndexTaskHandler
from app.modules.knowledge_base.rag_service import knowledge_base_rag_service
from app.modules.knowledge_base.vector_service import knowledge_base_vector_service


@pytest.mark.asyncio
async def test_vector_service_split_text_creates_chunks():
    text = "\n\n".join(
        [
            "第一段介绍 FastAPI 的路由与依赖注入。" * 20,
            "第二段介绍 Redis Stream 在异步队列中的作用。" * 20,
            "第三段介绍如何结合 worker 处理后台任务。" * 20,
        ]
    )

    chunks = knowledge_base_vector_service.split_text(text, chunk_size=180, overlap=20)

    assert len(chunks) >= 3
    assert chunks[0].chunk_index == 0
    assert chunks[0].metadata["char_start"] == 0
    assert all(chunk.embedding for chunk in chunks)


@pytest.mark.asyncio
async def test_rag_service_returns_ranked_references():
    class FakeChunk:
        def __init__(self, chunk_id: int, chunk_index: int, content: str):
            self.id = chunk_id
            self.chunk_index = chunk_index
            self.title = f"chunk-{chunk_index}"
            self.content = content
            self.content_preview = content[:80]
            self.metadata_json = '{"source":"test"}'
            self.embedding_json = str(knowledge_base_vector_service.embed_text(content)).replace("'", '"')

    class FakeKnowledgeBase:
        def __init__(self, chunks):
            self.index_status = AsyncTaskStatus.COMPLETED
            self.chunks = chunks

    class FakeChatModel:
        async def ainvoke(self, messages):
            prompt = messages[-1].content
            if "参考片段" in prompt:
                return SimpleNamespace(content="基于片段1和片段2的回答")
            return SimpleNamespace(content=messages[-1].content)

    class FakePersistence:
        async def find_by_id_or_throw(self, db, kb_id):
            return FakeKnowledgeBase(
                [
                    FakeChunk(1, 0, "FastAPI 提供 APIRouter 与 Depends。"),
                    FakeChunk(2, 1, "Redis Stream 支持异步任务消费。"),
                ]
            )

        async def create_chat(self, db, **kwargs):
            return SimpleNamespace(id=123)

        async def complete_chat(self, db, **kwargs):
            return None

        async def fail_chat(self, db, **kwargs):
            return None

    from app.modules.knowledge_base import rag_service as rag_module

    original_registry = rag_module.llm_registry
    original_persistence = rag_module.knowledge_base_persistence_service
    rag_module.llm_registry = SimpleNamespace(default=FakeChatModel())
    rag_module.knowledge_base_persistence_service = FakePersistence()

    async def _flush():
        return None

    try:
        result = await knowledge_base_rag_service.ask(
            db=SimpleNamespace(flush=_flush),
            kb_id=1,
            question="FastAPI 和 Redis Stream 分别做什么？",
            session_id="test-session",
        )
    finally:
        rag_module.llm_registry = original_registry
        rag_module.knowledge_base_persistence_service = original_persistence

    assert result.session_id == "test-session"
    assert result.references
    assert result.references[0].chunk_id in {1, 2}
    assert "回答" in result.answer


@pytest.mark.asyncio
async def test_index_task_handler_marks_failed_when_source_text_empty():
    updates = []

    class FakePersistence:
        async def find_by_id_or_throw(self, db, kb_id):
            return SimpleNamespace(id=kb_id, source_text="")

        async def update_index_status(self, db, kb_id, status, error=None):
            updates.append((kb_id, status, error))

    class FakeSession:
        def __init__(self):
            self.committed = False
            self.rolled_back = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def commit(self):
            self.committed = True

        async def rollback(self):
            self.rolled_back = True

    def fake_session_factory():
        return FakeSession()

    from app.modules.knowledge_base import async_tasks as async_module

    original_persistence = async_module.knowledge_base_persistence_service
    async_module.knowledge_base_persistence_service = FakePersistence()
    try:
        handler = KnowledgeBaseIndexTaskHandler(fake_session_factory)
        await handler.handle({"knowledgeBaseId": "42"})
    finally:
        async_module.knowledge_base_persistence_service = original_persistence

    assert updates == [(42, AsyncTaskStatus.FAILED, "知识库文本为空，无法建立索引")]


def test_async_knowledge_base_suite():
    asyncio.run(test_vector_service_split_text_creates_chunks())
    asyncio.run(test_rag_service_returns_ranked_references())
    asyncio.run(test_index_task_handler_marks_failed_when_source_text_empty())
