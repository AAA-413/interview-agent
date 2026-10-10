"""PR6：Embedding fallback policy（strict fail-closed）契约测试。

被测层是 ``KnowledgeBaseVectorService`` 的**降级策略**。失败点有两类，两类都必须收口：

```text
A. 运行时 provider 调用失败
B. 初始化阶段就不可用（凭证缺失 / SDK 不可用 / 已处于 degraded 状态）
```

```text
strict_config=False → hash fallback（保持旧行为，向后兼容）
strict_config=True  → raise EmbeddingFailedException（fail closed）
                       且 **不** 永久 flip provider、**不** 静默切换 provider
```

为什么 B 类重要（PR #11 review round 1 的 P0-2）：``embed_text()`` 第一段就是
``if not self._use_real_embedding: return self._embed_with_hash(text)``。原实现在
``__init__()`` 里遇到缺凭证 / SDK 不可用会直接把 ``_use_real_embedding`` 置 False，
于是 strict 下也会**悄悄返回 hash 向量**，完全绕过 ``_handle_real_embedding_failure()``。
所以本文件同时覆盖两条路径：前半段用 ``__new__`` 精确构造运行时状态，后半段
（``真实 __init__`` 一节）用真实 ``KnowledgeBaseVectorService()`` 覆盖初始化路径。

全部使用 fake client / fake provider / fake dashscope 模块，不调真实 API。
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
    """构造一个不受 .env 影响的 service 实例（绕过 __init__）。

    注意：``__new__`` 构造**绕过初始化**，因此无法覆盖「初始化阶段就不可用」的路径。
    那部分语义由本文件末尾 ``real init`` 一节用真实 ``__init__()`` 覆盖。
    """
    service = KnowledgeBaseVectorService.__new__(KnowledgeBaseVectorService)
    service._use_real_embedding = True
    service._embedding_provider = provider
    service._zhipu_api_key = zhipu_key
    service._text_embedding = text_embedding
    service._init_failure = None
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


def test_degraded_service_uses_hash_in_non_strict(strict_off):
    """非 strict：已经处于 hash 模式时继续用 hash（保持旧行为）。"""
    service = _service("dashscope", zhipu_key="", text_embedding=None)
    service._use_real_embedding = False
    assert service.embed_text(TEXT) == service._embed_with_hash(TEXT)


def test_degraded_service_is_rejected_in_strict(strict_on):
    """strict：既使服务「早就」降级了，也不允许再返回 hash 向量。"""
    service = _service("dashscope", zhipu_key="", text_embedding=None)
    service._use_real_embedding = False

    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)


def test_no_provider_configured_fails_closed_in_strict(strict_on):
    """strict：完全没有任何真实 provider 时也必须报错，而不是悄悄返回 hash。"""
    service = _service("dashscope", zhipu_key="", text_embedding=None)

    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)


def test_init_failure_is_reported_in_strict(strict_on):
    """strict：初始化阶段记录的原因必须让 embed_text fail closed。"""
    service = _service("zhipu")
    service._init_failure = "AI_ZHIPU_API_KEY 未配置，strict 模式拒绝回退到 DashScope"

    with pytest.raises(EmbeddingFailedException, match="strict 模式下 Embedding 不可用"):
        service.embed_text(TEXT)


# ---------------------------------------------------------------------------
# 真实 __init__：初始化阶段就不可用的路径
# ---------------------------------------------------------------------------
#
# 上面所有用例都用 __new__() 绕过初始化，因此**覆盖不到**真正的漏洞：
# 原实现在 __init__() 里遇到缺凭证 / SDK 不可用时会直接把 _use_real_embedding
# 置为 False，于是 embed_text() 第一段就 return hash —— 完全绕过 strict 的
# fail-closed 收口。这一节全部使用真实 KnowledgeBaseVectorService()。


def _install_fake_dashscope(monkeypatch, *, available: bool = True) -> None:
    """把 dashscope 换成假模块；available=False 时让它 import 直接失败。"""
    import sys
    import types

    if not available:
        # sys.modules[name] = None 会让 `from dashscope import ...` 抛 ImportError
        monkeypatch.setitem(sys.modules, "dashscope", None)
        return

    module = types.ModuleType("dashscope")
    module.TextEmbedding = _FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "dashscope", module)


def _configure_ai(
    monkeypatch,
    *,
    provider: str,
    zhipu_key: str,
    bailian_key: str,
    embedding_key: str = "",
) -> None:
    monkeypatch.setattr(settings.ai, "embedding_provider", provider, raising=False)
    monkeypatch.setattr(settings.ai, "zhipu_api_key", zhipu_key, raising=False)
    monkeypatch.setattr(settings.ai, "bailian_api_key", bailian_key, raising=False)
    monkeypatch.setattr(settings.ai, "embedding_api_key", embedding_key, raising=False)


def test_real_init_strict_zhipu_key_missing_raises_and_never_hashes(strict_on, monkeypatch):
    """strict + zhipu 选中但缺 Key → 初始化即记录不可用，embed_text 抛错，绝不落 hash。"""
    _configure_ai(monkeypatch, provider="zhipu", zhipu_key="", bailian_key="")
    _install_fake_dashscope(monkeypatch, available=True)

    service = KnowledgeBaseVectorService()

    assert service._init_failure is not None, "strict 必须在初始化阶段就记录不可用原因"
    assert service._use_real_embedding is True, "strict 不得把 provider 永久降级"
    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)


def test_real_init_strict_zhipu_key_missing_does_not_silently_switch_to_dashscope(strict_on, monkeypatch):
    """strict 下「选了 zhipu 却缺 Key」不得静默改用用户没有选的 DashScope。"""
    # DashScope 在本次测试里是「可用且配了 key」的 —— 所以一旦静默切换就会被抓到
    _FakeTextEmbedding.calls = 0
    _install_fake_dashscope(monkeypatch, available=True)
    _configure_ai(monkeypatch, provider="zhipu", zhipu_key="", bailian_key="sk-real-looking-key")

    service = KnowledgeBaseVectorService()

    assert service._text_embedding is None, "strict 不允许静默切换到 DashScope"
    assert service._init_failure is not None
    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)
    assert _FakeTextEmbedding.calls == 0


def test_real_init_strict_dashscope_sdk_unavailable_raises(strict_on, monkeypatch):
    """strict + dashscope SDK 不可用 → 抛错，不落 hash。"""
    _configure_ai(monkeypatch, provider="dashscope", zhipu_key="", bailian_key="sk-real-looking-key")
    _install_fake_dashscope(monkeypatch, available=False)

    service = KnowledgeBaseVectorService()

    assert service._init_failure is not None
    assert service._use_real_embedding is True
    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)


def test_real_init_strict_dashscope_key_missing_raises(strict_on, monkeypatch):
    """strict + DashScope Key 未配置 → 抛错，不落 hash。"""
    _configure_ai(monkeypatch, provider="dashscope", zhipu_key="", bailian_key="")
    _install_fake_dashscope(monkeypatch, available=True)

    service = KnowledgeBaseVectorService()

    assert service._init_failure is not None
    with pytest.raises(EmbeddingFailedException):
        service.embed_text(TEXT)


def test_real_init_strict_previously_degraded_service_raises(strict_on, monkeypatch):
    """strict + service 已处于 degraded hash 状态 → 抛错，不返回 hash。"""
    _configure_ai(monkeypatch, provider="dashscope", zhipu_key="", bailian_key="")
    _install_fake_dashscope(monkeypatch, available=True)

    service = KnowledgeBaseVectorService()
    service._use_real_embedding = False  # 模拟「历史上已经降级过」
    service._init_failure = None

    with pytest.raises(EmbeddingFailedException, match="已处于降级状态"):
        service.embed_text(TEXT)


def test_real_init_strict_success_uses_real_provider(strict_on, monkeypatch):
    """strict + DashScope 配置齐备 → 正常走真实 provider。"""
    _FakeTextEmbedding.calls = 0
    _FakeTextEmbedding.mode = "ok"
    _configure_ai(monkeypatch, provider="dashscope", zhipu_key="", bailian_key="sk-real-looking-key")
    _install_fake_dashscope(monkeypatch, available=True)

    service = KnowledgeBaseVectorService()
    vector = service.embed_text(TEXT)

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert _FakeTextEmbedding.calls == 1
    assert service._init_failure is None


def test_real_init_non_strict_missing_config_keeps_legacy_hash(strict_off, monkeypatch):
    """非 strict + 缺失配置 → 保留既有兼容行为：降级 hash，不抛错。"""
    _configure_ai(monkeypatch, provider="dashscope", zhipu_key="", bailian_key="")
    _install_fake_dashscope(monkeypatch, available=True)

    service = KnowledgeBaseVectorService()

    assert service._use_real_embedding is False
    assert service._init_failure is None, "非 strict 不走 _init_failure 收口"
    assert service.embed_text(TEXT) == service._embed_with_hash(TEXT)


def test_real_init_non_strict_zhipu_key_missing_still_falls_back_to_dashscope(strict_off, monkeypatch):
    """非 strict + 选了 zhipu 但缺 Key → 保持旧兼容行为：仍可回退 DashScope。"""
    _FakeTextEmbedding.calls = 0
    _FakeTextEmbedding.mode = "ok"
    _configure_ai(monkeypatch, provider="zhipu", zhipu_key="", bailian_key="sk-real-looking-key")
    _install_fake_dashscope(monkeypatch, available=True)

    service = KnowledgeBaseVectorService()

    assert service._text_embedding is _FakeTextEmbedding
    assert len(service.embed_text(TEXT)) == EMBEDDING_DIMENSIONS
    assert _FakeTextEmbedding.calls == 1


def test_real_init_non_strict_sdk_unavailable_degrades_to_hash(strict_off, monkeypatch):
    """非 strict + SDK 不可用 → 旧行为：降级 hash。"""
    _configure_ai(monkeypatch, provider="dashscope", zhipu_key="", bailian_key="sk-real-looking-key")
    _install_fake_dashscope(monkeypatch, available=False)

    service = KnowledgeBaseVectorService()

    assert service._use_real_embedding is False
    assert service.embed_text(TEXT) == service._embed_with_hash(TEXT)


# ---------------------------------------------------------------------------
# 端到端：strict 下索引任务不得把 hash 向量写进 knowledge_chunks
# ---------------------------------------------------------------------------


class _FakeKbEntity:
    source_text = "Redis MULTI 先把命令入队，EXEC 再统一执行。\n\nMySQL 索引最左前缀原则。"


class _RecordingKbPersistence:
    """记录索引任务实际做了哪些写操作。"""

    def __init__(self):
        self.cleared: list[int] = []
        self.saved_chunks: list[tuple[int, list]] = []
        self.status_updates: list[tuple] = []

    async def find_by_id_or_throw(self, _db, kb_id):
        return _FakeKbEntity()

    async def clear_chunks(self, _db, kb_id):
        self.cleared.append(kb_id)

    async def save_chunks(self, _db, kb_id, chunk_entities):
        self.saved_chunks.append((kb_id, list(chunk_entities)))

    async def update_index_status(self, _db, kb_id, status, error=None):
        self.status_updates.append((kb_id, status, error))


async def _run_index_task(monkeypatch, *, strict: bool):
    """在指定 strict 模式下跑一次知识库索引任务。"""
    monkeypatch.setattr(settings, "strict_config", strict, raising=False)
    _configure_ai(monkeypatch, provider="zhipu", zhipu_key="", bailian_key="")
    _install_fake_dashscope(monkeypatch, available=True)

    service = KnowledgeBaseVectorService()  # 真实 __init__：strict 下 _init_failure 被置位

    from app.modules.knowledge_base import async_tasks as tasks_module

    fake = _RecordingKbPersistence()
    monkeypatch.setattr(tasks_module, "knowledge_base_vector_service", service)
    monkeypatch.setattr(tasks_module, "knowledge_base_persistence_service", fake)

    handler = tasks_module.KnowledgeBaseIndexTaskHandler(session_factory=None)
    return handler, fake, service


async def test_strict_index_task_never_writes_hash_chunks(monkeypatch):
    """strict + 真实 provider 不可用 → 索引任务抛错，且一个 chunk 都没落库。"""
    handler, fake, service = await _run_index_task(monkeypatch, strict=True)

    assert service._init_failure is not None
    with pytest.raises(EmbeddingFailedException):
        await handler.process(db=object(), key_value="7")

    assert fake.cleared == [7], "索引任务确实走到了分块这一步（否则断言是空转的）"
    assert fake.saved_chunks == [], "strict 下绝不允许把 hash 向量写入 knowledge_chunks"
    assert fake.status_updates == [], "也不允许把这次失败顺手标记成别的状态"


async def test_non_strict_index_task_still_writes_hash_chunks(monkeypatch):
    """对照组：非 strict 下确实会写入 hash 向量 —— 证明上面的守卫是它挡住了。"""
    handler, fake, _service = await _run_index_task(monkeypatch, strict=False)

    await handler.process(db=object(), key_value="7")

    assert fake.cleared == [7]
    assert len(fake.saved_chunks) == 1, "非 strict 保持旧行为：允许 hash 向量落库"
    _kb_id, entities = fake.saved_chunks[0]
    assert entities, "应当生成了分块"
    assert all(len(entity.embedding) == EMBEDDING_DIMENSIONS for entity in entities)
