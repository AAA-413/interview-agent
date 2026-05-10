# RAG 检索评估与优化 — 面试技术细节

## 一、为什么要评估

**面试话术**: 我们的 RAG 系统有多种检索策略——纯向量、纯图谱、混合检索、重排序。但上线前不确定哪种策略最优，不同策略在不同场景下的表现差异有多大。所以我设计了一套自动化评估框架来量化对比，用数据驱动决策而不是凭感觉。

**评估框架设计**:

```
生成测试数据集 → 运行评估 → 生成报告
     ↓               ↓            ↓
  从已有chunks     5种策略×2场景   自动生成
  采样+LLM生成     ×变量=26轮     Markdown报告
  74个问题         ~35分钟
```

**测试数据集生成**:
- 从用户已有知识库的 chunks 中均匀采样（过滤 length > 200 的 chunk）
- 调用 LLM 根据 chunk 内容生成自然口语化的问题
- 每个问题关联 ground truth chunk_id，用于后续计算 recall
- 问题类型均匀分布：事实型、关系型、比较型、流程型、概念型

**评估指标**:
- Recall@K：ground truth chunk 是否出现在 top-K 结果中
- MRR：首个相关结果的排名倒数（rank 从 1 开始）
- Hit@1/3/5：top-1/3/5 是否命中
- 平均延迟：检索耗时

**面试加分点**: 不是手动测试几个问题，而是设计了可重复运行的自动化评估 pipeline，有量化数据支撑决策。每次修改检索策略后跑一遍就能看到效果变化。

## 二、首次评估发现的问题

**面试话术**: 首次评估发现图谱检索 recall=0，一开始以为是图谱覆盖率不足，但排查后发现了两个更深层的问题。

### 问题 1：图谱覆盖率不足

**现象**: 15 个知识库中只有 2 个有图谱实体（88 个实体、72 个三元组），其余 13 个 KB 的图谱为空。

**排查过程**:
```python
# 查询各KB的三元组分布
SELECT t.source_kb_id, kb.name, COUNT(*) 
FROM kg_triples t 
LEFT JOIN knowledge_bases kb ON t.source_kb_id = kb.id
GROUP BY t.source_kb_id, kb.name

# 结果：只有 kb_id=43(Agent相关) 和 46(service-startup) 有数据
```

**根因**: 实体提取在索引流程中对每个 KB 都会调用，但 LLM 对大部分内容返回了空数组。Agent 相关内容天然富含实体和关系（AI Agent、工具调用、编排模式），而 asyncio、心理学等内容太抽象，LLM 提取不出实体。

**修复**: 优化提取 prompt：
- 实体类型从 7 种扩展到 9 种（新增「方法」「流程」「问题」）
- 关系类型从 9 种扩展到 12 种（新增「实现」「导致」「依赖」等）
- 放宽规则：从「只提取明确陈述的关系」改为「显而易见的常识性关系也可以提取」
- 增加 2 个完整示例（技术文本 + 心理学文本）

**效果**: 实体从 88 增至 ~1200，三元组从 72 增至 ~925，13 个之前为空的 KB 全部有数据。

### 问题 2：图谱搜索 chunk_id 映射 bug（关键发现）

**现象**: 修复覆盖率后，图谱搜索手动测试能返回结果，但评估系统显示 recall 仍然为 0。

**排查过程**:
```python
# 手动测试图谱搜索
refs, _ = await cross_kb_rag_service.retrieve_with_config(
    db, user_id=1, question='FastAPI 的依赖注入怎么实现？',
    use_vector=False, use_graph=True, top_k=4
)
# 返回 4 个结果，chunk_id 分别是 304, 697, 698, 699

# 验证 chunk_id 是否存在于 knowledge_chunks 表
SELECT id FROM knowledge_chunks WHERE id = 304
# 返回空！chunk_id=304 在 knowledge_chunks 表中不存在

# 检查图谱搜索的 _triples_to_references 方法
chunk_id=triple.id  # ← 这里用了三元组的 ID，不是知识库 chunk 的 ID
```

**根因**: 图谱搜索返回 `triple.id` 作为 `chunk_id`，但评估比较的是 `knowledge_chunks.id`。**两个 ID 空间不同，永远不可能匹配。** 这个 bug 隐蔽在于：图谱搜索功能本身「正常工作」（能返回相关实体关系），但返回的 ID 语义不对。

**修复**: 图谱搜索改为通过实体名在 `knowledge_chunks.content` 中 ILIKE 匹配，返回真实的文本片段：
```python
# 旧代码：直接返回三元组
chunk_id=triple.id  # 三元组ID，不是chunk ID

# 新代码：通过实体名匹配到实际的chunk
stmt = select(KnowledgeChunkEntity).where(
    or_(*[KnowledgeChunkEntity.content.ilike(f"%{name}%") for name in entity_names])
)
# 返回 knowledge_chunks 表中的真实 ID
```

**面试话术**: 这个 bug 很隐蔽——手动测试图谱搜索能返回结果，看起来功能是正常的。但评估系统通过 chunk_id 匹配来计算 recall，发现永远匹配不上。排查后发现是 ID 空间不对。这说明了自动化评估的价值：手动测试发现不了的问题，量化评估能暴露出来。

## 三、修复后的评估结果

**面试话术**: 修复后重新评估，图谱从 0 提升到有效果，但发现了新的问题——跨 KB 场景图谱反而降低了检索效果。

### 核心数据对比

**各策略对比（单 KB / 跨 KB，优化后）:**

| 策略 | 单 KB Recall | 跨 KB Recall | 说明 |
|------|-------------|-------------|------|
| 纯向量 | 0.797 | 0.649 | 基线 |
| 纯图谱 | **0.622** | **0.419** | 从 0.000 大幅提升 |
| 混合(无重排) | **0.878** | **0.662** | 单 KB +10.2%，跨 KB +2.1% |
| 混合+重排 | **0.878** | **0.662** | 分离管道，重排不再降低效果 |

### 为什么跨 KB 反而降了？

**根因**: 图谱搜索用 ILIKE 实体名匹配 chunks，跨 KB 时匹配到不同 KB 中恰好包含同名实体但内容不相关的 chunk。

```
用户问题："asyncio 事件循环怎么工作"（来自 asyncio KB）
图谱找到实体：asyncio, 事件循环
ILIKE 搜索所有 KB 的 chunks → 匹配到：
  ① asyncio KB 的 chunk（讲事件循环原理）✓ 正确
  ② FastAPI KB 的 chunk（提到 "asyncio" 但讲的是路由）✗ 噪声
  ③ Python异步 KB 的 chunk（提到 "事件循环" 但讲的是协程调度）✗ 噪声
```

噪声 chunk 被排到前面，挤掉了正确的 ground truth。单 KB 不受影响，因为候选池只有同一个 KB 的 chunks。

### 关系型问题是图谱的优势场景

| 问题类型 | 纯向量 Recall | 混合+重排 Recall | 变化 |
|---------|-------------|---------------|------|
| relational（关系型） | 0.400 | **0.600** | **+50.0%** |
| factual（事实型） | 0.703 | 0.432 | -38.5% |
| procedural（流程型） | 0.636 | 0.545 | -14.3% |

关系型问题（"A 和 B 有什么区别"）需要跨文档的关系信息，纯向量检索是语义相似度，找不到跨文档关系。图谱通过实体关系链能找到向量检索遗漏的内容。

**面试话术**: 这个发现很有价值——不是简单地说「图谱好」或「图谱差」，而是发现图谱在特定场景（关系型问题、单 KB）下有明显优势，但在跨 KB 场景下因为匹配精度问题反而降低效果。这说明技术选型要结合具体场景。

## 四、提出的优化方案

**面试话术**: 基于评估结果，我提出了 5 个优化方向，按优先级排序。

### 1. 跨 KB 图谱语义过滤（高优先级）✅ 已实现

**问题**: ILIKE 实体名匹配太粗糙，跨 KB 时引入噪声。

**方案**: 实体名粗筛 + embedding 余弦相似度精筛。
```python
# 伪代码
chunks = ilike_search(entity_names)  # 粗筛：包含实体名的chunk
for chunk in chunks:
    similarity = cosine_similarity(query_embedding, chunk.embedding)
    if similarity < 0.5:  # 精筛：语义不相关的过滤掉
        chunks.remove(chunk)
```

**实现**: 在 `_graph_search` 和 `_triples_to_chunk_references` 中，ILIKE 查询后计算每个 chunk 与 query 的余弦相似度，过滤掉 similarity < 0.4 的 chunk。阈值 0.4 为保守起点，通过评估调优。

### 2. 重排序与图谱配合（中优先级）✅ 已实现

**问题**: 图谱匹配的 chunk 语义质量参差不齐，CrossEncoder 重排后反而降低效果。

**方案**: 图谱结果单独排序，不与向量结果混合后统一重排；或先做语义过滤再重排。

**实现**: 采用分离管道方案——向量结果单独通过 CrossEncoder 重排，图谱结果保留自身分数（已含语义过滤），最后合并 dedup 取较高分。CrossEncoder 仅处理语义一致的向量结果，不覆盖图谱的实体匹配分数。

### 3. source_chunk_id 关联（低优先级）

**问题**: 图谱提取在整篇 source_text 上执行，source_chunk_id 全为 NULL，搜索时需要 ILIKE 反查。

**方案**: 提取时按 chunk 分别执行，记录每个三元组来自哪个 chunk，搜索时直接定位。

## 五、技术亮点总结

**「你做过的最有技术深度的事情？」**
→ 设计 RAG 评估框架，通过量化测试发现图谱搜索的 chunk_id 映射 bug 和跨 KB 噪声问题。实施 5 项优化：语义过滤、重排分离管道、source_chunk_id 关联、Prompt 优化、评估脚本缓存。跨 KB hybrid recall 从 0.473 提升到 0.662（+39.8%），超过纯向量基线。

**「你遇到过最难 debug 的问题？」**
→ 图谱搜索手动测试能返回结果，但评估系统显示 recall=0。排查发现图谱返回的 chunk_id 是三元组 ID，不是知识库 chunk 的 ID，两个 ID 空间不同导致永远无法匹配。这个问题隐蔽在于：功能本身是「正常工作」的，只是返回的 ID 语义不对。手动测试发现不了，量化评估才能暴露。

**「你怎么做性能优化？」**
→ 不是凭直觉优化，而是先建立评估基准（26 轮策略对比），用数据定位瓶颈（跨 KB 图谱噪声、重排序与图谱不兼容），再针对性优化。实施语义过滤（ILIKE 粗筛 + embedding 精筛）和重排分离管道（向量单独重排，图谱保留自身分数），每次改完跑一遍评估，量化效果变化。

**「说说你对 RAG 的理解？」**
→ RAG 不只是「向量检索 + LLM 生成」。我们实现了完整的 pipeline：Query Rewrite → 多通道检索（向量 + 图谱）→ CrossEncoder 重排 → LLM 生成。通过评估发现，不同策略在不同场景下效果差异很大——单 KB 向量就够，跨 KB 需要图谱补充关系信息，关系型问题是图谱的优势场景。关键是要有量化评估手段，用数据说话。

## 六、相关代码

| 文件 | 说明 |
|------|------|
| `scripts/rag_eval_dataset_generator.py` | 测试数据集生成（chunks 采样 + LLM 生成问题） |
| `scripts/rag_eval_runner.py` | 全量评估（26 轮策略对比） |
| `scripts/rag_eval_rerun_graph.py` | 选择性重跑图谱策略（复用纯向量结果） |
| `scripts/rag_eval_report.py` | 评估报告生成 |
| `app/modules/knowledge_graph/graph_search_channel.py` | 图谱检索（实体提取 + 两跳查询 + chunk 映射） |
| `app/modules/knowledge_base/cross_kb_rag_service.py` | 跨 KB 混合检索（向量 + 图谱 + 重排） |
| `app/prompts/kg-extraction-system.md` | 图谱实体提取 prompt |
