# Python 项目目录结构与核心模块关系分析

更新时间：2026-04-17

## 1. 项目整体结构

```text
python/
├── PLAN.md                  # 分阶段开发计划
├── PROGRESS.md              # 当前进度、已解决问题、启动方式
├── README.md                # 项目功能总览
├── docker-compose.yml       # PostgreSQL / Redis / MinIO 基础设施
├── pyproject.toml           # Python 项目依赖
├── alembic/                 # 数据库迁移
├── app/                     # FastAPI 后端主代码
│   ├── main.py              # 应用入口、生命周期、路由注册
│   ├── config.py            # 配置中心（数据库/Redis/AI/CORS/存储）
│   ├── database.py          # SQLAlchemy async engine + session
│   ├── common/              # 通用能力：Result、异常、错误码、AI 封装
│   ├── infrastructure/      # 基础设施能力：文件、导出、Redis
│   ├── models/              # Base 等通用模型
│   └── modules/             # 业务模块
│       ├── resume/          # 简历管理（已完成）
│       ├── interview/       # 模拟面试（已完成）
│       ├── knowledge_base/  # 知识库（路由占位，未实现）
│       ├── interview_schedule/ # 面试安排（路由占位，未实现）
│       └── voice_interview/ # 语音面试（目录占位）
├── frontend/                # React + Vite 前端
│   ├── src/
│   │   ├── api/             # Axios 请求封装与接口层
│   │   ├── components/      # 布局组件
│   │   ├── pages/           # 页面组件
│   │   ├── types/           # TS DTO 类型定义
│   │   ├── App.tsx          # 路由入口
│   │   └── main.tsx         # 前端入口
├── skills/                  # Skill 定义与参考知识库
└── docs/
    ├── llm-streaming-issue-analysis.md
    └── onboarding/          # 本次新增：上手分析文档目录
```

---

## 2. 后端核心模块关系

### 2.1 应用入口层

### `app/main.py`
职责：
- 创建 FastAPI 应用
- 初始化数据库和 Redis
- 注册异常处理
- 注册业务路由
- 暴露健康检查 `/api/health`

当前注册路由：
- `/api/resumes` → 简历管理
- `/api/interview` → 模拟面试
- `/api/interview/skills` → 面试方向/Skill
- `/api/interview-schedule` → 面试安排（当前空实现）
- `/api/knowledgebase` → 知识库（当前空实现）

说明：
知识库和面试安排模块已经接入主应用，但实际 router 还是占位，因此接口层面已预留扩展点。

### `app/config.py`
职责：统一配置中心。

配置分组：
- `DatabaseSettings`
- `RedisSettings`
- `AiSettings`
- `StorageSettings`
- `CorsSettings`
- `InterviewSettings`
- `ResumeSettings`
- `VoiceInterviewSettings`

作用：
项目几乎所有基础设施能力都从这里读配置，是后续扩展新模块时最先要看的地方。

### `app/database.py`
职责：
- 构建 SQLAlchemy async engine
- 提供 `get_db()` 依赖注入
- 启动时初始化表
- 增加数据库端口检测与超时保护

关键特征：
- 如果 PostgreSQL 不可用，不会直接把整个服务卡死
- 使用 async session factory
- 在 `get_db()` 中统一 commit / rollback

---

## 3. common 与 infrastructure 分层

### 3.1 `app/common/`
用于放跨业务通用能力。

关键文件：
- `result.py`：统一响应模型 `Result<T>`
- `exception.py` / `exception_handlers.py`：业务异常与全局异常处理
- `error_code.py`：统一错误码
- `model.py`：通用枚举/模型
- `common/ai/llm_provider.py`：LLM Provider 注册中心
- `common/ai/structured_output.py`：结构化输出封装
- `common/ai/prompt_template.py`：Prompt 相关封装

### 3.2 `app/infrastructure/`
负责偏“外部资源接入”的能力。

子目录：
- `file/`
  - `document_parse_service.py`：文档解析 PDF/DOCX/TXT
  - `file_storage_service.py`：文件上传到 MinIO/S3
  - `file_hash_service.py`：内容哈希
  - `file_validation_service.py`：上传校验
- `export/`
  - `pdf_export_service.py`：PDF 导出
- `redis/`
  - `redis_service.py`：Redis 初始化与封装

理解方式：
- `common` 偏“通用规则/框架能力”
- `infrastructure` 偏“与外部系统交互的技术实现”

---

## 4. 业务模块结构

项目采用 `modules/<domain>/` 的按领域拆分方式。

### 4.1 简历模块 `app/modules/resume/`（已完成）

关键文件：
- `models.py`：简历与分析结果 ORM
- `schemas.py`：接口 DTO
- `router.py`：对外 API
- `upload_service.py`：上传、解析、存储、分析主流程
- `grading_service.py`：AI 简历评分
- `history_service.py`：列表/详情查询
- `persistence_service.py`：数据库读写封装
- `delete_service.py`：删除逻辑
- `async_tasks.py`：早期异步任务相关，现主流程已偏同步

核心调用链：
```text
router.py
  -> upload_service.py
      -> file_validation_service
      -> file_hash_service
      -> file_storage_service
      -> document_parse_service
      -> resume_persistence_service
      -> resume_grading_service
      -> llm_registry.default
```

当前业务特点：
- 上传简历后直接同步分析
- 状态流转：`PENDING -> PROCESSING -> COMPLETED/FAILED`
- 支持列表、详情、删除、重新分析、PDF 导出

重点注意：
虽然有 `async_tasks.py`，但根据当前文档与 `upload_service.py` 的实现，主流程已经从 Redis Stream 异步消费改成同步执行。

### 4.2 模拟面试模块 `app/modules/interview/`（已完成）

关键文件：
- `models.py`：面试会话/答案 ORM
- `schemas.py`：接口 DTO
- `router.py`：会话 API
- `skill_router.py`：Skill 查询与 JD 解析 API
- `skill_service.py`：Skill 加载、参考资料拼装、JD 解析
- `question_service.py`：生成题目
- `session_service.py`：会话生命周期管理
- `evaluation_service.py`：统一评估引擎
- `history_service.py`：历史详情与导出
- `persistence_service.py`：DB 访问
- `async_tasks.py`：评估任务生产逻辑相关

核心调用链：
```text
router.py
  -> session_service.py
      -> interview_persistence_service
      -> llm_registry.get_chat_model()
      -> question_service.py
      -> skill_service.py
      -> evaluation_service.py
```

模块职责拆分：
- `skill_service.py`：从 `python/skills/` 加载预设 Skill，并支持 JD 解析生成自定义面试方向
- `question_service.py`：根据 skill/difficulty/resume/JD 生成题目
- `session_service.py`：创建会话、提交答案、推进索引、完成会话、生成报告
- `evaluation_service.py`：面试完成后生成结构化评估结果

重点注意：
- 面试问题生成走同步调用
- 面试评估入口仍保留了 Redis 入队逻辑
- 但报告接口 `generate_report()` 也支持直接按当前答案重新计算报告

### 4.3 知识库模块 `app/modules/knowledge_base/`（未实现）

当前文件：
- `router.py`
- `rag_router.py`

现状：
- 两个 router 都只有 `APIRouter()`，还没有实际接口
- 但主应用已注册路由前缀，说明框架接入位置已预留

后续实现通常会补这些内容：
- ORM：KnowledgeBase / RagChat
- 上传与分块服务
- 向量化服务
- RAG 检索与对话服务
- CRUD 与 SSE 接口

### 4.4 面试安排模块 `app/modules/interview_schedule/`（未实现）

当前仅有：
- `router.py`

现状：
- 已注册路由，但无业务逻辑

### 4.5 语音面试模块 `app/modules/voice_interview/`（目录占位）

现状：
- 目前只有包目录
- 尚未看到 models/router/service 代码

---

## 5. Skill 体系与题库来源

### 目录：`python/skills/`

这是模拟面试模块的重要输入源。

结构包括：
- 各类面试方向目录，如：
  - `java-backend`
  - `python-backend`
  - `frontend`
  - `algorithm`
  - `system-design`
  - `ai-agent-dev`
- 每个方向通常包含：
  - `SKILL.md`
  - `skill.meta.yml`
- `_shared/references/` 下存放共享参考知识文档

`skill_service.py` 会：
- 扫描 `skills/` 目录
- 解析 `SKILL.md` front matter
- 读取 `skill.meta.yml`
- 组装为 `SkillDTO`
- 构建 category → reference 的映射
- 为出题/评估拼接参考上下文

因此这套系统的“题目风格”和“评估基线”很大程度由 `skills/` 驱动，而不是硬编码在 Python 业务代码里。

---

## 6. 前端目录结构与模块关系

### 6.1 路由层

#### `frontend/src/App.tsx`
当前路由：
- `/resumes`
- `/resumes/:resumeId`
- `/upload`
- `/interviews`
- `/interviews/:sessionId`
- `/interview-hub`
- `/interview`

特点：
- 根路由使用 `Layout`
- 子页面通过 `Outlet` 渲染
- 页面按需加载（LazyPage）

#### `frontend/src/components/Layout.tsx`
职责：
- 左侧导航栏
- 当前页面高亮
- `Outlet` 渲染子路由内容

当前导航项只有：
- 简历管理
- 上传简历
- 面试记录
- 开始面试

这也说明：
前端尚未接入知识库、面试安排、语音面试的页面入口。

### 6.2 API 层

#### `frontend/src/api/request.ts`
职责：
- Axios 实例封装
- 统一超时
- 响应拦截器自动解包后端 `Result<T>`
- 错误统一转成 `Error`

关键点：
- 没有硬编码 baseURL
- 依赖 Vite 代理把 `/api` 转发到 8001

#### `frontend/src/api/resume.ts`
封装：
- 简历列表
- 简历详情
- 上传
- 删除
- 重新分析
- PDF 导出

#### `frontend/src/api/interview.ts`
封装：
- 面试会话列表
- 创建会话
- 获取当前问题
- 提交答案/暂存答案
- 完成面试
- 获取报告/详情
- 查未完成会话
- 删除
- 导出 PDF

#### `frontend/src/api/skill.ts`
封装面试方向与 JD 解析相关接口。

### 6.3 页面层

已存在页面：
- `ResumeListPage.tsx`
- `ResumeDetailPage.tsx`
- `UploadPage.tsx`
- `InterviewHistoryPage.tsx`
- `InterviewDetailPage.tsx`
- `InterviewHubPage.tsx`
- `InterviewPage.tsx`

结构上已经形成了比较完整的“列表页 / 详情页 / 操作页”模式，可直接复用于后续知识库或面试安排模块。

---

## 7. 当前模块关系图（简版）

```text
前端页面
  -> frontend/src/api/*.ts
    -> /api/... HTTP 请求
      -> app/modules/*/router.py
        -> 各业务 service
          -> persistence_service / infrastructure / common.ai
            -> PostgreSQL / Redis / MinIO / LLM
```

更细一点：

```text
React Page
  -> API 封装（Axios）
    -> FastAPI Router
      -> Domain Service
        -> Persistence Service
        -> File / Redis / Export / AI Infrastructure
          -> DB / Redis / Object Storage / LLM
```

---

## 8. 当前代码状态判断

### 已经成熟稳定的部分
- 简历上传与分析主链路
- 模拟面试出题与会话交互
- 基础前端页面与路由
- 技能系统加载
- 统一响应和错误处理

### 仍属“预留框架”的部分
- 知识库管理
- 面试安排
- 语音面试

### 工程上值得注意的现实
- `README.md` 中描述了一些尚未真正落地的能力，和 `PROGRESS.md` / 实际代码相比要以代码现状为准
- 简历分析目前是同步执行，不再是 README 描述的完整异步流
- 知识库与面试安排虽然写进了主路由，但基本还是空壳

---

## 9. 后续最推荐的开发切入点

### 方向 A：继续主线功能开发
优先做 `knowledge_base` 模块。

原因：
- `PLAN.md` 中下一个 Phase 就是它
- 主应用已预留路由
- 前后端目前还没有相关 UI/服务实现，适合完整增量开发

建议切入顺序：
1. 设计 ORM 与 schema
2. 先做 CRUD 和文档上传
3. 再做分块/向量化
4. 最后补 RAG/SSE

### 方向 B：补现有用户体验
- 上传后自动刷新简历列表
- 面试中状态轮询
- 报告生成状态反馈
- 错误提示优化

### 方向 C：补异步架构一致性
- 把简历分析恢复成真正后台任务
- 梳理 interview 评估任务的入队与消费闭环

---

## 10. 建议继续阅读的代码入口

如果后续要继续深入，我建议按下面顺序读：

1. `app/main.py`
2. `app/config.py`
3. `app/database.py`
4. `app/modules/resume/upload_service.py`
5. `app/modules/resume/persistence_service.py`
6. `app/modules/interview/session_service.py`
7. `app/modules/interview/question_service.py`
8. `app/modules/interview/evaluation_service.py`
9. `app/modules/interview/skill_service.py`
10. `frontend/src/App.tsx`
11. `frontend/src/api/request.ts`
12. `frontend/src/pages/*`

---

## 11. 本次新增文档说明

本分析文档保存位置：
- `python/docs/onboarding/python-project-structure-analysis.md`

用途：
- 新对话快速接手
- 后续 Phase 4 开发前的结构参考
- 作为代码阅读导航文档
