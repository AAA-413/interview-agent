# 知识库 RAG 问答系统 — 面试技术细节

## 一、整体流程

```
用户问题
  ↓
LLM Query Rewrite（改写查询，1次LLM调用）
  ↓
Embedding 生成向量（Zhipu Embedding-3, 2048维截断到1536维）
  ↓
多通道检索引擎（MultiChannelRetrievalEngine）
  ├─ VectorSearchChannel: pgvector cosine_distance 检索（召回 top_k*2 候选）
  └─ (预留 BM25/关键词通道接口)
  ↓
CrossEncoder 二次重排（BAAI/bge-reranker-base, 本地模型, 不调LLM）
  ↓
LLM 生成回答（带引用标注[1][2] + 推荐追问, 1次LLM调用）
  ↓
SSE 流式返回
```

一次完整问答：**2次LLM调用**（改写+生成）+ **1次本地CrossEncoder推理** + **1次Embedding API调用**

## 二、Query Rewrite（查询改写）

**代码位置**: `app/modules/knowledge_base/rag_service.py:202-223`

**实现逻辑**:
- 调用 LLM，System Prompt 要求"保留核心实体、名词和约束，不要扩展无关内容"
- 支持多轮对话上下文：如果有历史对话，将历史 QA 拼接后让 LLM 结合上下文改写
- 改写失败时静默降级，返回原始问题

**技术细节**:
```python
# 单轮：直接改写
messages = [SystemMessage(content=REWRITE_SYSTEM_PROMPT), HumanMessage(content=question)]

# 多轮：拼接历史后改写
history_text = "\n".join(f"用户: {c['question']}\n助手: {c['answer'][:200]}" for c in chat_history)
messages.append(HumanMessage(content=f"对话历史：\n{history_text}\n\n当前问题：{question}\n\n请结合对话历史改写..."))
```

**面试话术**: 为了提高检索准确率，我引入了 Query Rewrite 环节。用户原始问题可能口语化、省略上下文，直接检索效果不好。通过 LLM 改写为更适合向量检索的简洁查询，同时支持结合多轮对话历史改写，解决指代消解问题。

## 三、向量检索（VectorSearchChannel）

**代码位置**: `app/modules/knowledge_base/search_channel.py:59-169` + `app/modules/knowledge_base/vector_service.py`

**Embedding 方案**（三级降级）:
1. **Zhipu Embedding-3**: 2048维原始向量，截断到1536维匹配 pgvector 列定义
2. **DashScope text-embedding-v2**: 阿里云百炼备选
3. **Hash 向量降级**: SHA-256 哈希生成1536维向量（API不可用时保底）

**检索实现**:
```python
# 优先 pgvector 原生检索
stmt = (
    select(KnowledgeChunkEntity)
    .where(KnowledgeChunkEntity.knowledge_base_id == context.kb_id)
    .where(KnowledgeChunkEntity.embedding.isnot(None))
    .order_by(KnowledgeChunkEntity.embedding.cosine_distance(query_embedding))
    .limit(context.top_k * 2)  # 召回2倍候选用于重排
)

# pgvector 无结果时降级到内存余弦相似度计算
if not chunks_entities:
    all_chunks = ...  # 加载全部chunks
    chunks = rag_service._search_chunks(all_chunks, question, top_k * 2)
```

**文本切分策略**（`vector_service.py:56-83`）:
- 递归语义切分：按 `\n\n → \n → 。→ ！→ ？→ ；` 等分隔符逐级切分
- 默认 chunk_size=900, overlap=120
- 代码块 chunk_size=1200, overlap=150（更大窗口保持代码完整性）
- 表格 chunk_size=600, overlap=50（更小窗口保持表格结构）
- 最终降级：按字符强制切分

## 四、CrossEncoder 二次重排

**代码位置**: `app/modules/knowledge_base/rerank_service.py`

**实现细节**:
- 模型: `BAAI/bge-reranker-base`（~400MB），通过 `sentence-transformers` 的 `CrossEncoder` 加载
- 在线程池中执行推理，避免阻塞 asyncio 事件循环
- 将 (query, chunk_content) 对输入 CrossEncoder，输出相关性分数
- 按分数重排后取 top_k

```python
pairs = [(query, chunk.content_preview or chunk.content) for chunk in chunks]
loop = asyncio.get_event_loop()
scores = await loop.run_in_executor(None, self.model.predict, pairs)
```

**为什么用 CrossEncoder 而不是直接用向量相似度**:
- 向量检索（Bi-Encoder）速度快但精度有限，它把 query 和 document 分别编码，无法捕捉细粒度交互
- CrossEncoder 把 (query, document) 拼接后一起编码，能捕捉 token 级别的交互关系，精度更高
- 缺点是速度慢（O(n) 对每个候选打分），所以只对召回的候选做二次精排

**面试话术**: 向量检索用的是 Bi-Encoder 架构，query 和 document 独立编码，速度快但精度有限。我引入 CrossEncoder 做二阶段重排，它把 query 和候选片段拼接后联合编码，能捕捉更细粒度的语义交互。先用向量检索召回 2 倍候选，再用 CrossEncoder 精排到最终 top_k，在速度和精度之间取得平衡。

## 五、多通道检索架构（预留扩展）

**代码位置**: `app/modules/knowledge_base/search_channel.py`

**架构设计**:
```python
class SearchChannel(ABC):           # 检索通道抽象接口
    def get_name(self) -> str
    def get_priority(self) -> int    # 优先级（数字越小越高）
    def is_enabled(self, context) -> bool
    async def search(self, context) -> SearchChannelResult

class MultiChannelRetrievalEngine:   # 多通道检索引擎
    async def retrieve(self, context):
        # 1. 筛选启用的通道
        # 2. asyncio.gather 并行执行所有通道
        # 3. 合并结果，按 chunk_id 去重（保留最高分）
        # 4. 按分数排序取 top_k
```

**当前状态**: 只注册了 `VectorSearchChannel` 一个通道，但架构上支持随时添加 BM25、关键词匹配等通道。

## 六、SSE 流式输出

**代码位置**: `rag_service.py:122-195`

```python
async def stream_answer(self, ...) -> AsyncIterator[str]:
    yield self._sse_event("meta", {"session_id": ..., "rewritten_query": ...})
    yield self._sse_event("references", {"items": [...]})
    async for token in llm_registry.default.astream([SystemMessage(...), HumanMessage(...)]):
        yield self._sse_event("chunk", {"content": chunk_text})
    yield self._sse_event("done", {"answer": answer})
```

前端通过 `EventSource` 或 `fetch` + `ReadableStream` 接收，实现打字机效果。

## 七、面试常见追问

**Q: 为什么选择 pgvector 而不是 Milvus/Pinecone？**
A: 项目初期数据量不大（知识库级别），pgvector 作为 PostgreSQL 扩展，不需要额外引入向量数据库，降低运维复杂度。cosine_distance 是 pgvector 原生支持的操作符，性能足够。

**Q: 向量维度为什么是1536？**
A: Zhipu Embedding-3 原始输出2048维，但 pgvector 列定义为1536维（参考 OpenAI text-embedding-ada-002 的维度），所以截断匹配。截断损失的信息量很小（前1536维通常包含主要语义信息）。

**Q: Rerank 为什么用本地模型而不是调 LLM？**
A: Rerank 需要对每个候选片段打分，假设有20个候选，调 LLM 就是20次 API 调用，成本和延迟都不可接受。CrossEncoder 本地推理一次 forward pass 就能处理所有对，延迟在百毫秒级。

**Q: 如何处理 Embedding API 不可用的情况？**
A: 三级降级：Zhipu → DashScope → Hash 向量。Hash 向量用 SHA-256 生成确定性向量，虽然语义质量差，但保证系统可用。
