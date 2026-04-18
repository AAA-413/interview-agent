import logging
from types import SimpleNamespace

from app.common.model import AsyncTaskStatus
from app.modules.knowledge_base.rag_service import knowledge_base_rag_service
from app.modules.knowledge_base.vector_service import knowledge_base_vector_service

logger = logging.getLogger(__name__)


async def _noop() -> None:
    return None


class FakeChatModel:
    async def ainvoke(self, messages):
        prompt = messages[-1].content
        if "检索查询" in prompt and "参考片段" in prompt:
            return SimpleNamespace(content="这是基于知识库片段整理出的回答。依据片段1和片段2。")
        return SimpleNamespace(content=messages[-1].content)


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
    def __init__(self, kb_id: int, chunks):
        self.id = kb_id
        self.index_status = AsyncTaskStatus.COMPLETED
        self.chunks = chunks


async def run() -> None:
    chunks = [
        FakeChunk(1, 0, "FastAPI 提供 APIRouter、Depends 和 StreamingResponse 等能力。"),
        FakeChunk(2, 1, "Redis Stream 可以用于异步任务排队与 worker 消费。"),
    ]
    kb = FakeKnowledgeBase(1, chunks)
    fake_db = SimpleNamespace(flush=_noop)

    from app.modules.knowledge_base import rag_service as rag_module

    original_registry = rag_module.llm_registry
    original_persistence = rag_module.knowledge_base_persistence_service

    class FakePersistence:
        async def find_by_id_or_throw(self, db, kb_id):
            return kb

        async def create_chat(self, db, **kwargs):
            return SimpleNamespace(id=99)

        async def complete_chat(self, db, **kwargs):
            return None

        async def fail_chat(self, db, **kwargs):
            return None

        async def find_recent_chats(self, db, kb_id):
            return []

        def to_chat_list_item(self, item):
            return item

    rag_module.llm_registry = SimpleNamespace(default=FakeChatModel())
    rag_module.knowledge_base_persistence_service = FakePersistence()
    try:
        result = await knowledge_base_rag_service.ask(db=fake_db, kb_id=1, question="FastAPI 和 Redis Stream 有什么作用？")
        print(result.model_dump())
    finally:
        rag_module.llm_registry = original_registry
        rag_module.knowledge_base_persistence_service = original_persistence


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
