"""PR6：Embedding fallback policy（strict fail-closed）契约测试。

被测层是 ``KnowledgeBaseVectorService.embed_text`` 的**降级策略**，失败点是 provider 调用：

```text
strict_config=False → 真实 provider 失败 → hash fallback（保持旧行为）
strict_config=True  → 真实 provider 失败 → raise EmbeddingFailedException（fail closed）
                       且 **不** 永久 flip provider
```

为什么这条重要：旧 KB 是用真实 embedding 建的。如果某次 API 抖动后悄悄写 hash 向量，
新 query 与旧 KB 会落在互不兼容的向量空间里，检索静默失效 —— 比直接报错危险得多。

全部使用 fake client / fake provider，不调真实 API。
"""

from __future__ import annotations

import pytest

from app.common.exception import EmbeddingFailedException
from app.config import settings
from app.modules.knowledge_base.vector_service import (
    EMBEDDING_DIMENSIONS,
    KnowledgeBaseVectorService,
)

#: 智谱 embedding-3 原始维度（代码会截断到 EMBEDDING_DIMENSIONS）
ZHIPU_RAW_DIM = 2048
#: DashScope text-embedding-v2 的真实维度（代码不截断，直接落库）
DASHSCOPE_DIM = 1536
TEXT = "Redis MULTI EXEC transaction"


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200, message: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.message = message
        # DashScope 分支是**按属性**读 output（不是 .json()）
        self.output = payload.get("output") if isinstance(payload, dict) else None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeHttpxClient:
    """替身 httpx.Client：可控成功 / 抛错，并记录调用次数。"""

    calls = 0
    mode = "ok"

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def post(self, *_args, **_kwargs):
        type(self).calls += 1
        if type(self).mode == "error":
            raise RuntimeError("connection refused: fake provider down")
        vector = [0.01 * (index % 97) for index in range(ZHIPU_RAW_DIM)]
        return _FakeResponse({"data": [{"embedding": vector}]})


class _FakeTextEmbedding:
    """替身 DashScope TextEmbedding。"""

    calls = 0
    mode = "ok"

    @classmethod
    def call(cls, **_kwargs):
        cls.calls += 1
        if cls.mode == "error":
            return _FakeResponse({}, status_code=500, message="dashscope down")
        vector = [0.02 * (index % 89) for index in range(DASHSCOPE_DIM)]
        return _FakeResponse({"output": {"embeddings": [{"embedding": vector}]}})


def _service(provider: str, *, zhipu_key: str = "z" * 32, text_embedding=None) -> KnowledgeBaseVectorService:
    """构造一个不受 .env 影响的 service 实例。"""
    service = KnowledgeBaseVectorService.__new__(KnowledgeBaseVectorService)
    service._use_real_embedding = True
    service._embedding_provider = provider
    service._zhipu_api_key = zhipu_key
    service._text_embedding = text_embedding
    return service


@pytest.fixture
def strict_off(monkeypatch):
    monkeypatch.setattr(settings, "strict_config", False, raising=False)
    return settings


@pytest.fixture
def strict_on(monkeypatch):
    monkeypatch.setattr(settings, "strict_config", True, raising=False)
    return settings


@pytest.fixture
def fake_zhipu(monkeypatch):
    import app.modules.knowledge_base.vector_service as module

    _FakeHttpxClient.calls = 0
    _FakeHttpxClient.mode = "ok"
    monkeypatch.setattr(module.httpx, "Client", _FakeHttpxClient)
    return _FakeHttpxClient


# ---------------------------------------------------------------------------
# Zhipu
# ---------------------------------------------------------------------------


def test_non_strict_success_uses_real_embedding(strict_off, fake_zhipu):
    service = _service("zhipu")
    vector = service.embed_text(TEXT)

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert fake_zhipu.calls == 1
    assert service._use_real_embedding is True


def test_non_strict_failure_falls_back_to_hash(strict_off, fake_zhipu):
    fake_zhipu.mode = "error"
    service = _service("zhipu")

    vector = service.embed_text(TEXT)

    assert vector == service._embed_with_hash(TEXT)
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert service._use_real_embedding is False, "非 strict 保持旧行为：永久降级 hash"


def test_strict_success_uses_real_embedding(strict_on, fake_zhipu):
    service = _service("zhipu")
    vector = service.embed_text(TEXT)

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert fake_zhipu.calls == 1
    assert service._use_real_embedding is True


def test_strict_failure_raises_and_never_writes_hash(strict_on, fake_zhipu):
    fake_zhipu.mode = "error"
    service = _service("zhipu")

    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)


def test_strict_failure_does_not_permanently_flip_provider(strict_on, fake_zhipu):
    """strict 的语义是 fail closed，不是 fail once then 永久 hash。"""
    fake_zhipu.mode = "error"
    service = _service("zhipu")

    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)

    assert service._use_real_embedding is True, "strict 失败后必须保留下次重试真实 provider 的能力"
    assert fake_zhipu.calls == 1

    # provider 恢复 → 下一次调用直接用真实 embedding（不再经过任何降级状态）
    fake_zhipu.mode = "ok"
    vector = service.embed_text(TEXT)
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert fake_zhipu.calls == 2, "strict 失败后必须仍然尝试真实 provider"


def test_already_degraded_service_does_not_call_provider(strict_off, fake_zhipu):
    """已经是 hash 模式（历史行为）时不再尝试 provider，也不受 strict 影响。"""
    service = _service("zhipu")
    service._use_real_embedding = False

    assert service.embed_text(TEXT) == service._embed_with_hash(TEXT)
    assert fake_zhipu.calls == 0


# ---------------------------------------------------------------------------
# DashScope（第二条 provider 的关键语义）
# ---------------------------------------------------------------------------


def test_dashscope_non_strict_failure_falls_back(strict_off):
    _FakeTextEmbedding.calls = 0
    _FakeTextEmbedding.mode = "error"
    service = _service("dashscope", zhipu_key="", text_embedding=_FakeTextEmbedding)

    vector = service.embed_text(TEXT)

    assert vector == service._embed_with_hash(TEXT)
    assert service._use_real_embedding is False
    assert _FakeTextEmbedding.calls == 1


def test_dashscope_strict_failure_raises(strict_on):
    _FakeTextEmbedding.calls = 0
    _FakeTextEmbedding.mode = "error"
    service = _service("dashscope", zhipu_key="", text_embedding=_FakeTextEmbedding)

    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)
    assert service._use_real_embedding is True

    _FakeTextEmbedding.mode = "ok"
    assert len(service.embed_text(TEXT)) == EMBEDDING_DIMENSIONS
    assert _FakeTextEmbedding.calls == 2


def test_dashscope_strict_success_uses_real_embedding(strict_on):
    _FakeTextEmbedding.calls = 0
    _FakeTextEmbedding.mode = "ok"
    service = _service("dashscope", zhipu_key="", text_embedding=_FakeTextEmbedding)

    vector = service.embed_text(TEXT)

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert service._use_real_embedding is True


def test_no_provider_configured_uses_hash_even_in_strict(strict_off):
    """provider / key 都不满足 → 从未真正启用真实 embedding，strict 也不该凭空报错。"""
    service = _service("dashscope", zhipu_key="", text_embedding=None)
    assert service.embed_text(TEXT) == service._embed_with_hash(TEXT)
