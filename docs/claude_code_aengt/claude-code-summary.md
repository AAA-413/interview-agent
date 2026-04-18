# Claude Code 架构总结

> 基于 12 篇渐进式文档，从零到完整 Agent 系统的全景梳理。

---

## 一、总览

Claude Code 的核心哲学是 **"一个循环 + 一个工具 = 一个 Agent"**。整个系统从一个不到 30 行的 `while True` 循环开始，通过 12 个递进章节逐步叠加机制，但循环本身始终不变。每一层新增的能力都通过注册工具和扩展 Harness（脚手架）实现，而非修改核心循环。

```
s01 循环 ──> s02 工具 ──> s03 规划 ──> s04 子代理 ──> s05 技能 ──> s06 压缩
                                                                    │
s07 任务图 ──> s08 后台 ──> s09 团队 ──> s10 协议 ──> s11 自治 ──> s12 隔离
```

**两大阶段：**

| 阶段 | 章节 | 核心主题 |
|------|------|----------|
| 单 Agent 构建 | s01–s06 | 循环、工具、规划、上下文隔离、按需知识、压缩 |
| 多 Agent 协作 | s07–s12 | 持久化任务、后台执行、团队通信、协议、自治、隔离 |

---

## 二、逐章精要

### s01: Agent 循环 — 一切的基础

**核心思想：** 模型能推理但不能触碰真实世界，循环是模型与真实世界的第一道连接。

**机制：**
- 用户 prompt 作为第一条消息
- 每轮将消息 + 工具定义发给 LLM
- 检查 `stop_reason`：若非 `tool_use` 则结束，否则执行工具、收集结果、追加为 user 消息，回到第 2 步
- 退出条件：`stop_reason != "tool_use"`

**关键代码模式：**
```python
while True:
    response = client.messages.create(model, system, messages, tools)
    messages.append({"role": "assistant", "content": response.content})
    if response.stop_reason != "tool_use":
        return
    # 执行工具，追加 tool_result
```

---

### s02: 工具使用 — 扩展边界

**核心思想：** 加工具不需要改循环，只需注册进 dispatch map。

**机制：**
- 从单一 `bash` 扩展为 4 个工具：`bash`、`read_file`、`write_file`、`edit_file`
- `TOOL_HANDLERS` 字典将工具名映射到处理函数，一个 lookup 替代 if/elif 链
- `safe_path()` 路径沙箱防止逃逸工作区
- 循环体与 s01 完全一致

**设计原则：** 加工具 = 加 handler + 加 schema，循环永远不变。

---

### s03: TodoWrite — 让模型不偏航

**核心思想：** 没有计划的 agent 走哪算哪，先列步骤再动手，完成率翻倍。

**机制：**
- `TodoManager` 存储带状态的项目（`pending` / `in_progress` / `completed`）
- 同一时间只允许一个 `in_progress`，强制顺序聚焦
- Nag reminder：模型连续 3 轮以上不调用 `todo` 时注入 `<reminder>` 提醒
- `todo` 工具和其他工具一样加入 dispatch map

**解决的问题：** 多步任务中模型丢失进度——重复做、跳步、跑偏。对话越长，系统提示影响力越被稀释。

---

### s04: Subagent — 上下文隔离

**核心思想：** 大任务拆小，每个小任务用独立的 `messages[]`，不污染主对话。

**机制：**
- 父 Agent 有 `task` 工具，Subagent 拥有除 `task` 外的所有基础工具（禁止递归生成）
- Subagent 以 `messages=[]` 启动，运行自己的循环
- 只有最终文本返回给父 Agent，整个消息历史直接丢弃
- Subagent 可能跑了 30+ 次工具调用，父 Agent 只收到一段摘要

**解决的问题：** Agent 工作越久，messages 数组越臃肿。读 5 个文件只为回答一个问题，但所有中间结果都留在上下文里。

---

### s05: Skill 加载 — 按需知识注入

**核心思想：** 用到什么知识，临时加载什么知识，不塞 system prompt。

**机制：**
- **两层架构：**
  - 第一层（便宜）：系统提示中放 Skill 名称和简短描述（~100 token/skill）
  - 第二层（贵）：模型调用 `load_skill` 时，通过 `tool_result` 注入完整内容（~2000 token）
- 每个 Skill 是一个目录，包含 `SKILL.md` 文件和 YAML frontmatter
- `SkillLoader` 递归扫描 `SKILL.md` 文件，用目录名作为标识

**解决的问题：** 10 个 Skill 每个 2000 token 全塞系统提示就是 20000 token，大部分跟当前任务无关。

---

### s06: Context Compact — 无限会话

**核心思想：** 上下文总会满，要有办法腾地方。三层压缩策略，换来无限会话。

**三层压缩：**

| 层级 | 触发条件 | 行为 |
|------|----------|------|
| Layer 1: micro_compact | 每轮静默执行 | 3 轮前的 tool_result 替换为占位符 `[Previous: used {tool_name}]` |
| Layer 2: auto_compact | token > 阈值 | 保存完整对话到 `.transcripts/`，LLM 做摘要，替换所有消息 |
| Layer 3: compact 工具 | 模型主动调用 | 同 auto_compact 的摘要机制 |

**关键点：** 完整历史通过 transcript 保存在磁盘上，信息没有真正丢失，只是移出了活跃上下文。

---

### s07: Task System — 持久化任务图

**核心思想：** 大目标要拆成小任务，排好序，记在磁盘上。文件持久化的任务图，为多 agent 协作打基础。

**机制：**
- 从扁平清单升级为持久化到磁盘的**任务图**（DAG）
- 每个任务是一个 JSON 文件，有状态和 `blockedBy` 前置依赖
- 任务图随时回答三个问题：什么可以做？什么被卡住？什么做完了？
- 完成任务时自动解锁后续任务（从 `blockedBy` 中移除）
- 状态流转：`pending` → `in_progress` → `completed`
- 四个工具：`task_create` / `task_update` / `task_list` / `task_get`

**关键意义：** 这个任务图是 s07 之后所有机制的协调骨架——后台执行、多 agent 团队、worktree 隔离都读写同一个结构。

---

### s08: Background Tasks — 后台执行

**核心思想：** 慢操作丢后台，agent 继续想下一步。

**机制：**
- `BackgroundManager` 用线程安全的通知队列追踪任务
- `run()` 启动守护线程，立即返回
- 子进程完成后，结果进入通知队列
- 每次 LLM 调用前排空通知队列，注入 `<background-results>`
- 循环保持单线程，只有子进程 I/O 被并行化

**解决的问题：** `npm install`、`pytest`、`docker build` 等慢命令阻塞式循环下模型只能干等。

---

### s09: Agent Teams — 团队邮箱

**核心思想：** 任务太大一个人干不完，要能分给队友。持久化队友 + JSONL 邮箱。

**机制：**
- `TeammateManager` 通过 `config.json` 维护团队名册
- `spawn()` 创建队友并在线程中启动 agent loop
- `MessageBus`：append-only 的 JSONL 收件箱
  - `send()` 追加一行到目标收件箱
  - `read_inbox()` 读取全部并清空（drain-on-read）
- 每个队友在每次 LLM 调用前检查收件箱，将消息注入上下文
- 队友生命周期：`spawn` → `WORKING` → `IDLE` → `WORKING` → ... → `SHUTDOWN`

**与 Subagent 的区别：** Subagent 是一次性的（无身份、无跨调用记忆），Teammate 是持久的（有身份、有生命周期、有通信通道）。

---

### s10: Team Protocols — 结构化协商

**核心思想：** 队友之间要有统一的沟通规矩。一个 request-response 模式驱动所有协商。

**机制：**
- **关机协议：** 领导发 `shutdown_request`（带唯一 `request_id`），队友 `shutdown_response`（approve/reject）
- **计划审批协议：** 队友提交 `plan_request`，领导 `plan_approval_response`（approve/reject）
- 共享 FSM：`pending` → `approved` | `rejected`
- 一个 FSM，两种用途，可套用到任何请求-响应协议

**解决的问题：** 直接杀线程留下写了一半的文件；高风险变更应该先过审。

---

### s11: Autonomous Agents — 自组织

**核心思想：** 队友自己看看板，有活就认领。不需要领导逐个分配。

**机制：**
- 队友循环分两个阶段：
  - **WORK 阶段：** 正常 agent loop，执行工具
  - **IDLE 阶段：** 每 5 秒轮询一次（最多 60 秒）
    - 检查收件箱 → 有消息则回到 WORK
    - 扫描任务看板 → 有未认领任务则自动 claim 并回到 WORK
    - 60 秒超时 → 自动关机
- **身份重注入：** 上下文压缩后 Agent 可能忘了自己是谁，检测到 `len(messages) <= 3` 时在开头插入身份块
- 新增工具：`idle`（主动进入空闲）、`claim_task`（认领任务）

**解决的问题：** 领导得给每个队友写 prompt，10 个未认领任务得手动分配，扩展不了。

---

### s12: Worktree 任务隔离 — 永不碰撞

**核心思想：** 各干各的目录，互不干扰。任务管目标，worktree 管目录，按 ID 绑定。

**机制：**
- **控制面**（`.tasks/`）：任务 JSON 文件，记录状态和绑定的 worktree
- **执行面**（`.worktrees/`）：每个任务独立的 git worktree 目录
- 创建 worktree 时自动将任务推进到 `in_progress`
- 命令在 worktree 目录中执行（`cwd` 指向隔离目录）
- 收尾两种选择：
  - `worktree_keep(name)` — 保留目录
  - `worktree_remove(name, complete_task=True)` — 删除目录 + 完成任务 + 发出事件
- **事件流：** `.worktrees/events.jsonl` 记录所有生命周期事件
- **可恢复性：** 崩溃后从 `.tasks/` + `.worktrees/index.json` 重建现场

**解决的问题：** 所有任务共享一个目录，两个 Agent 同时改同一文件互相污染，无法干净回滚。

---

## 三、架构演进全景

```
                    单 Agent 阶段                              多 Agent 协作阶段
              ┌──────────────────────┐                 ┌─────────────────────────────┐
              │                      │                 │                             │
  s01 循环 ───┤  while True + bash   │                 │  s07 任务图 (DAG, 磁盘持久)  │
              │                      │                 │       │                     │
  s02 工具 ───┤  dispatch map 4工具   │                 │  s08 后台 (线程+通知队列)    │
              │                      │                 │       │                     │
  s03 规划 ───┤  TodoManager + nag   │                 │  s09 团队 (JSONL邮箱)       │
              │                      │                 │       │                     │
  s04 子代理 ─┤  独立messages[],摘要  │                 │  s10 协议 (request-response) │
              │                      │                 │       │                     │
  s05 技能 ───┤  两层: 描述+按需加载  │                 │  s11 自治 (看板轮询+认领)    │
              │                      │                 │       │                     │
  s06 压缩 ───┤  三层: micro/auto/手动│                 │  s12 隔离 (worktree绑定)    │
              │                      │                 │                             │
              └──────────────────────┘                 └─────────────────────────────┘
```

---

## 四、核心设计模式

### 1. 循环不变原则
从 s01 到 s12，核心 `while True` 循环从未改变。所有新能力通过注册工具和扩展 Harness 实现。

### 2. 工具注册模式
每个新能力 = 一个 handler 函数 + 一个 schema 定义，加入 `TOOL_HANDLERS` 字典。循环中按名称查找处理函数，零耦合。

### 3. 上下文隔离
- **Subagent（s04）：** 独立 `messages[]`，完成后丢弃
- **Worktree（s12）：** 独立目录，物理隔离
- **压缩（s06）：** 旧内容移出活跃上下文，磁盘保留

### 4. 按需加载
- **Skill（s05）：** 名称常驻（便宜），内容按需注入（贵）
- **工具结果：** micro_compact 将旧结果替换为占位符

### 5. 文件即状态
- 任务图：`.tasks/task_*.json`
- 团队名册：`.team/config.json`
- 邮箱：`.team/inbox/*.jsonl`
- Worktree 索引：`.worktrees/index.json`
- 事件日志：`.worktrees/events.jsonl`
- 对话存档：`.transcripts/*.jsonl`

所有状态持久化到磁盘，崩溃可恢复，压缩不丢失。

### 6. 问责机制
- **Nag reminder（s03）：** 3 轮不更新 todo 就追着问
- **单 in_progress（s03）：** 强制顺序聚焦
- **协议（s10）：** 关机和计划变更必须握手确认

---

## 五、工具数量演进

| 章节 | 工具数 | 新增工具 |
|------|--------|----------|
| s01 | 1 | `bash` |
| s02 | 4 | `read_file`, `write_file`, `edit_file` |
| s03 | 5 | `todo` |
| s04 | 5+1 | `task`（仅父端） |
| s05 | 5+1 | `load_skill`（替换 task） |
| s06 | 5+1 | `compact` |
| s07 | 8 | `task_create`, `task_update`, `task_list`, `task_get` |
| s08 | 6 | `background_run`, `check` |
| s09 | 9 | `spawn`, `send`, `read_inbox` |
| s10 | 12 | `shutdown_request`, `shutdown_response`, `plan_submit`, `plan_review` |
| s11 | 14 | `idle`, `claim_task` |
| s12 | 16+ | `worktree_create`, `worktree_remove`, `worktree_keep`, `worktree_list` 等 |

---

## 六、关键洞察

1. **简单循环的威力：** 不到 30 行代码构成整个 Agent 的核心，12 个章节的复杂度都叠加在外围，循环本身始终不变。

2. **隔离是扩展的前提：** 从 Subagent 的消息隔离，到压缩的上下文隔离，到 Worktree 的目录隔离——每一步扩展都建立在隔离之上。

3. **文件是真相来源：** 内存状态随时可能丢失（压缩、崩溃、重启），磁盘上的 JSON/JSONL 文件才是可信赖的状态。

4. **自治需要结构：** 自组织（s11）不是无序的，它依赖任务图（s07）提供看板、依赖协议（s10）提供协商、依赖隔离（s12）避免冲突。

5. **两层知识架构：** 常驻信息放系统提示（便宜），领域知识按需注入（贵），这是 token 经济学的基本策略。

6. **从指派到自治的渐进：** s04 Subagent 被动执行 → s09 Teammate 有身份但被动等待 → s11 Autonomous 主动认领任务，自治程度逐步提升。
