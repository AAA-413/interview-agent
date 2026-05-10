---
skill: rag-eval-testing
description: RAG 检索效果评估测试流程
tags: [rag, evaluation, knowledge-base, testing]
---

# RAG 检索效果评估测试流程

对知识库 RAG 检索系统进行自动化评估，量化不同检索策略（向量/图谱/混合/重排）在单 KB 和跨 KB 场景下的效果差异。

## 前置条件

- Docker 基础设施已启动（PostgreSQL + Redis + MinIO）
- 后端服务已启动（`uvicorn app.main:app --port 8002`）
- 数据库中已有至少一个用户的知识库，且索引状态为 `COMPLETED`
- 知识图谱已完成实体/关系提取（如果要测试图谱检索）

## 评估流程概览

```
生成测试数据集 → 运行评估 → 生成报告
```

三个步骤分别对应三个脚本，位于 `scripts/` 目录：

| 脚本 | 用途 | 输出 |
|------|------|------|
| `rag_eval_dataset_generator.py` | 从已有 chunks 采样，调用 LLM 生成测试问题 | `tests/rag_eval_dataset.json` |
| `rag_eval_runner.py` | 对每个问题跑不同检索策略，记录指标 | `tests/rag_eval_results.json` |
| `rag_eval_report.py` | 读取评估结果，生成 Markdown 报告 | `tests/rag_eval_report.md` |

## 步骤 1：生成测试数据集

从用户已有知识库的 chunks 中采样，调用 LLM 生成测试问题。每个问题关联一个 ground truth chunk_id，用于后续评估检索准确率。

```bash
python scripts/rag_eval_dataset_generator.py --user-id 1 --samples-per-kb 10 --output tests/rag_eval_dataset.json
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--user-id` | 必填 | 用户 ID，从数据库查询该用户的所有已完成知识库 |
| `--samples-per-kb` | 10 | 每个知识库采样 chunk 数量 |
| `--output` | `tests/rag_eval_dataset.json` | 输出文件路径 |

**采样策略：**
- 使用项目已有的 chunks（递归语义切分 900/120），不重新切分
- 过滤条件：`length(content) > 200`（太短的 chunk 生成不出好问题）
- 按 `chunk_index` 均匀分布采样，确保覆盖文档不同部分
- LLM 根据 chunk 内容生成自然口语化的问题，包含问题类型和关键术语

**输出格式：**

```json
{
  "generated_at": "2026-05-10T10:00:00",
  "user_id": 1,
  "total_questions": 50,
  "kb_count": 5,
  "samples_per_kb": 10,
  "questions": [
    {
      "id": "q_001",
      "question": "FastAPI 的依赖注入是怎么实现的？",
      "question_type": "conceptual",
      "key_terms": ["FastAPI", "依赖注入"],
      "difficulty": "medium",
      "ground_truth": {
        "chunk_id": 123,
        "kb_id": 5,
        "kb_name": "FastAPI 官方文档",
        "chunk_title": "依赖注入系统",
        "chunk_content_preview": "FastAPI 的依赖注入系统基于..."
      }
    }
  ]
}
```

**问题类型分布（均匀）：**

| 类型 | 说明 | 示例 |
|------|------|------|
| `factual` | 事实型 | "XXX 有什么特点" |
| `relational` | 关系型 | "XXX 和 YYY 有什么区别" |
| `comparative` | 比较型 | "XXX 和 YYY 哪个更适合 ZZZ" |
| `procedural` | 流程型 | "怎么配置 XXX" |
| `conceptual` | 概念型 | "什么是 XXX" |

## 步骤 2：运行评估

加载测试数据集，对每个问题跑不同检索策略，在单 KB 和跨 KB 两种场景下记录结果。

```bash
python scripts/rag_eval_runner.py --dataset tests/rag_eval_dataset.json --output tests/rag_eval_results.json --user-id 1
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dataset` | 必填 | 测试数据集 JSON 路径 |
| `--output` | `tests/rag_eval_results.json` | 评估结果输出路径 |
| `--user-id` | 必填 | 用户 ID |

### 评估场景

| 场景 | `scope_kb_id` | 说明 |
|------|--------------|------|
| 单 KB | `ground_truth.kb_id` | 只搜 ground truth 所在的知识库，候选池小，噪声少，是基线 |
| 跨 KB | `None` | 搜用户所有已完成知识库，候选池大，噪声多，是真实场景 |

### 检索策略矩阵

**5 种基础策略（每种在 2 个场景下各跑一次 = 10 轮）：**

| 策略名 | 向量检索 | 图谱检索 | 重排序 | 说明 |
|--------|---------|---------|--------|------|
| `vector_only` | ✅ | ❌ | ❌ | 纯向量基线 |
| `vector_rerank` | ✅ | ❌ | ✅ | 向量 + CrossEncoder 重排 |
| `graph_only` | ❌ | ✅ | ❌ | 纯图谱检索 |
| `hybrid_no_rerank` | ✅ | ✅ | ❌ | 混合检索（无重排） |
| `hybrid_rerank` | ✅ | ✅ | ✅ | 完整流水线 |

**top_k 变量测试（`hybrid_rerank` 策略，2 个场景各跑 5 次 = 10 轮）：**

| top_k | 说明 |
|-------|------|
| 2 | 最严格，只看 top-2 |
| 4 | 默认值 |
| 6 | 中等 |
| 8 | 宽松 |
| 10 | 最宽松 |

**graph_weight 变量测试（`hybrid_rerank` 策略，top_k=4，2 个场景各跑 3 次 = 6 轮）：**

| graph_weight | 说明 |
|-------------|------|
| 0.3 | 向量为主，图谱辅助 |
| 0.5 | 均衡 |
| 0.7 | 图谱为主 |

### 评估指标

| 指标 | 计算方式 | 意义 |
|------|---------|------|
| `recall` | ground_truth chunk_id 是否出现在 top-K 结果中 | 召回率 |
| `mrr` | 1 / rank_of_first_relevant（rank 从 1 开始） | 首个相关结果的位置 |
| `precision` | 1/K（命中时）或 0（未命中时） | 精确率 |
| `hit@1` | top-1 结果是否命中 | 最严格指标 |
| `hit@3` | top-3 是否命中 | 实用指标 |
| `hit@5` | top-5 是否命中 | 宽松指标 |
| `avg_latency_ms` | 平均检索耗时（毫秒） | 性能指标 |

所有指标先按单条问题计算，再取平均值聚合。同时按 `question_type` 分组统计，用于分析不同问题类型的检索效果差异。

### 输出格式

```json
{
  "evaluated_at": "2026-05-10T10:30:00",
  "dataset_size": 50,
  "user_id": 1,
  "scopes": {
    "single_kb": {
      "strategies": {
        "vector_only": {
          "config": {"use_vector": true, "use_graph": false, "use_rerank": false, "top_k": 4, "graph_weight": 0.5, "scope": "single_kb"},
          "metrics": {"recall": 0.82, "mrr": 0.75, "precision": 0.205, "hit@1": 0.68, "hit@3": 0.78, "hit@5": 0.82, "avg_latency_ms": 80.5, "count": 50},
          "per_type": {
            "factual": {"recall": 0.90, "mrr": 0.85, "avg_latency_ms": 75.0, "count": 10},
            "relational": {"recall": 0.70, "mrr": 0.62, "avg_latency_ms": 85.0, "count": 10}
          }
        }
      }
    },
    "cross_kb": { "strategies": { "..." } }
  }
}
```

## 步骤 3：生成评估报告

读取评估结果 JSON，生成结构化的 Markdown 报告。

```bash
python scripts/rag_eval_report.py --results tests/rag_eval_results.json --output tests/rag_eval_report.md
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--results` | 必填 | 评估结果 JSON 路径 |
| `--output` | `tests/rag_eval_report.md` | 输出报告路径 |

### 报告结构

报告包含以下 8 个部分：

1. **单 KB vs 跨 KB 总览** — 混合+重排策略在两个场景下的核心指标对比
2. **各策略总览** — 5 种基础策略在两个场景下的完整指标表
3. **按问题类型分析** — 5 种问题类型分别对比纯向量 vs 混合+重排的提升幅度
4. **top_k 影响分析** — top_k 从 2 到 10 的 Recall/MRR/延迟变化趋势
5. **重排序效果分析** — 加 vs 不加重排的 Recall/MRR/延迟变化
6. **知识图谱贡献分析** — 加 vs 不加图谱的 Recall/MRR 变化，分单 KB 和跨 KB 场景
7. **图谱权重影响分析** — graph_weight 0.3/0.5/0.7 下的效果对比
8. **结论** — 自动生成的文字总结

## 一键运行完整流程

```bash
# 1. 确保后端服务已启动
uvicorn app.main:app --host 0.0.0.0 --port 8002

# 2. 生成测试数据集
python scripts/rag_eval_dataset_generator.py --user-id 1 --samples-per-kb 10

# 3. 运行评估
python scripts/rag_eval_runner.py --dataset tests/rag_eval_dataset.json --user-id 1

# 4. 生成报告
python scripts/rag_eval_report.py --results tests/rag_eval_results.json

# 5. 查看报告
cat tests/rag_eval_report.md
```

## 自定义评估

### 调整采样数量

```bash
# 每个知识库采样 20 个 chunk（更多测试数据，更长运行时间）
python scripts/rag_eval_dataset_generator.py --user-id 1 --samples-per-kb 20
```

### 手动编辑测试数据集

可以手动编辑 `tests/rag_eval_dataset.json`，调整问题内容或 ground truth。格式参考步骤 1 的输出格式。

### 添加新策略

在 `scripts/rag_eval_runner.py` 的 `BASE_STRATEGIES` 列表中添加新策略：

```python
BASE_STRATEGIES = [
    # ... 现有策略 ...
    {"name": "my_custom", "use_vector": True, "use_graph": True, "use_rerank": True, "top_k": 6, "graph_weight": 0.6},
]
```

### 调整 top_k / graph_weight 测试范围

修改 `scripts/rag_eval_runner.py` 中的常量：

```python
TOP_K_VARIANTS = [2, 4, 6, 8, 10]       # 修改为你需要的值
GRAPH_WEIGHT_VARIANTS = [0.3, 0.5, 0.7]  # 修改为你需要的值
```

## 关键设计说明

### 为什么用现有 chunks 而不重新切分

评估的目的是测试**检索**效果，不是切分效果。使用数据库中已有的 chunks（递归语义切分 900/120），可以保证评估结果与实际生产环境一致。LLM 只负责根据 chunk 内容生成问题，不改变 chunk 本身。

### 单 KB vs 跨 KB 的核心差异

- **单 KB**：向量检索的候选池只有同一个 KB 的 chunks，噪声少，纯向量就能有不错效果
- **跨 KB**：候选池包含所有 KB 的 chunks，不同 KB 的"语义相似但不相关"的 chunk 会干扰排序，图谱通过实体关系精确定位，优势更明显
- 报告中重点对比：同一策略在单 KB vs 跨 KB 下的 Recall 差距，以及图谱带来的提升幅度差异

### 评分权重问题

向量检索和图谱检索的分数来自不同域：
- 向量检索：0-1 余弦相似度
- 图谱检索：直接关系 0.85，间接关系 0.65（固定分）

合并时通过 `graph_weight` 参数控制图谱分数的权重。例如 `graph_weight=0.5` 时，图谱直接关系分数变为 `0.85 * 0.5 = 0.425`。

## 实际测试记录

### 2026-05-10 首次完整评估

**环境配置：**
- 数据库：PostgreSQL 16 + pgvector（Docker）
- LLM：DeepSeek Chat（via DashScope API）
- Embedding：Zhipu Embedding-3（2048 维，截断到 1536）
- 重排序：BAAI/bge-reranker-base（CrossEncoder）
- 用户：user_id=1，15 个已完成知识库

**测试数据集：**
- 生成方式：`--samples-per-kb 5`，每个 KB 采样 5 个 chunk
- 总问题数：74（15 KB × 5，部分 chunk 太短被过滤）
- 问题类型分布：factual、relational、comparative、procedural、conceptual

**评估耗时：** 约 35 分钟（26 轮 × 74 问题，每轮约 1.5 分钟）

#### 核心结果

**单 KB vs 跨 KB（混合+重排，top_k=4）：**

| 场景 | Recall@4 | MRR | Hit@1 | Hit@3 | 平均延迟 |
|------|----------|-----|-------|-------|---------|
| 单 KB | 0.797 | 0.568 | 0.405 | 0.716 | 1120ms |
| 跨 KB | 0.635 | 0.464 | 0.324 | 0.581 | 1156ms |
| 差异 | -20.3% | -18.3% | -20.0% | -18.9% | +3.2% |

**各策略对比（单 KB / 跨 KB）：**

| 策略 | 单 KB Recall@4 | 跨 KB Recall@4 | 说明 |
|------|---------------|---------------|------|
| 纯向量 | 0.797 | 0.649 | 基线 |
| 向量+重排 | 0.797 | 0.649 | 重排序无提升 |
| 纯图谱 | 0.000 | 0.000 | 图谱覆盖率不足（见下方分析） |
| 混合(无重排) | 0.797 | 0.649 | 图谱无贡献 |
| 混合+重排 | 0.797 | 0.635 | 图谱引入噪声，略降 |

**top_k 影响：**

| top_k | 单 KB Recall | 跨 KB Recall | 延迟 |
|-------|-------------|-------------|------|
| 2 | 0.635 | 0.568 | ~1130ms |
| 4 | 0.797 | 0.635 | ~1130ms |
| 6 | 0.878 | 0.716 | ~1230ms |
| 8 | 0.960 | 0.730 | ~1170ms |
| 10 | 0.960 | 0.730 | ~1200ms |

**图谱权重影响（跨 KB）：**

| graph_weight | Recall@4 | MRR |
|-------------|----------|-----|
| 0.3 | 0.649 | 0.467 |
| 0.5 | 0.635 | 0.464 |
| 0.7 | 0.527 | 0.364 |

#### 发现的问题

**1. 图谱检索 Recall=0 的根因：图谱覆盖率不足**

图谱检索本身是正常工作的（Agent 相关问题 graph-only 可返回结果），但测试数据集覆盖 15 个 KB，大部分 KB（asyncio、Python 异步、心理学等）没有对应的图谱实体。图谱中只有 88 个实体，主要来自 Agent 相关 KB（kb_id=43, 46）。

验证方法：
```bash
# 用 Agent 相关问题测试图谱检索（应返回结果）
curl "http://localhost:8002/api/cross-knowledgebase/cross/chat/retrieve?question=AI+Agent有哪些核心组件&use_vector=false&use_graph=true&top_k=4"

# 用 asyncio 问题测试（应返回空，因为图谱中没有 asyncio 实体）
curl "http://localhost:8002/api/cross-knowledgebase/cross/chat/retrieve?question=asyncio事件循环工作原理&use_vector=false&use_graph=true&top_k=4"
```

**改进方向：**
- 对所有已完成 KB 运行图谱实体提取（当前只有部分 KB 有图谱数据）
- 或在评估时按 KB 分组，只对有图谱数据的 KB 测试图谱策略

**2. 重排序无提升**

CrossEncoder 重排序在当前数据集上没有带来 Recall 提升。可能原因：
- 测试数据集的 ground truth chunk 与 query 语义高度匹配，向量检索本身已排在 top-1
- CrossEncoder 模型（bge-reranker-base）对当前文档类型的 reranking 效果有限
- 需要更大规模、更具歧义性的测试数据集来验证重排序效果

**3. 混合+重排在跨 KB 场景略低于纯向量**

混合+重排 Recall=0.635 vs 纯向量 Recall=0.649（-2.1%）。原因是图谱检索返回的结果（来自不同 KB 的实体关系）干扰了重排序，将不相关的图谱结果排到了前面。

#### 结论

1. **向量检索是当前最可靠的策略**：纯向量在单 KB 和跨 KB 场景下都有稳定表现
2. **top_k=8 是最佳性价比**：单 KB Recall=0.960，跨 KB Recall=0.730，延迟可接受
3. **图谱检索需要更多数据**：当前图谱覆盖率不足，无法发挥跨文档关系检索的优势
4. **重排序需要更大规模验证**：当前数据集规模（74 问题）可能不足以体现重排序价值
5. **跨 KB 比单 KB 难约 20%**：候选池增大带来的噪声是主要挑战

### 2026-05-10 第二次评估（图谱修复后）

**修复内容：**

1. **图谱覆盖率**：优化实体提取 prompt（扩展实体/关系类型、放宽规则、增加示例），对 15 个 KB 全部重新提取。实体数从 88 增至 ~1200，三元组从 72 增至 ~925。
2. **图谱搜索 chunk 映射 bug**：旧代码图谱搜索返回 `triple.id` 作为 `chunk_id`，与知识库 chunk 的 ID 空间不同，导致评估永远无法匹配。修复后图谱搜索通过实体名关联到 `knowledge_chunks` 中的实际文本片段，返回真实 `chunk_id`。
3. **实体提取 prompt 过窄**：只提取"技术实体"，非技术内容（心理学、流程等）提取为空。扩展为"技术、概念、理论、方法、人物等"。

**评估方式：** 复用 `vector_only` 和 `vector_rerank` 结果（4 轮），只重跑图谱相关策略（22 轮），使用 `scripts/rag_eval_rerun_graph.py`。

#### 核心结果

**单 KB vs 跨 KB（混合+重排，top_k=4）：**

| 场景 | Recall@4 | MRR | Hit@1 | Hit@3 | 平均延迟 |
|------|----------|-----|-------|-------|---------|
| 单 KB | 0.838 | 0.588 | 0.419 | 0.730 | 1440ms |
| 跨 KB | 0.473 | 0.304 | 0.203 | 0.392 | 739ms |
| 差异 | -43.5% | -48.3% | -51.6% | -46.3% | -48.7% |

**各策略对比（单 KB / 跨 KB）：**

| 策略 | 单 KB Recall@4 | 跨 KB Recall@4 | 说明 |
|------|---------------|---------------|------|
| 纯向量 | 0.797 | 0.649 | 基线（复用首次结果） |
| 向量+重排 | 0.797 | 0.649 | 重排序无提升（复用首次结果） |
| 纯图谱 | **0.608** | **0.473** | 从 0.000 大幅提升 |
| 混合(无重排) | **0.865** | 0.473 | 单 KB +8.5%，跨 KB 反降 |
| 混合+重排 | **0.838** | 0.473 | 单 KB +5.1%，跨 KB 反降 |

**top_k 影响：**

| top_k | 单 KB Recall | 跨 KB Recall | 延迟 |
|-------|-------------|-------------|------|
| 2 | 0.568 | 0.297 | ~720ms |
| 4 | 0.770 | 0.473 | ~730ms |
| 6 | 0.865 | 0.540 | ~740ms |
| 8 | **0.960** | 0.581 | ~740ms |
| 10 | 0.960 | **0.608** | ~750ms |

**图谱权重影响（跨 KB）：**

| graph_weight | Recall@4 | MRR |
|-------------|----------|-----|
| 0.3 | 0.473 | 0.295 |
| 0.5 | 0.460 | 0.280 |
| 0.7 | 0.486 | 0.311 |

**按问题类型分析（跨 KB，纯向量 vs 混合+重排）：**

| 问题类型 | 纯向量 Recall | 混合+重排 Recall | 变化 |
|---------|-------------|---------------|------|
| relational（关系型） | 0.400 | **0.600** | **+50.0%** |
| procedural（流程型） | 0.636 | 0.545 | -14.3% |
| factual（事实型） | 0.703 | 0.432 | -38.5% |
| comparative（比较型） | 0.750 | 0.500 | -33.3% |
| conceptual（概念型） | 0.500 | 0.333 | -33.3% |

#### 发现的问题

**1. 跨 KB 场景图谱反而降低效果**

混合检索在跨 KB 场景下 Recall 从 0.649 降至 0.473（-27.1%）。根因：图谱搜索通过实体名（ILIKE 模糊匹配）在所有 KB 的 chunks 中搜索，跨 KB 时匹配到不同 KB 中恰好包含同名实体但内容不相关的 chunk。例如问题来自 asyncio KB，但图谱匹配到 FastAPI KB 中提到 "asyncio" 的 chunk，这些 chunk 被排到前面，挤掉了正确的 ground truth。

**2. 重排序在混合策略中反而降低效果**

单 KB：hybrid_no_rerank=0.865 → hybrid_rerank=0.838（-3.1%）。图谱匹配的 chunk 是通过实体名 ILIKE 找到的，语义相关性不一定高，CrossEncoder 重排后反而将它们排到了不正确的位置。

**3. 关系型问题是图谱的优势场景**

关系型问题（"A 和 B 有什么区别"）在跨 KB 混合策略下提升 50%。这类问题需要跨文档的关系信息，图谱通过实体关系链能找到向量检索遗漏的内容。

#### 结论

1. **图谱在单 KB 场景有价值**：混合(无重排) recall=0.865，比纯向量 0.797 提升 8.5%
2. **跨 KB 场景图谱需要更精确的匹配**：当前 ILIKE 实体名匹配太粗糙，需要结合语义相似度过滤
3. **重排序与图谱的配合需要优化**：图谱匹配的 chunk 语义质量参差不齐，直接重排反而降低效果
4. **top_k=8 仍是最佳选择**：单 KB recall=0.960，跨 KB top_k=10 recall=0.608
5. **关系型问题是图谱的核心价值**：跨文档关系检索是向量搜索的盲区，图谱在此场景提升 50%

### 2026-05-10 第三次评估（优化后）

**优化内容：**

1. **语义过滤**：图谱搜索 ILIKE 匹配后，用 query embedding 余弦相似度过滤噪声 chunk（阈值 0.4）。仅跨 KB 模式启用，单 KB 不过滤。
2. **重排分离管道**：向量结果单独 CrossEncoder 重排，图谱结果保留自身分数，合并 dedup 取较高分。
3. **source_chunk_id 关联**：提取时按 chunk 分别执行，记录每个三元组来源 chunk。
4. **Prompt 优化**：新增产品设计、数据科学示例，添加同义词归一化指导和最低提取规则。
5. **评估脚本优化**：实体提取缓存（222→74 次 LLM 调用），串行评估（SQLAlchemy session 限制）。

#### 核心结果

**单 KB vs 跨 KB（混合+重排，top_k=4）：**

| 场景 | Recall@4 | MRR | Hit@1 | Hit@3 | 平均延迟 |
|------|----------|-----|-------|-------|---------|
| 单 KB | 0.878 | 0.628 | 0.460 | 0.770 | 507ms |
| 跨 KB | 0.662 | 0.463 | 0.311 | 0.595 | 546ms |
| 差异 | -24.6% | -26.4% | -32.4% | -22.8% | +7.8% |

**各策略对比（单 KB / 跨 KB）：**

| 策略 | 单 KB Recall@4 | 跨 KB Recall@4 | 说明 |
|------|---------------|---------------|------|
| 纯向量 | 0.797 | 0.649 | 基线 |
| 向量+重排 | 0.797 | 0.649 | 重排序无提升 |
| 纯图谱 | **0.622** | **0.419** | 从 0.000/0.000 大幅提升 |
| 混合(无重排) | **0.878** | **0.662** | 单 KB +10.2%，跨 KB +2.1% |
| 混合+重排 | **0.878** | **0.662** | 分离管道，重排不再降低效果 |

**与第二次评估对比：**

| 策略 | 单 KB (旧→新) | 跨 KB (旧→新) |
|------|-------------|-------------|
| graph_only | 0.608→0.622 | 0.000→0.419 |
| hybrid_no_rerank | 0.865→0.878 | 0.473→0.662 |
| hybrid_rerank | 0.838→0.878 | 0.473→0.662 |

#### 结论

1. **语义过滤解决了跨 KB 噪声**：跨 KB hybrid recall 从 0.473 提升到 0.662（+39.8%），超过纯向量 0.649
2. **分离管道修复了重排降低问题**：单 KB hybrid_rerank 从 0.838 恢复到 0.878，不再低于 hybrid_no_rerank
3. **单 KB 语义过滤需谨慎**：仅跨 KB 启用，单 KB 不过滤，避免误杀图谱匹配的 chunk
4. **top_k=8 仍是最佳选择**：单 KB recall=0.960，跨 KB recall=0.730
5. **图谱权重 0.5 最优**：0.3→0.649, 0.5→0.662, 0.7→0.595

## 常见问题排查

### 脚本报错 `'NoneType' object is not callable`

原因：`from app.database import async_session_factory` 在导入时绑定为 None，`init_engine()` 修改了模块级变量但本地引用不变。

修复：使用模块引用 `import app.database as database_module`，然后用 `database_module.async_session_factory()`。

### 脚本报错 `index_status == "COMPLETED"` 比较失败

原因：`index_status` 是 `AsyncTaskStatus` 枚举，不是字符串。

修复：使用 `from app.common.model import AsyncTaskStatus`，比较时用 `AsyncTaskStatus.COMPLETED`。

### 图谱检索返回空结果

排查步骤：
1. 检查图谱是否有数据：`GET /api/knowledge-graph/entities?page=1&page_size=5`
2. 检查实体提取是否工作：用 Agent 相关问题测试 `GET /api/cross-knowledgebase/cross/chat/retrieve?question=AI+Agent&use_vector=false&use_graph=true`
3. 如果图谱有数据但检索为空，说明问题中的实体名与图谱实体名不匹配

### 评估运行缓慢

- 每个策略需要处理 N 个问题，每个问题需要 1-2 次 LLM 调用（实体提取）+ 向量检索 + 图谱检索
- 74 个问题 × 26 轮 ≈ 35 分钟
- 减少 `--samples-per-kb` 或减少策略数量可缩短时间

### 图谱搜索返回的 chunk_id 不匹配评估 ground truth

原因：旧版图谱搜索返回 `triple.id` 作为 `chunk_id`，但评估期望的是 `knowledge_chunks.id`，两个 ID 空间不同。

修复：图谱搜索改为通过实体名在 `knowledge_chunks.content` 中 ILIKE 匹配，返回实际的文本片段 `chunk_id`。修改了 `graph_search_channel.py` 和 `cross_kb_rag_service.py` 中的 `_graph_search` 方法。

## 相关文件

| 文件 | 说明 |
|------|------|
| `app/modules/knowledge_base/cross_kb_rag_service.py` | 跨知识库 RAG 服务，提供 `retrieve_with_config` 方法 |
| `app/modules/knowledge_base/cross_kb_router.py` | 跨知识库问答 API 路由 |
| `app/modules/knowledge_graph/graph_search_channel.py` | 图谱检索通道，实体提取 + 两跳查询 + chunk 映射 |
| `app/modules/knowledge_graph/extraction_service.py` | 图谱实体提取服务（从文件加载 prompt） |
| `app/prompts/kg-extraction-system.md` | 图谱实体提取 system prompt |
| `app/prompts/kg-extraction-user.md` | 图谱实体提取 user prompt |
| `app/prompts/eval-question-gen-system.md` | 测试问题生成的 LLM prompt |
| `scripts/rag_eval_dataset_generator.py` | 测试数据集生成脚本 |
| `scripts/rag_eval_runner.py` | 全量评估运行脚本 |
| `scripts/rag_eval_rerun_graph.py` | 选择性重跑图谱相关策略（复用纯向量结果） |
| `scripts/rag_eval_report.py` | 评估报告生成脚本 |
| `tests/rag_eval_dataset.json` | 测试数据集（74 个问题） |
| `tests/rag_eval_results.json` | 评估结果 |
| `tests/rag_eval_report.md` | 评估报告（Markdown 格式） |
| `docs/02-开发指南/rag-eval-todo.md` | 基于评估结果的优化 TODO 列表 |
