import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.common.base_async_task import StreamTaskHandler, StreamTaskProducer
from app.common.model import AsyncTaskStatus
from app.config import settings
from app.infrastructure.redis.redis_service import RedisService
from app.modules.resume.canonical.extractor import resume_canonical_extractor
from app.modules.resume.canonical.validator import resume_canonical_validator
from app.modules.resume.grading_service import resume_grading_service
from app.modules.resume.persistence_service import resume_persistence_service

logger = logging.getLogger(__name__)

RESUME_ANALYZE_STREAM_KEY = "resume:analyze:stream"
FIELD_RESUME_ID = "resumeId"


class AnalyzeStreamProducer(StreamTaskProducer):
    def __init__(self, redis_service: RedisService):
        super().__init__(redis_service, RESUME_ANALYZE_STREAM_KEY)

    async def send_analyze_task(self, resume_id: int) -> None:
        await self.send_task({FIELD_RESUME_ID: str(resume_id)})


class ResumeAnalyzeTaskHandler(StreamTaskHandler):
    """简历分析任务。

    PR4 起任务内有两个 LLM 调用（Canonical Extractor + Resume Grading），
    **绝不能让一个 DB transaction 跨两个模型调用**。因此 process() 自己划分短事务：

    ```text
    R0  DB：载入 resume_text 快照 + 计算 source hash + 读 freshness → commit（释放事务）
    R1  Canonical Extractor LLM：无 DB transaction
    R2  短 DB transaction：persist canonical（成功或错误）→ commit
    R3  Resume Grading LLM：无 DB transaction
    R4  短 DB transaction：clear 旧 analyses + save 新 analysis → commit
    ```

    这里只在本 handler 内做 snapshot / commit / 外部调用 / 短持久化，
    **不修改通用 StreamTaskHandler 语义**，其它 Redis Stream Task 不受影响。

    旧 analysis 的删除必须在 grading **成功之后**才发生（§32）：
    grading 抛错时 R4 根本不会执行，旧记录与已提交的 canonical 都保留。
    """

    @property
    def field_name(self) -> str:
        return FIELD_RESUME_ID

    async def update_status(
        self, db: AsyncSession, key_value: str, status: AsyncTaskStatus, error: str | None = None
    ) -> None:
        await resume_persistence_service.update_analyze_status(db, int(key_value), status, error)

    async def process(self, db: AsyncSession, key_value: str) -> None:
        resume_id = int(key_value)

        # ---------------- Phase R0：短事务，取不可变快照后释放 ----------------
        entity = await resume_persistence_service.find_by_id_or_throw(db, resume_id)
        if not entity.resume_text:
            await resume_persistence_service.update_analyze_status(
                db, resume_id, AsyncTaskStatus.FAILED, "简历文本为空，无法分析"
            )
            return

        resume_text = entity.resume_text  # immutable snapshot：后续不再依赖 ORM 状态
        source_hash = resume_persistence_service.canonical_source_hash(resume_text)
        canonical_enabled = settings.resume.canonical_extractor_enabled
        # freshness 必须在 commit 前读完（commit 后 ORM 属性会 expire，再读会触发新的 IO）
        canonical_fresh = resume_persistence_service.canonical_is_fresh(entity, resume_text)
        if canonical_enabled and canonical_fresh:
            logger.info("简历 canonical 仍为最新，跳过抽取: resumeId=%d", resume_id)
        await db.commit()

        # ---------------- Phase R1：Canonical Extractor LLM（无 DB transaction） ----------------
        if canonical_enabled and not canonical_fresh:
            chat_model = llm_registry.default
            try:
                raw = await asyncio.wait_for(
                    resume_canonical_extractor.extract(chat_model, resume_text),
                    timeout=settings.resume.canonical_extractor_timeout_seconds,
                )
                profile = resume_canonical_validator.build(raw, resume_text)
                # ---------------- Phase R2：短事务 persist canonical ----------------
                await resume_persistence_service.save_canonical_profile(db, resume_id, profile, source_hash)
                await db.commit()
                logger.info(
                    "简历 canonical 抽取完成: resumeId=%d, projects=%d, skills=%d",
                    resume_id,
                    len(profile.projects),
                    len(profile.skills),
                )
            except Exception as e:
                # Canonical 失败是独立 failure domain：记错误，绝不影响后续 grading
                logger.warning("简历 canonical 抽取失败（grading 继续）: resumeId=%d, error=%s", resume_id, e)
                # asyncio.TimeoutError 的 str() 是空串，空串会让 canonical_status
                # 误判成 NOT_EXTRACTED，因此这里回退到异常类名。
                await resume_persistence_service.save_canonical_error(db, resume_id, str(e) or e.__class__.__name__)
                await db.commit()

        # ---------------- Phase R3：Resume Grading LLM（无 DB transaction） ----------------
        chat_model = llm_registry.default
        result = await resume_grading_service.analyze_resume(chat_model, resume_text)

        # ---------------- Phase R4：短事务，grading 成功后再替换旧 analysis ----------------
        # clear + save 必须在同一事务里，且必须在 grading 之后：
        # grading 抛错时 R4 不执行 → 旧 analysis 保留（不会被提前删掉）。
        await resume_persistence_service.clear_analyses(db, resume_id)
        await resume_persistence_service.save_analysis(db, resume_id, result)
        await db.commit()
        logger.info("简历分析完成: resumeId=%d, 总分=%d", resume_id, result.overall_score)
