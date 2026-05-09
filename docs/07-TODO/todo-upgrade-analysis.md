# 系统升级分析与 TODO 清单

> 生成日期：2026-05-06
> 最后更新：2026-05-07
> 范围：多 Agent 通讯结构、用户隔离安全、并发能力、智能下载与 RAG 展示优化

### 修复进度汇总（2026-05-07）

- ✅ **竞争条件 Bug**：知识库/简历上传路径在事务提交前分发 Redis 任务 → 在 enqueue 前增加 `db.commit()`
- ✅ **P0 安全漏洞**（4/4）：U-P1~U-P4 全部修复
- ✅ **P1 用户体验**（3/3）：R-P1 RAG 完整内容、R-P2 引用可展开、S-P1 下载展示文档
- ✅ **P2 架构优化**（3/5）：A-P2 清理死代码、C-P2 LLM 并发队列、R-P4 Markdown 渲染
- ✅ **P2 全部完成**（5/5）
- ✅ **P3 锦上添花**（9/9）：全部完成

---

## 一、多 Agent 编排 — 消息通讯结构分析

### 1.1 当前架构

系统存在 **两套并行但未统一** 的 Agent 通讯框架：

| 维度 | System A（活跃） | System B（死代码） |
|------|-----------------|-------------------|
| 使用位置 | `orchestrator.py` 实际调用 | `agent_chain.py` + `base_agent.py` 定义但未使用 |
| 消息格式 | `Dict[str, Any]` 无 schema 校验 | `DynamicContext` 可变共享状态对象 |
| 通讯方式 | 直接函数调用，dict 传参 | 责任链遍历，context 传递 |
| Agent 接口 | 各 Agent 自定义方法签名（`plan()`/`execute()`/`check()`/`summarize()`） | 统一 `apply(context)` + `get_next(context)` |

**结论**：System B 的 `BaseAgent`、`AgentChain`、`DynamicContext`、`AgentContext`、`Result`、`AgentResult` 均为死代码，实际 Agent 从未实现这些接口。

### 1.2 数据流路径

```
用户输入
  │
  ▼
DecisionTree.decide()  ← 规则引擎选择 simple/standard/complex 路径
  │
  ▼
PlanningAgent.plan()   ← 返回 {intent, complexity, subtasks[], strategy}
  │
  ├─ sequential: 逐任务执行，previous_results 累积传递
  ├─ parallel:   asyncio.gather，任务间无数据共享
  └─ hybrid:     拓扑排序，同层并行，跨层依赖传递
  │
  ▼
QualityAgent.check()   ← 评分+问题列表，失败则调整 plan 重试（最多 2 次）
  │
  ▼
SummaryAgent.summarize() ← 合并所有结果生成最终回答
```

### 1.3 核心问题

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| A1 | Agent 间无统一消息协议 | 中 | 各 Agent 返回的 `result` 内部结构完全不同，无类型校验 |
| A2 | 责任链系统为死代码 | 低 | `BaseAgent`/`AgentChain`/`DynamicContext` 从未被 orchestrator 使用，增加维护负担 |
| A3 | `AgentToolRegistry` 注册了工具但从未分发给 Agent | 低 | 工具注册与 Agent 执行脱节 |
| A4 | `CostController` 无锁保护 | 低 | asyncio 单线程下安全，但切换到多线程会出竞态 |
| A5 | `AgentFactory._agent_cache` 无同步机制 | 低 | 同上，asyncio 下安全但设计脆弱 |
| A6 | parallel 模式下忽略任务间依赖 | 中 | `_execute_parallel()` 给每个任务空 `previous_results`，如果 plan 有依赖则静默失败 |
| A7 | 无任务取消/超时机制 | 中 | `asyncio.gather()` 中某个任务卡死则整体阻塞 |

### 1.4 升级 TODO

- [x] **A-P1：统一 Agent 消息协议** — 定义 `AgentMessage` Pydantic 模型，包含 `task_id`、`agent_type`、`status`、`result`、`error`、`metadata`，所有 Agent 强制返回此类型
- [x] **A-P2：清理死代码** — 删除或重构 `BaseAgent`/`AgentChain`/`DynamicContext`/`AgentContext`/`Result`/`AgentResult`，要么让 orchestrator 真正使用责任链，要么移除
- [x] **A-P3：接入 ToolRegistry** — 让执行 Agent 在 `execute()` 中可以调用注册的工具，实现工具-执行解耦
- [x] **A-P4：parallel 模式增加依赖校验** — 当 strategy=parallel 时检查 subtasks 是否有依赖，有则自动降级为 hybrid
- [x] **A-P5：增加任务超时** — 给 `asyncio.gather()` 中每个任务加 `asyncio.wait_for(timeout=...)` 防止卡死

---

## 二、多用户隔离 — 安全问题分析

### 2.1 当前认证链路

```
HTTP 请求 → auth_middleware（JWT 解码 → request.state.user_id）
                → get_current_user_id（从 request.state 读取）
                → get_current_user（解码 JWT + 查 DB）
```

FastAPI 的 `request.state` 是 per-request 对象，middleware 层面不泄露。但 **业务层存在多处遗漏**。

### 2.2 安全漏洞清单

| # | 漏洞 | 严重度 | 位置 | 说明 |
|---|------|--------|------|------|
| U1 | Agent Chat 不关联用户 | **HIGH** | `agent_orchestration/router.py:96` | `create_execution()` 未传 `user_id`，所有执行记录 `user_id=NULL` |
| U2 | 执行历史无权限校验 | **HIGH** | `agent_orchestration/router.py:236` | `GET /executions/{session_id}` 不验证所有权，任意用户可读他人数据 |
| U3 | 执行列表泄露全局数据 | **HIGH** | `agent_orchestration/router.py:270` | `list_executions()` 不按 `user_id` 过滤，返回所有用户的执行记录 |
| U4 | 智能下载进度端点无认证 | **MEDIUM** | `smart_download_router.py:251` | `GET /progress/{task_id}` 不要求 JWT，仅靠 UUID 不可猜测做安全保证 |
| U5 | 知识库归属未校验 | **MEDIUM** | `smart_download_router.py:726` | 提供 `kb_id` 时不验证请求用户是否拥有该知识库，可向他人 KB 注入内容 |
| U6 | Redis key 未按用户隔离 | **LOW** | `smart_download_router.py:24-25` | `smart_download:plan:{uuid}` 不含 `user_id`，无法按用户清理或审计 |
| U7 | GitHub API 共享限额 | **MEDIUM** | `common/tools/github_service.py:295` | 全局单例 `github_service`，所有用户共享 60 次/小时未认证限额 |

### 2.3 升级 TODO

- [x] **U-P1（紧急）：Agent Chat 关联用户** — `router.py` 的 `/chat` 端点注入 `get_current_user_id`，`create_execution()` 传入 `user_id`；`list_executions()` 按 `user_id` 过滤
- [x] **U-P2（紧急）：执行详情加权限校验** — `GET /executions/{session_id}` 查询时加 `WHERE user_id = :user_id` 条件
- [x] **U-P3：智能下载进度加认证** — `/progress/{task_id}` 端点增加 `Depends(get_current_user_id)`，Redis 存储时记录 `user_id`，查询时校验
- [x] **U-P4：知识库归属校验** — `_add_to_knowledge_base()` 中当 `kb_id` 存在时，查询 KB 记录验证 `user_id` 匹配
- [x] **U-P5：Redis key 加用户前缀** — 改为 `smart_download:{user_id}:plan:{uuid}`，支持按用户清理
- [x] **U-P6：GitHub token 支持** — 支持用户配置个人 GitHub token，或实现 token 池轮换机制

---

## 三、并行智能下载 — 并发能力分析

### 3.1 当前并发模型

```
POST /execute → BackgroundTasks.add(_execute_download_with_retry)
                     │
                     ├─ 每个请求独立协程
                     ├─ AgentOrchestrator 每次 new 实例（非单例）
                     ├─ Agent 实例被 AgentFactory 缓存（无状态，安全）
                     ├─ Redis 连接池 max_connections=50
                     └─ Redis key 用 UUID 无冲突
```

### 3.2 并发安全评估

| 组件 | 是否安全 | 说明 |
|------|---------|------|
| `AgentOrchestrator` | ✅ | 每次请求 new 实例，无共享状态 |
| `AgentFactory._agent_cache` | ⚠️ | asyncio 单线程安全，多线程不安全 |
| `CostController` | ⚠️ | 同上，无锁保护 |
| `RedisService` | ✅ | aioredis 连接池，天然并发安全 |
| Redis key | ✅ | UUID 无冲突，但不含 user_id 不利于管理 |
| `BackgroundTasks` | ✅ | FastAPI 内置，每个请求独立任务 |
| `github_service` | ❌ | 全局单例共享 60 次/小时限额 |

### 3.3 瓶颈分析

| 瓶颈 | 影响 | 现状 |
|------|------|------|
| GitHub API 限额 | 多用户同时智能下载 GitHub 内容会快速耗尽 | 60 次/小时未认证 |
| LLM API 并发 | 多个下载任务同时调用 DeepSeek/DashScope | 依赖 provider 并发限制 |
| PostgreSQL 连接 | 向量检索 + 写入同时进行 | asyncpg 连接池，通常足够 |
| `integrate_contents` 限制 3 源 | 丢弃第 4+ 个源的信息 | 源数量被截断 |

### 3.4 升级 TODO

- [x] **C-P1：GitHub token 池** — 维护多个 GitHub token 轮换使用，或支持用户提供自己的 token
- [x] **C-P2：LLM 调用增加并发队列** — 对 LLM API 调用增加信号量限制（如 `asyncio.Semaphore(10)`），防止触发 provider 限流
- [x] **C-P3：integrate_contents 分层摘要** — 超过 3 源时采用"先分组摘要，再合并摘要"的两级策略，避免信息丢失
- [x] **C-P4：增加任务取消支持** — 用户可以在前端取消正在执行的智能下载任务

---

## 四、智能下载展示优化 — 片段整合问题

### 4.1 问题描述

当前智能下载完成后，用户看到的是：

```
┌─────────────────────────────────────┐
│ 标题: xxx                           │
│ 摘要: xxx（50字）                    │
│ 来源数: 3                           │
│ 总字数: 2800                        │
│ 来源: [URL1, URL2, URL3]            │
│ 知识库: xxx（点击跳转）              │
└─────────────────────────────────────┘
```

**用户看不到实际内容**。要阅读下载结果，必须跳转到知识库详情页，而那里展示的是 180 字符的分块预览。

### 4.2 内容合成链路分析

```
原始网页（4000字符）
  │ _clean_content() LLM 清洗
  ▼
清洗后片段（~1500字符/源，最多N个源）
  │ integrate_contents() LLM 合成
  │ ⚠️ 截断为最多3源，每源2000字符
  ▼
合成文档（~3000字符）
  │ 保存为 KnowledgeBaseEntity.source_text
  ▼
异步分块（900字符/块，120字符重叠）
  │ Embedding → pgvector
  ▼
知识库块（KnowledgeChunkEntity）
```

**信息损失点**：
1. `integrate_contents` 限制 3 源 → 第 4+ 源丢失
2. 合成文档 3000 字符上限 → 被截断
3. 分块后原始结构丢失 → 用户看到碎片

### 4.3 升级 TODO

- [x] **S-P1：智能下载完成后直接展示合成文档** — 在 SmartDownloadPage 的完成阶段增加一个可展开的文档预览区域，渲染 `integrated_content` 的完整内容（支持 Markdown）
- [x] **S-P2：每个源独立摘要** — 在合成之前，先对每个源生成独立摘要（~200字），展示给用户"每个来源提取了什么"
- [x] **S-P3：分层合成策略** — 超过 3 源时：
  ```
  源1-3 → 摘要A    源4-6 → 摘要B    源7-9 → 摘要C
              └──────────┬──────────┘
                    最终合成文档
  ```
- [x] **S-P4：重新启用 SummaryAgent** — 取消 `smart_download_router.py:549` 的注释，让 SummaryAgent 对合成文档做二次精炼，生成结构化目录+要点提炼
- [x] **S-P5：下载结果增加结构化目录** — 合成文档自动生成 `## 目录`、`## 核心要点`、`## 代码示例` 等分节，而非纯文本

---

## 五、知识库问答优化 — 片段回答问题

### 5.1 问题描述

当前 RAG 问答的回答基于 **180 字符的片段预览**，导致：
- 回答内容浅显，缺乏细节
- 引用片段太短，用户无法判断相关性
- 片段之间缺乏关联，回答是"拼凑"而非"综合"

### 5.2 根因定位

**关键代码** `rag_service.py:235`：
```python
f"内容: {item.content_preview}"  # content_preview 只有 180 字符
```

而完整块内容最多 900 字符（代码块 1200），但 `RagReferenceDTO` 只携带了 `content_preview`。

### 5.3 信息流对比

```
当前：问题 → Embedding → 检索 top_k 块 → 取每块前180字 → LLM 生成回答
理想：问题 → Embedding → 检索 top_k 块 → 取每块完整内容 → LLM 生成回答 → 后处理增强
```

### 5.4 升级 TODO

- [x] **R-P1（最高优先级）：RAG 回答使用完整块内容** — `RagReferenceDTO` 增加 `content` 字段（完整内容），`_build_answer_prompt()` 改用 `content` 而非 `content_preview`。考虑到 token 成本，可限制 top_k 为 3-5 个块
- [x] **R-P2：引用片段可展开** — 前端 KnowledgeBaseDetailPage 的引用卡片支持点击展开显示完整块内容，而非只显示 180 字符
- [x] **R-P3：答案后处理增强** — 在 LLM 生成回答后增加后处理步骤：
  - 自动添加来源引用标注（如 [1][2]）
  - 提取关键代码块单独展示
  - 生成 2-3 个推荐追问
- [x] **R-P4：答案渲染 Markdown** — 前端用 Markdown 渲染器替代 `whitespace-pre-wrap`，支持代码高亮、列表、表格等格式
- [x] **R-P5：块来源追溯** — 每个 `KnowledgeChunkEntity` 记录其所属文档名称和分块位置（章节/段落），在引用时展示"来自《xxx》第3节"
- [x] **R-P6：多轮对话上下文** — RAG 问答支持对话历史，追问时自动关联前文上下文改写 query

---

## 六、优先级排序

### P0 — 紧急修复（安全漏洞）✅ 全部完成

| 编号 | 任务 | 预估工时 | 状态 |
|------|------|---------|------|
| U-P1 | Agent Chat 关联用户 | 1h | ✅ |
| U-P2 | 执行详情加权限校验 | 0.5h | ✅ |
| U-P3 | 智能下载进度加认证 | 0.5h | ✅ |
| U-P4 | 知识库归属校验 | 0.5h | ✅ |

### P1 — 高价值改进（用户体验）✅ 全部完成

| 编号 | 任务 | 预估工时 | 状态 |
|------|------|---------|------|
| R-P1 | RAG 回答使用完整块内容 | 2h | ✅ |
| S-P1 | 智能下载展示合成文档 | 3h | ✅ |
| R-P2 | 引用片段可展开 | 2h | ✅ |

### P2 — 架构优化（5/5 完成）✅

| 编号 | 任务 | 预估工时 | 状态 |
|------|------|---------|------|
| A-P1 | 统一 Agent 消息协议 | 4h | ✅ |
| A-P2 | 清理死代码 | 2h | ✅ |
| S-P3 | 分层合成策略 | 4h | ✅ |
| C-P2 | LLM 并发队列 | 2h | ✅ |
| R-P4 | 答案渲染 Markdown | 2h | ✅ |

### P3 — 锦上添花（11/11 完成）✅

| 编号 | 任务 | 预估工时 | 状态 |
|------|------|---------|------|
| S-P2 | 每个源独立摘要 | 3h | ✅ |
| S-P4 | 重新启用 SummaryAgent | 2h | ✅ |
| S-P5 | 下载结果结构化目录 | 2h | ✅ |
| R-P3 | 答案后处理增强 | 3h | ✅ |
| R-P5 | 块来源追溯 | 3h | ✅ |
| R-P6 | 多轮对话上下文 | 4h | ✅ |
| U-P5 | Redis key 加用户前缀 | 1h | ✅ |
| U-P6 | GitHub token 池 | 3h | ✅ |
| C-P1 | GitHub token 轮换 | 3h | ✅ |
| C-P4 | 任务取消支持 | 2h | ✅ |
| A-P3 | 接入 ToolRegistry | 2h | ✅ |
| A-P4-P5 | parallel 依赖校验 + 任务超时 | 2h | ✅ |

---

## 七、涉及文件索引

### Agent 编排
- `app/modules/agent_orchestration/orchestrator.py` — 主编排器
- `app/modules/agent_orchestration/agent_factory.py` — Agent 工厂
- `app/modules/agent_orchestration/agent_chain.py` — 责任链（死代码）
- `app/modules/agent_orchestration/base_agent.py` — 基类定义（死代码）
- `app/modules/agent_orchestration/cost_controller.py` — 成本控制器
- `app/modules/agent_orchestration/tool_registry.py` — 工具注册表
- `app/modules/agent_orchestration/agents/*.py` — 5 个 Agent 实现

### 用户隔离
- `app/main.py:131-163` — auth middleware
- `app/modules/auth/dependencies.py` — get_current_user_id
- `app/modules/agent_orchestration/router.py` — Agent Chat 路由（有问题）
- `app/modules/agent_orchestration/persistence_service.py` — 持久化层
- `app/modules/agent_orchestration/smart_download_router.py` — 智能下载路由

### 智能下载
- `app/modules/agent_orchestration/smart_download_router.py` — 两阶段流程
- `app/modules/agent_orchestration/agents/execution_agent.py:601` — `integrate_contents()`
- `app/modules/agent_orchestration/agents/summary_agent.py` — 未启用的摘要 Agent
- `frontend/src/pages/SmartDownloadPage.tsx` — 前端展示

### RAG 问答
- `app/modules/knowledge_base/rag_service.py:226` — `_build_answer_prompt()`（核心问题）
- `app/modules/knowledge_base/rag_router.py` — RAG API
- `app/modules/knowledge_base/vector_service.py` — 分块 + Embedding
- `app/modules/knowledge_base/search_channel.py` — 向量检索
- `app/modules/knowledge_base/rerank_service.py` — 重排序
- `app/modules/knowledge_base/schemas.py` — `RagReferenceDTO` 定义
- `frontend/src/pages/KnowledgeBaseDetailPage.tsx` — 前端展示
