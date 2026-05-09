# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Interview Platform (智能 AI 面试官平台) — a full-stack application using LLMs for resume analysis and simulated technical interviews. Python 3.11+, FastAPI backend + React 18 frontend.

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
python tests/e2e_smoke_test.py   # manual e2e smoke test (requires running backend)
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
    └── agent_orchestration/ # /api/agent — multi-agent pipeline, smart download
```

### Key patterns
- **Async task queue**: Redis Streams with consumer groups (`xreadgroup`/`xack`), three workers for resume analysis, interview evaluation, and KB indexing
- **Auth middleware**: global HTTP middleware validates JWT Bearer tokens on non-public paths, stores `user_id` in `request.state`
- **User data isolation**: all business tables have `user_id` FK; `BasePersistenceService[T]` filters by `user_id`
- **LLM integration**: LangChain `ChatOpenAI` wrapped in `MonitoredChatModel` (semaphore concurrency limit of 10), structured output via `PydanticOutputParser` with retry + repair prompts
- **Agent orchestration**: DecisionTree -> PlanningAgent -> ExecutionAgent(s) -> QualityAgent -> SummaryAgent pipeline

### Frontend (React + TypeScript + Vite)
- Tailwind CSS v4, React Router v7, lazy-loaded pages
- Axios client with JWT interceptor (`localStorage`) and `Result<T>` unwrapping
- Vite dev proxy: `/api` -> `http://localhost:8002`
- Pre-built production assets in `frontend/dist/`

## Database

PostgreSQL 16 with pgvector extension. Async via SQLAlchemy + asyncpg. Tables auto-created on startup via `Base.metadata.create_all`. Alembic for schema migrations.

Key tables: `users`, `resumes`, `resume_analyses`, `interview_sessions`, `interview_answers`, `knowledge_bases`, `knowledge_chunks` (pgvector `Vector(1536)`), `rag_chats`

## Skills System

Interview directions defined in `skills/<id>/` with:
- `SKILL.md` — YAML front matter + markdown persona content
- `skill.meta.yml` — display metadata and category-to-reference mappings
- `skills/_shared/references/` — shared reference docs per topic

## LLM Configuration

- Primary: DeepSeek (`deepseek-chat`) via OpenAI-compatible API
- Embedding: Zhipu Embedding-3 (2048-dim, truncated to 1536 for pgvector), DashScope fallback, hash-vector ultimate fallback
- Prompt templates: markdown files in `app/prompts/`
