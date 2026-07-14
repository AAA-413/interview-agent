# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Interview Platform (智能 AI 面试官平台) — a full-stack application using LLMs for resume analysis and simulated technical interviews. Python 3.11+, FastAPI backend + React 18 frontend.

## Git Workflow

**新功能先切到 develop 分支，不要直接在 main 上改。** 详细规范见 [`git-workflow.md`](git-workflow.md)（分支策略、commit 格式、合并策略）。要点速记：
- 永久分支：`main`（生产）、`develop`（集成）
- 功能分支：`feat/*`、`fix/*`、`refactor/*`、`chore/*` — 都从 develop 切出
- 热修例外：`hotfix/*` 从 main 切出，同时 merge 回 main + develop
- Commit 格式：`<type>(<scope>): <subject>`，例如 `feat(interview): 新增动态面试复盘`
- 功能分支合入 develop 用 `--no-ff` merge；功能分支同步 develop 用 rebase
- 发版：`develop` → `release/<version>` → `main`（`--no-ff` + tag）→ 同步回 develop

## Commands

### Backend (local dev)
```bash
pip install -r requirements.txt
cp .env.example .env    # then fill in API keys
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

### Frontend (local dev)
```bash
cd frontend
npm install
npm run dev     # Vite on :5173, proxies /api -> :8002
npm run build   # tsc && vite build -> dist/
```

### Docker
```bash
docker-compose up -d                            # Dev infra: pgvector, redis, minio
docker-compose -f docker-compose.prod.yml up -d # Full production stack
```

### Database migrations
```bash
alembic upgrade head
```

### Testing
```bash
pytest                           # async tests, asyncio_mode="auto"
pytest tests/test_quality_agent.py::TestClassName::test_method_name  # single test
python tests/e2e_smoke_test.py   # manual e2e smoke test (requires running backend)
```

### Linting
```bash
ruff check .                     # lint
ruff check . --fix               # auto-fix
ruff format .                    # format (line-length=120, target py311)
```

## Architecture

**Modular Monolith** with layered design. All API routes are under `/api/`.

```
app/
├── main.py                  # FastAPI entry, lifespan, middleware, router registration
├── config.py                # Pydantic Settings (Database, Redis, AI, Storage, CORS, etc.)
├── database.py              # SQLAlchemy async engine + session factory
├── models/base.py           # DeclarativeBase + TimestampMixin
├── common/                  # Shared: LLM layer, errors, exceptions, Result[T], prompt utils
│   ├── ai/                  # LlmProviderRegistry, MonitoredChatModel, StructuredOutputInvoker
│   ├── mcp/                 # MCP resource fetcher (web, search, github, arxiv)
│   └── tools/               # Search engines, GitHub API, document fetcher
├── infrastructure/          # Redis streams, MinIO/S3 storage, PDF export, doc parsing
└── modules/
    ├── auth/                # /api/auth — JWT auth, bcrypt, user CRUD
    ├── resume/              # /api/resumes — upload, AI grading, async analysis via Redis Streams
    ├── interview/           # /api/interview — sessions, AI questions, evaluation, reports
    ├── knowledge_base/      # /api/knowledgebase — RAG pipeline, pgvector, SSE streaming QA
    ├── knowledge_graph/     # /api/knowledge-graph — entity-relation triples, LLM extraction, GraphRAG
    └── agent_orchestration/ # /api/agent — multi-agent pipeline, smart download
```

### Key patterns
- **API response**: All endpoints return `Result[T]` wrapper (`app/common/result.py`) — frontend unwraps `.data` automatically via Axios interceptor
- **Async task queue**: Redis Streams with consumer groups (`xreadgroup`/`xack`). Three workers (resume analyze, interview evaluate, KB index) start in lifespan. Base classes: `StreamTaskProducer` (send) and `StreamTaskHandler` (receive/process) in `app/common/base_async_task.py`, with 5-minute timeout per task
- **Auth middleware**: global HTTP middleware validates JWT Bearer tokens on non-public paths, stores `user_id` in `request.state`
- **User data isolation**: all business tables have `user_id` FK; `BasePersistenceService[T]` filters by `user_id`
- **LLM integration**: LangChain `ChatOpenAI` wrapped in `MonitoredChatModel` (semaphore concurrency limit of 10), structured output via `PydanticOutputParser` with retry + repair prompts
- **Agent orchestration**: DecisionTree -> PlanningAgent -> ExecutionAgent(s) -> QualityAgent -> SummaryAgent pipeline
- **Knowledge graph**: PostgreSQL triple table (subject entity - predicate - object entity) with LLM-based entity/relation extraction; integrated into KB indexing pipeline; `graph_search_channel.py` provides GraphRAG hybrid retrieval (vector + graph traversal)

### Frontend (React + TypeScript + Vite)
- Tailwind CSS v4, React Router v7, lazy-loaded pages
- Axios client with JWT interceptor (`localStorage`) and `Result<T>` unwrapping
- Vite dev proxy: `/api` -> `http://localhost:8002`
- Pre-built production assets in `frontend/dist/`

## Database

PostgreSQL 16 with pgvector extension. Async via SQLAlchemy + asyncpg. Tables auto-created on startup via `Base.metadata.create_all`. Alembic for schema migrations.

Key tables: `users`, `resumes`, `resume_analyses`, `interview_sessions`, `interview_answers`, `knowledge_bases`, `knowledge_chunks` (pgvector `Vector(1536)`), `rag_chats`, `knowledge_entities`, `knowledge_triples`

## Skills System

Interview directions defined in `skills/<id>/` with:
- `SKILL.md` — YAML front matter + markdown persona content
- `skill.meta.yml` — display metadata and category-to-reference mappings
- `skills/_shared/references/` — shared reference docs per topic

## LLM Configuration

- Primary: DeepSeek (`deepseek-chat`) via OpenAI-compatible API
- Embedding: Zhipu Embedding-3 (2048-dim, truncated to 1536 for pgvector), DashScope fallback, hash-vector ultimate fallback
- Prompt templates: markdown files in `app/prompts/` — paired `*-system.md` / `*-user.md` for each use case

## Environment Variables

All config via `.env` file (Pydantic Settings). Key groups:
- `POSTGRES_*` — database connection
- `REDIS_*` — Redis connection
- `AI_*` — LLM provider (Bailian/DashScope API key, model, base_url, embedding)
- `APP_STORAGE_*` — MinIO/S3 object storage
- `CORS_ALLOWED_ORIGINS` — comma-separated allowed origins
- `APP_INTERVIEW_*` — interview settings (follow-up count, difficulty, batch size)
- `APP_RESUME_*` — resume upload limits
- `APP_VOICE_INTERVIEW_*` — voice interview config
- `GITHUB_TOKENS` — comma-separated GitHub PATs for rate limit distribution

## Conventions

- All business logic follows the pattern: `router.py` (API) -> `*_service.py` (logic) -> `persistence_service.py` (DB)
- Models defined per module (e.g., `modules/resume/models.py`), imported in `app/models/__init__.py` for Alembic discovery
- bcrypt pinned to `<4.1.0` due to passlib compatibility
