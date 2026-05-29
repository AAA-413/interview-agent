# RAG 检索优化 TODO

基于 2026-05-10 第二次评估结果，以下为待优化项。

## 1. 跨 KB 图谱搜索语义过滤（高优先级）✅ 已实现

**问题：** 跨 KB 场景混合检索 recall=0.473，比纯向量 0.649 低 27.1%。图谱通过 ILIKE 实体名匹配 chunks，跨 KB 时匹配到不同 KB 中恰好包含同名实体但内容不相关的 chunk，噪声挤掉正确结果。

**方案：** 图谱匹配到 chunk 后，计算 chunk embedding 与 query embedding 的余弦相似度，过滤掉相似度低于阈值（如 0.5）的 chunk，或按语义相似度重新排序。

**涉及文件：**
- `app/modules/knowledge_base/cross_kb_rag_service.py` — `_graph_search` 方法
- `app/modules/knowledge_graph/graph_search_channel.py` — `_triples_to_chunk_references` 方法

**实现说明（2026-05-10）：**
- `_graph_search` 和 `_triples_to_chunk_references` 新增 `query_embedding` 参数
- `retrieve_with_config` 中无条件计算 `query_embedding`，供图谱语义过滤使用
- ILIKE 查询后，对每个 chunk 计算 `1.0 - cosine_distance(query_embedding, chunk.embedding)`，过滤掉 similarity < 0.4 的 chunk
- 阈值 0.4 为保守起点，通过评估调优

## 2. 重排序与图谱结果的配合（中优先级）✅ 已实现

**问题：** 单 KB 场景 hybrid_no_rerank=0.865，加了重排后反而降到 0.838（-3.1%）。图谱匹配的 chunk 语义质量参差不齐，CrossEncoder 重排后将它们排到不正确的位置。

**方案：**
- 方案 A：图谱结果单独排序，不与向量结果混合后统一重排
- 方案 B：先做语义过滤（TODO 1），再重排
- 方案 C：给图谱结果设置独立的权重上限，防止重排后被推到 top-1

**涉及文件：**
- `app/modules/knowledge_base/cross_kb_rag_service.py` — `retrieve_with_config` 方法

**实现说明（2026-05-10）：**
- 采用分离管道方案：向量结果单独重排，图谱结果保留自身分数
- 新流程：向量检索 → 图谱检索（含语义过滤）→ 仅向量重排 → 合并 dedup → 排序截断
- CrossEncoder 仅处理向量结果，不覆盖图谱分数
- 图谱分数已通过 `weight` 参数限制（默认 0.5），不会压过向量结果

## 3. 图谱提取 source_chunk_id 关联（低优先级）✅ 已实现

**问题：** 图谱实体提取在整篇 `source_text` 上执行，`source_chunk_id` 全为 NULL。搜索时需要通过实体名 ILIKE 反查 chunk，效率低且可能匹配到不相关的 chunk。

**方案：** 提取时记录每个三元组来自哪个 chunk（按 chunk 分别提取），这样图谱搜索可以直接通过 `source_chunk_id` 定位到精确的文本片段。

**涉及文件：**
- `app/modules/knowledge_graph/extraction_service.py` — `extract_and_save` 方法
- `app/modules/knowledge_base/async_tasks.py` — 索引流程中调用提取的逻辑

**实现说明（2026-05-10）：**
- `extract_and_save` 新增 `chunks` 参数，有 chunks 时按 chunk 分别提取，记录 `source_chunk_id`
- 无 chunks 时回退到原有 `_split_text` 逻辑（向后兼容）
- `async_tasks.py` 中将 `chunk_entities` 传给 `extract_and_save`
- `create_triple` 调用时传入 `source_chunk_id=t.get("_source_chunk_id")`

## 4. 实体提取 prompt 持续优化（低优先级）✅ 已实现

**问题：** 仍有部分问题图谱搜索返回空结果（实体提取未提取到有效实体）。

**方案：**
- 增加更多领域的示例（心理学、产品设计等）
- 针对不同 KB 类型使用不同的提取 prompt
- 添加实体同义词表（如 "Python异步" = "asyncio"）

**涉及文件：**
- `app/prompts/kg-extraction-system.md`

**实现说明（2026-05-10）：**
- 新增产品设计示例（用户画像、可用性测试、A/B测试）
- 新增数据科学示例（梯度下降、学习率、Adam优化器）
- 添加同义词归一化指导（"缓存击穿" vs "缓存穿透" 保持独立）
- 添加最低提取规则：无明确关系时也提取独立实体节点（predicate 用 "提及" 或 "相关"）

## 5. 评估脚本优化（低优先级）✅ 已实现

**问题：** 图谱相关策略每个问题需要额外的 LLM 调用（实体提取），22 轮评估耗时约 20 分钟。

**方案：**
- 缓存实体提取结果（同一问题在不同策略/场景下实体相同）
- 并行处理多个问题

**涉及文件：**
- `scripts/rag_eval_rerun_graph.py`
- `scripts/rag_eval_runner.py`

**实现说明（2026-05-10）：**
- `CrossKBRagService._entity_cache` 字典缓存实体提取结果，`_extract_entities` 优先查缓存
- `pre_warm_entity_cache` 在评估开始前一次性提取所有问题的实体
- `evaluate_strategy` 使用 `asyncio.gather` + `Semaphore(5)` 并行评估
- 效果：222 次 LLM 调用 → 74 次，每个策略内 74 个问题并行处理

## 6. 评估报告可信化（高优先级）

**问题：** 当前 RAG 评估报告已经能展示 Recall、MRR、Hit@K 和延迟，但结论部分仍存在人工固定话术，可能与实际指标不一致。例如当重排序指标没有提升时，报告仍可能写出“稳定提升 5-10%”。

**方案：**
- 报告结论全部由 `tests/rag_eval_results.json` 指标计算生成，禁止写死提升幅度。
- 增加质量阈值判断：单 KB、跨 KB、关系型/概念型问题分别给出 PASS/WARN/FAIL。
- 增加回答质量评估，不只评估检索：引用覆盖率、低相关拒答、答案是否超出引用、推荐追问是否相关。
- 在 CI 或质量脚本中支持“只生成报告”和“带阈值失败”两种模式，避免演示报告和工程门禁混在一起。

**涉及文件：**
- `scripts/rag_eval_report.py` — 指标驱动结论和阈值判断
- `scripts/rag_eval_runner.py` — 保留每题检索结果，支持错误案例分析
- `tests/rag_eval_report.md` — 重新生成可信报告
- `docs/02-开发指南/rag-eval-testing.md` — 更新评估口径和报告解读方式
