# 智能面试 Agent 平台 — Python 实现计划

## 总览

基于 Java 版 `interview-guide` 项目，使用 Python (FastAPI + LangChain + SQLAlchemy) 重新实现智能面试 Agent 平台。

---

## Phase 1 — 基础框架 ✅ 已完成

| # | 任务 | 状态 |
|---|------|------|
| 1.1 | 项目初始化：pyproject.toml + 依赖声明 + .venv 虚拟环境 | ✅ 已完成 |
| 1.2 | 配置管理：pydantic-settings + .env.example | ✅ 已完成 |
| 1.3 | FastAPI 应用入口 + 生命周期管理 | ✅ 已完成 |
| 1.4 | 统一响应模型 Result<T> | ✅ 已完成 |
| 1.5 | 统一异常处理 + 错误码 | ✅ 已完成 |
| 1.6 | 数据库：SQLAlchemy async engine + session | ✅ 已完成 |
| 1.7 | 数据库迁移：Alembic 初始化 | ✅ 已完成 |
| 1.8 | Redis 封装：redis-py async | ✅ 已完成 |
| 1.9 | CORS + OpenAPI 配置 | ✅ 已完成 |
| 1.10 | LLM Provider 注册表 + 结构化输出封装 | ✅ 已完成 |
| 1.11 | 健康检查接口验证框架可用 | ✅ 已完成 |

**验证结果**：`GET /api/health` 返回 `{"status": "UP", "service": "AI Interview Platform"}`

## Phase 2 — 简历管理模块 ✅ 已完成

| # | 任务 | 状态 |
|---|------|------|
| 2.1 | ORM 模型：ResumeEntity + ResumeAnalysisEntity | ✅ 已完成 |
| 2.2 | 文档解析服务（PDF/DOCX/TXT） | ✅ 已完成 |
| 2.3 | 文件存储服务（S3/MinIO） | ✅ 已完成 |
| 2.4 | 文件哈希去重 | ✅ 已完成 |
| 2.5 | 异步任务：Redis Stream 生产者/消费者 | ✅ 已完成 |
| 2.6 | 简历分析 Prompt + AI 调用 | ✅ 已完成 |
| 2.7 | 简历 CRUD API | ✅ 已完成 |
| 2.8 | PDF 报告导出 | ✅ 已完成 |

## Phase 3 — 模拟面试模块 ✅ 已完成

| # | 任务 | 状态 |
|---|------|------|
| 3.1 | ORM 模型：InterviewSession + InterviewAnswer | ✅ 已完成 |
| 3.2 | Skill 加载服务（解析 SKILL.md + skill.meta.yml） | ✅ 已完成 |
| 3.3 | 出题服务（Skill 驱动 + 简历题 + 历史去重） | ✅ 已完成 |
| 3.4 | 会话管理服务（Redis 缓存 + DB 持久化） | ✅ 已完成 |
| 3.5 | 统一评估引擎（分批评估 + 二次汇总 + 降级兜底） | ✅ 已完成 |
| 3.6 | 面试 CRUD API + 问答交互 | ✅ 已完成 |
| 3.7 | 面试报告 PDF 导出 | ✅ 已完成 |

**验证结果**：10 个预设 Skill 加载成功，26 个 API 路由注册成功

## Phase 4 — 知识库管理模块

| # | 任务 | 状态 |
|---|------|------|
| 4.1 | ORM 模型：KnowledgeBase + RagChat | ✅ 已完成 |
| 4.2 | 文档上传 + 分块 + 异步向量化 | ✅ 已完成 |
| 4.3 | RAG 查询服务（Query Rewrite + 向量检索 + SSE 流式） | ✅ 已完成 |
| 4.4 | 知识库 CRUD API | ✅ 已完成 |

## Phase 5 — 面试安排模块

| # | 任务 | 状态 |
|---|------|------|
| 5.1 | ORM 模型：InterviewSchedule | ⬜ 未开始 |
| 5.2 | 邀约解析服务（规则引擎 + AI 解析） | ⬜ 未开始 |
| 5.3 | 日程 CRUD + 状态流转 + 定时过期 | ⬜ 未开始 |
| 5.4 | 日程 API | ⬜ 未开始 |

## Phase 6 — 语音面试模块

| # | 任务 | 状态 |
|---|------|------|
| 6.1 | ORM 模型：VoiceInterviewSession + Message + Evaluation | ⬜ 未开始 |
| 6.2 | WebSocket 处理器 | ⬜ 未开始 |
| 6.3 | ASR/TTS 服务（DashScope WebSocket） | ⬜ 未开始 |
| 6.4 | 阶段流转 + 暂停/恢复 | ⬜ 未开始 |
| 6.5 | 语音面试 API | ⬜ 未开始 |

---

## 完成标记说明

- ⬜ 未开始
- 🔄 进行中
- ✅ 已完成
