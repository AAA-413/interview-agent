import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import async_session_factory, close_db, init_db
from app.common.exception_handlers import register_exception_handlers
from app.infrastructure.redis.redis_service import RedisService, close_redis, init_redis
from app.infrastructure.redis.stream_worker import StreamWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_tasks: list[asyncio.Task] = []
    workers: list[StreamWorker] = []

    logger.info("正在初始化数据库...")
    try:
        await init_db()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.warning("数据库初始化失败（服务仍可启动）: %s", e)

    logger.info("正在连接 Redis...")
    try:
        redis = await init_redis()
        app.state.redis = redis
        logger.info("Redis 连接成功")

        if redis is not None and async_session_factory is not None:
            from app.modules.interview.async_tasks import (
                EVALUATE_STREAM_KEY,
                InterviewEvaluateTaskHandler,
            )
            from app.modules.knowledge_base.async_tasks import (
                KNOWLEDGE_BASE_INDEX_STREAM_KEY,
                KnowledgeBaseIndexTaskHandler,
            )
            from app.modules.resume.async_tasks import (
                RESUME_ANALYZE_STREAM_KEY,
                ResumeAnalyzeTaskHandler,
            )

            redis_service = RedisService(redis)

            resume_worker = StreamWorker(
                name="resume-analyze-worker",
                redis_service=redis_service,
                stream_key=RESUME_ANALYZE_STREAM_KEY,
                handler=ResumeAnalyzeTaskHandler(async_session_factory).handle,
            )
            interview_worker = StreamWorker(
                name="interview-evaluate-worker",
                redis_service=redis_service,
                stream_key=EVALUATE_STREAM_KEY,
                handler=InterviewEvaluateTaskHandler(async_session_factory).handle,
            )
            knowledge_base_worker = StreamWorker(
                name="knowledge-base-index-worker",
                redis_service=redis_service,
                stream_key=KNOWLEDGE_BASE_INDEX_STREAM_KEY,
                handler=KnowledgeBaseIndexTaskHandler(async_session_factory).handle,
            )

            workers.extend([resume_worker, interview_worker, knowledge_base_worker])
            worker_tasks.extend(
                [
                    asyncio.create_task(resume_worker.run_forever(), name="resume-analyze-worker"),
                    asyncio.create_task(interview_worker.run_forever(), name="interview-evaluate-worker"),
                    asyncio.create_task(knowledge_base_worker.run_forever(), name="knowledge-base-index-worker"),
                ]
            )
            logger.info("异步任务 worker 已启动: %d 个", len(worker_tasks))
        else:
            logger.warning("Redis 或数据库会话工厂不可用，跳过异步 worker 启动")
    except Exception as e:
        logger.warning("Redis 连接失败（服务仍可启动）: %s", e)
        app.state.redis = None

    logger.info("应用启动完成")
    yield

    for worker in workers:
        worker.stop()
    for task in worker_tasks:
        task.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    try:
        await close_redis()
    except Exception:
        pass

    try:
        await close_db()
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    _register_routers(app)

    @app.get("/api/health")
    async def health_check():
        return {"status": "UP", "service": settings.app_name}

    return app


def _register_routers(app: FastAPI) -> None:
    from app.modules.resume.router import router as resume_router
    from app.modules.interview.router import router as interview_router
    from app.modules.interview.skill_router import router as skill_router
    from app.modules.interview_schedule.router import router as schedule_router
    from app.modules.knowledge_base.router import router as kb_router
    from app.modules.knowledge_base.rag_router import router as rag_router

    app.include_router(resume_router, prefix="/api/resumes", tags=["简历管理"])
    app.include_router(interview_router, prefix="/api/interview", tags=["模拟面试"])
    app.include_router(skill_router, prefix="/api/interview/skills", tags=["面试方向"])
    app.include_router(schedule_router, prefix="/api/interview-schedule", tags=["面试安排"])
    app.include_router(kb_router, prefix="/api/knowledgebase", tags=["知识库管理"])
    app.include_router(rag_router, prefix="/api/knowledgebase", tags=["知识库问答"])


app = create_app()
