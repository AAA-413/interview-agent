import pytest

from app.modules.knowledge_base.search_channel import SearchContext, VectorSearchChannel


class _FakeResult:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self):
        self.execute_count = 0

    async def execute(self, _stmt):
        self.execute_count += 1
        if self.execute_count == 1:
            return _FakeResult(scalar="测试知识库")
        return _FakeResult(rows=[])


class _FakeVectorService:
    def __init__(self):
        self.queries: list[str] = []

    def embed_text(self, query: str) -> list[float]:
        self.queries.append(query)
        return [0.1, 0.2, 0.3]


class _FakeRagService:
    def __init__(self):
        self.fallback_queries: list[str] = []

    def _search_chunks(self, _chunks, query: str, _top_k: int):
        self.fallback_queries.append(query)
        return []


def test_single_kb_retrieval_engine_is_bound_to_current_db_session(monkeypatch):
    from app.modules.knowledge_base import rag_service as rag_module

    class FakeEngine:
        def __init__(self, channels):
            self.channels = channels

    monkeypatch.setattr(rag_module, "MultiChannelRetrievalEngine", FakeEngine)
    service = object.__new__(rag_module.KnowledgeBaseRagService)
    db_one = object()
    db_two = object()

    engine_one = service._build_retrieval_engine(db_one)
    engine_two = service._build_retrieval_engine(db_two)

    assert engine_one is not engine_two
    assert engine_one.channels[0].db_session is db_one
    assert engine_two.channels[0].db_session is db_two


@pytest.mark.asyncio
async def test_vector_search_uses_rewritten_query_for_embedding_and_fallback():
    rag_service = _FakeRagService()
    vector_service = _FakeVectorService()
    channel = VectorSearchChannel(rag_service, vector_service, _FakeDb())

    await channel.search(
        SearchContext(
            question="它和普通线程有什么区别？",
            rewritten_query="Python asyncio 协程 与 普通线程 区别",
            kb_id=1,
            top_k=4,
        )
    )

    assert vector_service.queries == ["Python asyncio 协程 与 普通线程 区别"]
    assert rag_service.fallback_queries == ["Python asyncio 协程 与 普通线程 区别"]
