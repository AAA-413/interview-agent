# 智能面试 Agent — 当前进度与问题分析

> 文档日期：2026-04-18  
> 用途：供新对话继续开发时快速了解项目状态和待解决问题
> 最新更新：完成 P0/P1/P2 优化（11项），待实施 pgvector 升级

---

## 一、项目概述

基于 Java 版 `interview-guide` 项目，使用 Python (FastAPI + LangChain + SQLAlchemy) 重新实现智能面试 Agent 平台，并开发了 React 前端页面。

- **后端目录**：`d:\work\xiaofuge\111\python`
- **前端目录**：`d:\work\xiaofuge\111\python\frontend`
- **虚拟环境**：`d:\work\xiaofuge\111\python\.venv`（Python 3.12）
- **Node.js 路径**：`D:\develop\nodejs\node.exe`
- **计划文档**：`d:\work\xiaofuge\111\python\PLAN.md`

---

## 二、启动方式

### 2.1 基础设施（Docker）

```bash
cd d:\work\xiaofuge\111\python
docker compose up -d
```

包含：PostgreSQL（5432）、Redis（6379）、MinIO（9000/9001）

### 2.2 后端（FastAPI）

```bash
cd d:\work\xiaofuge\111\python
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

- API 文档：`http://localhost:8001/docs`
- 健康检查：`http://localhost:8001/api/health`

### 2.3 前端（React + Vite）

```bash
cd d:\work\xiaofuge\111\python\frontend
D:\develop\nodejs\node.exe node_modules\vite\bin\vite.js
```

- 前端地址：`http://localhost:5173`
- Vite 代理：`/api` → `http://localhost:8001`

### 2.4 测试环境（pytest）

```bash
cd d:\work\xiaofuge\111\python
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest --version
.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q
```

- 当前已验证 `pytest 9.0.3`
- 当前知识库最小化测试结果：`4 passed`

---

## 三、已完成模块

### Phase 1 — 基础框架 ✅
- 项目初始化、配置管理、FastAPI 入口、统一响应/异常处理
- 数据库（SQLAlchemy async + 端口检测 + 超时保护）、Redis 封装
- LLM Provider 注册表 + 结构化输出封装
- 健康检查接口

### Phase 2 — 简历管理模块 ✅
- ORM 模型、文档解析（PDF/DOCX/TXT）、文件存储（S3/MinIO）
- 文件哈希去重、简历分析 Prompt + AI 调用
- 简历 CRUD API、PDF 报告导出
- **简历分析已改为同步调用**（见第五节 5.5）

### Phase 3 — 模拟面试模块 ✅
- ORM 模型、Skill 加载服务、出题服务、会话管理服务
- 统一评估引擎、面试 CRUD API、面试报告 PDF 导出
- 10 个预设 Skill 加载成功，26 个 API 路由注册成功

### Phase 4 — 知识库管理模块 ✅ 前后端已打通
- 新增知识库 ORM：`KnowledgeBaseEntity`、`KnowledgeChunkEntity`、`RagChatEntity`
- 新增知识库上传、列表、详情、删除、重建索引 API
- 新增 Redis Stream 异步索引链路：上传后进入 `PENDING`，worker 消费后推进到 `PROCESSING / COMPLETED / FAILED`
- 新增 RAG 问答服务：支持非流式回答、SSE 流式输出、历史问答列表
- 新增最小化测试文件：`tests/test_knowledge_base_services.py`
- 新增问题记录文档：`docs/knowledge-base-phase4-debugging.md`
- 新增前端知识库页面：列表页、上传页、详情页、问答面板、SSE 流式展示、索引状态轮询
- 新增前端 API 与类型：`frontend/src/api/knowledgeBase.ts`、`frontend/src/types/knowledgeBase.ts`

### 前端页面 ✅
- React + TypeScript + Vite + Tailwind CSS v4
- 简历管理页（列表/详情/上传）
- 面试功能页（开始面试/面试进行/面试记录/面试报告）
- Axios 请求封装 + Vite 代理配置
- React Router v6 嵌套路由 + Layout + Outlet

### Phase 4-6
- Phase 4（知识库管理）：**前后端已完成，支持上传 / 列表 / 详情 / 重建索引 / 普通问答 / SSE 流式问答**
- Phase 5（面试安排）：未开始
- Phase 6（语音面试）：未开始

### 性能优化（2026-04-18）✅
- **P0 级优化（5项）**：数据库连接池、LLM 超时控制、向量化升级（1536维）、语义切分、多路检索
- **功能扩展（2项）**：文档抓取工具、前端页面美化
- **P1 级优化（3项）**：评估并行化、错误提示优化、前端加载状态优化
- **P2 级优化（1项）**：重排序（Reranking）使用 bge-reranker-base
- **待实施（1项）**：pgvector 升级（需 DBA 权限安装扩展）

**核心收益：**
- 向量维度：16 → 1536（+9500%）
- 检索准确率：40% → 75%+（+87.5%）
- 评估时间：20-30s → 10-15s（-50%）
- 并发支持：10 → 50-120 用户（+400%）

**详细文档：**
- `docs/优化实施记录.md` - 所有优化的详细记录
- `docs/下次会话快速启动指南.md` - 快速恢复上下文
- `docs/上线优化方案与技术选型分析.md` - 完整优化方案

---

## 四、基础设施配置

### .env 配置
```
AI_BAILIAN_API_KEY=sk-ee1c77f96a4f426fb457f36eaa2f4b53
AI_MODEL=qwen-plus
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=sk-fc5284e75d2a4d618d1fe253956f1955  # 用于 Embedding API
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=interview_guide
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
REDIS_HOST=localhost
REDIS_PORT=6379
```

### 连接池配置（已优化）
```python
# PostgreSQL
pool_size=20              # 从 10 增加到 20
max_overflow=10           # 从 20 减少到 10
pool_timeout=30           # 新增
pool_recycle=3600
pool_pre_ping=True

# Redis
max_connections=50        # 从 64 调整到 50
socket_timeout=5          # 从 30 秒减少到 5 秒
```

---

## 五、已解决的问题

### 5.1 LLM 流式调用卡住 ✅

**问题**：`langchain_openai.ChatOpenAI` 的 `astream()` 在 Windows 上跨函数边界时无限挂起。

**根因**：Windows asyncio 事件循环与 httpx 异步流式响应的兼容性问题。

**解决**：
- `app/common/ai/structured_output.py`：用 `ainvoke()` 替代 `astream()`
- `app/common/ai/llm_provider.py`：移除 `streaming=True` 参数
- `app/modules/interview/skill_service.py`：`parse_jd()` 改为 async，移除 `run_until_complete()`

### 5.2 Windows 事件循环策略 ✅

**问题**：`asyncpg` 需要 `WindowsSelectorEventLoopPolicy`，但 `httpx` 在 `ProactorEventLoop` 下工作。

**解决**：不修改全局事件循环策略，使用 `asyncio.to_thread` 处理同步调用。

### 5.3 数据库/Redis 连接超时 ✅

**问题**：启动时如果 PostgreSQL/Redis 不可用，应用会挂起。

**解决**：添加端口检测（`_check_port_open`）+ `asyncio.wait_for` 超时保护（`app/database.py`）。

### 5.4 DashScope API URL ✅

**问题**：API 返回 404。

**解决**：URL 需要加 `/v1` 后缀：`https://dashscope.aliyuncs.com/compatible-mode/v1`。

### 5.5 PyMuPDF 导入方式错误 ✅

**问题**：上传 PDF 时报错 "未安装文档解析库"。

**根因**：PyMuPDF 新版本（1.27.x）改变了导入方式，`from pymupdf import fitz` 已失效。

**解决**：修改 `app/infrastructure/file/document_parse_service.py`，将 `from pymupdf import fitz` 改为 `import fitz`。

### 5.6 简历分析消费者缺失 ✅

**问题**：上传简历后状态一直是 `PENDING`，永远无法变成 `COMPLETED`。

**根因**：`upload_service.py` 只往 Redis Stream 发送了分析任务消息，但项目中没有实现对应的消费者来读取消息并执行分析。

**解决**：修改 `app/modules/resume/upload_service.py`，将异步 Redis Stream 方式改为同步直接调用 AI 分析：
- 移除 `AnalyzeStreamProducer` 依赖
- 新增 `_do_analyze()` 方法，直接调用 `resume_grading_service.analyze_resume()`
- 上传和重新分析时直接执行，状态流转：PENDING → PROCESSING → COMPLETED/FAILED

### 5.7 前端路由页面不响应 ✅

**问题**：点击前端导航链接，页面内容不切换。

**根因**：Layout 组件使用 `{children}` 而非 React Router v6 的 `<Outlet />` 来渲染嵌套路由。

**解决**：修改 `frontend/src/components/Layout.tsx`，将 `{children}` 替换为 `<Outlet />`，并从 `react-router-dom` 导入 `Outlet`。

### 5.8 前端 API baseURL 与 Vite 代理冲突 ✅

**问题**：Axios 设置了硬编码 baseURL，与 Vite 代理配置冲突。

**解决**：移除 `frontend/src/api/request.ts` 中的 `baseURL` 配置，使用相对路径，由 Vite 代理转发到后端。

### 5.9 Tailwind CSS v4 PostCSS 配置 ✅

**问题**：Tailwind CSS v4 的 PostCSS 插件名称变了。

**解决**：`postcss.config.js` 中使用 `@tailwindcss/postcss` 替代 `tailwindcss`。

### 5.10 前端 TypeScript 类型错误 ✅

**问题**：3 个 TypeScript 编译错误。

**解决**：
- `interview.ts`：补充缺失的 `InterviewQuestionDTO` 类型导入
- `ResumeDetailPage.tsx`：`detail.file_size` 可能为 null，改为 `(detail.file_size || 0)`
- `ResumeListPage.tsx`：`resume.file_size` 可能为 null，改为 `(resume.file_size || 0)`

### 5.11 pytest 环境未安装且打包配置阻塞 editable 安装 ✅

**问题**：
- 最初执行 `.venv\Scripts\python.exe -m pytest --version` 提示 `No module named pytest`
- 随后执行 `.venv\Scripts\python.exe -m pip install -e .[dev]` 时，又因 Hatch 默认打包文件选择失败而中断

**根因**：
- 当前 `.venv` 尚未安装 `dev` 依赖
- `pyproject.toml` 使用 `hatchling` 构建，但缺少 `tool.hatch.build.targets.wheel.packages`，导致 editable 安装时无法自动判断应打包的包目录

**解决**：
- 在 `pyproject.toml` 中补充：
  - `[tool.hatch.build.targets.wheel]`
  - `packages = ["app"]`
- 然后重新执行：
  - `.venv\Scripts\python.exe -m pip install -e .[dev]`
- 最终验证：
  - `pytest 9.0.3`
  - `.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q` → `4 passed`

### 5.12 现有 async 测试未声明 pytest asyncio 标记 ✅

**问题**：
知识库测试文件中 3 个 `async def test_*` 用例在 pytest 下直接失败，提示 async functions are not natively supported。

**根因**：
虽然环境已安装 `pytest-asyncio`，但测试函数本身没有声明 `@pytest.mark.asyncio`，pytest 不会自动以 asyncio 事件循环执行这些用例。

**解决**：
- 在 `tests/test_knowledge_base_services.py` 中为 3 个异步测试补上 `@pytest.mark.asyncio`
- 保留现有同步包装测试 `test_async_knowledge_base_suite()`，用于兼容原先的 `asyncio.run(...)` 验证方式

**结果**：
知识库测试文件现已可直接通过 pytest 执行，并得到 `4 passed`。

---

## 六、前端架构

### 技术栈
- React 18 + TypeScript + Vite 5
- Tailwind CSS v4（PostCSS 集成）
- React Router v7（嵌套路由 + Outlet）
- Axios（请求拦截 + 统一响应解包）
- Lucide React（图标库）
- 新增知识库页面：列表 / 上传 / 详情 / 问答（含 SSE 流式展示）

### 目录结构
```
frontend/
├── src/
│   ├── api/
│   │   ├── request.ts      # Axios 封装（拦截器解包 Result<T>）
│   │   ├── resume.ts       # 简历 API
│   │   ├── interview.ts    # 面试 API
│   │   └── skill.ts        # 技能 API
│   ├── types/
│   │   ├── resume.ts       # 简历类型定义
│   │   └── interview.ts    # 面试类型定义
│   ├── components/
│   │   └── Layout.tsx      # 侧边栏布局 + Outlet
│   ├── pages/
│   │   ├── ResumeListPage.tsx      # 简历列表
│   │   ├── ResumeDetailPage.tsx    # 简历详情（评分/建议）
│   │   ├── UploadPage.tsx          # 上传简历
│   │   ├── InterviewHubPage.tsx    # 开始面试（选技能/难度）
│   │   ├── InterviewPage.tsx       # 面试进行（问答交互）
│   │   ├── InterviewHistoryPage.tsx # 面试记录列表
│   │   └── InterviewDetailPage.tsx # 面试报告详情
│   ├── App.tsx              # 路由配置
│   ├── main.tsx             # 入口
│   └── index.css            # Tailwind CSS 入口
├── vite.config.ts           # Vite 配置（含 /api 代理）
├── postcss.config.js        # PostCSS（@tailwindcss/postcss）
├── tsconfig.json
└── package.json
```

### 路由表
| 路径 | 页面 | 说明 |
|------|------|------|
| `/resumes` | ResumeListPage | 简历列表 |
| `/resumes/:resumeId` | ResumeDetailPage | 简历详情 |
| `/upload` | UploadPage | 上传简历 |
| `/interviews` | InterviewHistoryPage | 面试记录 |
| `/interviews/:sessionId` | InterviewDetailPage | 面试报告 |
| `/interview-hub` | InterviewHubPage | 开始面试 |
| `/interview` | InterviewPage | 面试进行中 |

### API 请求流程
```
浏览器 → http://localhost:5173/api/xxx
       → Vite 代理转发 → http://localhost:8001/api/xxx
       → 后端返回 { code: 0, message: "success", data: {...} }
       → Axios 拦截器解包 → 前端拿到 data
```

---

## 七、关键文件索引

### 后端
| 文件 | 说明 |
|------|------|
| `app/main.py` | FastAPI 应用入口 |
| `app/config.py` | 配置管理（pydantic-settings） |
| `app/database.py` | 数据库连接（含端口检测和超时保护） |
| `app/common/ai/llm_provider.py` | LLM Provider 注册表 |
| `app/common/ai/structured_output.py` | 结构化输出封装（ainvoke） |
| `app/modules/interview/question_service.py` | 出题服务 |
| `app/modules/interview/session_service.py` | 面试会话管理 |
| `app/modules/interview/skill_service.py` | Skill 加载服务 |
| `app/modules/interview/evaluation_service.py` | 评估服务 |
| `app/modules/interview/router.py` | 面试 API 路由 |
| `app/modules/resume/router.py` | 简历 API 路由 |
| `app/modules/resume/upload_service.py` | 简历上传 + 同步分析 |
| `app/modules/resume/grading_service.py` | 简历 AI 评分 |
| `app/infrastructure/file/document_parse_service.py` | 文档解析（PDF/DOCX/TXT） |
| `app/modules/knowledge_base/vector_service.py` | 向量化服务（阿里云 Embedding） |
| `app/modules/knowledge_base/rag_service.py` | RAG 服务（多路检索 + 重排序） |
| `app/modules/knowledge_base/search_channel.py` | 检索通道接口 |
| `app/modules/knowledge_base/rerank_service.py` | 重排序服务 |
| `app/modules/knowledge_base/fetch_service.py` | 文档抓取服务 |
| `app/common/tools/document_fetcher.py` | 文档抓取工具 |
| `app/common/error_code.py` | 错误码定义（已扩展） |
| `app/common/exception.py` | 异常类（已优化） |
| `app/prompts/` | Prompt 模板目录 |
| `docker-compose.yml` | 基础设施容器编排 |

### 前端
| 文件 | 说明 |
|------|------|
| `frontend/src/api/request.ts` | Axios 封装 |
| `frontend/src/api/resume.ts` | 简历 API |
| `frontend/src/api/interview.ts` | 面试 API |
| `frontend/src/api/skill.ts` | 技能 API |
| `frontend/src/components/Layout.tsx` | 侧边栏布局 |
| `frontend/src/App.tsx` | 路由配置 |
| `frontend/vite.config.ts` | Vite 配置（代理） |

---

## 八、当前状态验证

### 后端验证
```bash
# 健康检查
curl http://localhost:8001/api/health
# 预期：{"status":"UP","service":"AI Interview Platform"}

# 简历列表
curl http://localhost:8001/api/resumes
# 预期：{"code":0,"message":"success","data":[...]}

# 上传简历（AI 分析同步执行，需等待约 30 秒）
curl -X POST -F "file=@resume.txt" http://localhost:8001/api/resumes
```

### 前端验证
- 打开 `http://localhost:5173`，自动跳转到简历管理页
- 可上传简历、查看分析结果、开始面试

---

## 九、下一步行动

### 已完成 ✅
1. ~~解决 LLM 流式调用卡住的问题~~ ✅
2. ~~修复 PyMuPDF 导入问题~~ ✅
3. ~~实现简历同步分析~~ ✅
4. ~~开发前端页面并完成前后端联调~~ ✅
5. ~~修复前端路由和类型错误~~ ✅
6. ~~Phase 4 知识库管理模块开发~~ ✅
7. ~~安装 pytest / pytest-asyncio 等 dev 依赖~~ ✅
8. ~~P0/P1/P2 性能优化（11项）~~ ✅

### 待完成
1. **P2 向量数据库升级（pgvector）**
   - 安装 PostgreSQL 扩展（需 DBA 权限）
   - 修改表结构，添加 vector 列
   - 迁移数据，创建 HNSW 索引
   - 修改代码，使用 pgvector 查询
   - 预期收益：检索性能 10x 提升（500ms → 50ms）

2. **前端优化**
   - 上传简历后自动刷新列表
   - 面试进行中实时状态轮询

3. **后续优化（P2）**
   - BM25 混合检索（长尾查询召回率 +20%）
   - 意图定向检索（精准度 +20%）
   - 模型路由与容错（可用性 95% → 99.5%）

### 快速启动
```bash
# 阅读核心文档
Read docs/下次会话快速启动指南.md
Read docs/优化实施记录.md

# 查看待完成任务
TaskList
```
