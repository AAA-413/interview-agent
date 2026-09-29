import hashlib
import json
import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_persistence_service import BasePersistenceService, safe_json_loads
from app.common.error_code import ErrorCode
from app.common.model import AsyncTaskStatus
from app.modules.resume.canonical.models import (
    RESUME_CANONICAL_SCHEMA_VERSION,
    ResumeCanonicalProfileDTO,
    ResumeCanonicalStatus,
    ResumeEvidenceRefDTO,
)
from app.modules.resume.models import ResumeAnalysisEntity, ResumeEntity
from app.modules.resume.schemas import (
    AnalysisHistoryDTO,
    ResumeAnalysisResponse,
    ResumeDetailDTO,
    ResumeListItemDTO,
    ResumeProfile,
    Suggestion,
)

logger = logging.getLogger(__name__)


class ResumePersistenceService(BasePersistenceService[ResumeEntity]):
    model = ResumeEntity
    not_found_error = ErrorCode.RESUME_NOT_FOUND

    async def find_by_file_hash(
        self, db: AsyncSession, file_hash: str, user_id: int | None = None
    ) -> ResumeEntity | None:
        query = select(ResumeEntity).where(ResumeEntity.file_hash == file_hash)
        if user_id is not None:
            query = query.where(ResumeEntity.user_id == user_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def exists_by_file_hash(self, db: AsyncSession, file_hash: str, user_id: int | None = None) -> bool:
        query = select(ResumeEntity.id).where(ResumeEntity.file_hash == file_hash)
        if user_id is not None:
            query = query.where(ResumeEntity.user_id == user_id)
        result = await db.execute(query)
        return result.scalar_one_or_none() is not None

    async def find_all(self, db: AsyncSession, user_id: int | None = None) -> list[ResumeEntity]:
        query = select(ResumeEntity).order_by(ResumeEntity.uploaded_at.desc())
        if user_id is not None:
            query = query.where(ResumeEntity.user_id == user_id)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def save_resume(self, db: AsyncSession, entity: ResumeEntity) -> ResumeEntity:
        return await self.save(db, entity)

    async def clear_analyses(self, db: AsyncSession, resume_id: int) -> None:
        await db.execute(delete(ResumeAnalysisEntity).where(ResumeAnalysisEntity.resume_id == resume_id))
        await db.flush()

    async def delete_resume(self, db: AsyncSession, resume_id: int) -> None:
        await self.clear_analyses(db, resume_id)
        await db.execute(delete(ResumeEntity).where(ResumeEntity.id == resume_id))
        await db.flush()

    async def update_analyze_status(
        self, db: AsyncSession, resume_id: int, status: AsyncTaskStatus, error: str | None = None
    ) -> None:
        entity = await self.find_by_id(db, resume_id)
        if entity:
            entity.analyze_status = status
            entity.analyze_error = error[:500] if error and len(error) > 500 else error
            await db.flush()

    async def save_analysis(
        self, db: AsyncSession, resume_id: int, analysis: ResumeAnalysisResponse
    ) -> ResumeAnalysisEntity:
        entity = ResumeAnalysisEntity(
            resume_id=resume_id,
            overall_score=analysis.overall_score,
            content_score=analysis.score_detail.content_score,
            structure_score=analysis.score_detail.structure_score,
            skill_match_score=analysis.score_detail.skill_match_score,
            expression_score=analysis.score_detail.expression_score,
            project_score=analysis.score_detail.project_score,
            summary=analysis.summary,
            strengths_json=json.dumps(analysis.strengths, ensure_ascii=False),
            suggestions_json=json.dumps([s.model_dump() for s in analysis.suggestions], ensure_ascii=False),
            profile_json=json.dumps(analysis.profile.model_dump(), ensure_ascii=False) if analysis.profile else None,
            analyzed_at=datetime.now(),
        )
        db.add(entity)
        await db.flush()
        return entity

    # ------------------------------------------------------------------
    # PR4：Canonical Resume 持久化
    # ------------------------------------------------------------------

    @staticmethod
    def canonical_source_hash(resume_text: str | None) -> str:
        """Canonical 的直接输入是 resume_text，因此用 text hash 而不是 file hash。"""
        return hashlib.sha256((resume_text or "").encode("utf-8")).hexdigest()

    @staticmethod
    def parse_canonical_profile(raw_json: str | None) -> ResumeCanonicalProfileDTO | None:
        """安全解析 canonical JSON。坏 JSON → None（不 500，调用方按 STALE 处理）。"""
        if not raw_json:
            return None
        try:
            payload = json.loads(raw_json)
        except (TypeError, ValueError):
            logger.warning("canonical_profile_json 解析失败，按 STALE 处理")
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return ResumeCanonicalProfileDTO.model_validate(payload)
        except Exception:
            logger.warning("canonical_profile_json 结构非法，按 STALE 处理")
            return None

    def canonical_is_fresh(self, entity: ResumeEntity, resume_text: str | None) -> bool:
        """canonical 可用 = JSON 可解析 + schema 版本匹配 + source hash 匹配。

        schema version **内外都校验**：列上的 ``canonical_schema_version`` 与 JSON
        内部的 ``profile.schema_version`` 都必须等于当前版本。只校验列会被
        「列=v1、JSON 内=old」绕过（手工改数据、跨版本残留等）。
        """
        profile = self.parse_canonical_profile(entity.canonical_profile_json)
        if profile is None:
            return False
        if profile.schema_version != RESUME_CANONICAL_SCHEMA_VERSION:
            return False
        if entity.canonical_schema_version != RESUME_CANONICAL_SCHEMA_VERSION:
            return False
        return entity.canonical_source_hash == self.canonical_source_hash(resume_text)

    def canonical_status(self, entity: ResumeEntity, resume_text: str | None = None) -> str:
        """Derived canonical status（不落 DB enum）。

        READY → 当前 canonical 可用；
        STALE → 有 canonical JSON 但 schema/hash 不匹配或 JSON 坏；
        FAILED → 没有可用 canonical 且记录过抽取错误；
        NOT_EXTRACTED → 其余。
        """
        text = resume_text if resume_text is not None else entity.resume_text
        if self.canonical_is_fresh(entity, text):
            return ResumeCanonicalStatus.READY.value
        if entity.canonical_profile_json:
            return ResumeCanonicalStatus.STALE.value
        if entity.canonical_extract_error:
            return ResumeCanonicalStatus.FAILED.value
        return ResumeCanonicalStatus.NOT_EXTRACTED.value

    async def save_canonical_profile(
        self,
        db: AsyncSession,
        resume_id: int,
        profile: ResumeCanonicalProfileDTO,
        source_hash: str,
    ) -> None:
        entity = await self.find_by_id(db, resume_id)
        if not entity:
            return
        entity.canonical_profile_json = json.dumps(profile.model_dump(), ensure_ascii=False)
        entity.canonical_schema_version = profile.schema_version
        entity.canonical_source_hash = source_hash
        entity.canonical_extract_error = None
        entity.canonical_extracted_at = datetime.now()
        await db.flush()

    async def save_canonical_error(self, db: AsyncSession, resume_id: int, error: str) -> None:
        entity = await self.find_by_id(db, resume_id)
        if not entity:
            return
        entity.canonical_extract_error = error[:500] if error and len(error) > 500 else error
        entity.canonical_extracted_at = datetime.now()
        await db.flush()

    @staticmethod
    def parse_resume_evidence_refs(raw_json: str | None) -> list[ResumeEvidenceRefDTO]:
        """安全解析 interview topic 上的 resume_evidence_refs。

        坏 JSON / 非法结构 → []（不 500），保证老 topic 与坏数据可用。
        """
        if not raw_json:
            return []
        try:
            payload = json.loads(raw_json)
        except (TypeError, ValueError):
            logger.warning("resume_evidence_refs_json 解析失败，按空处理")
            return []
        if not isinstance(payload, list):
            return []
        refs: list[ResumeEvidenceRefDTO] = []
        for item in payload:
            try:
                refs.append(ResumeEvidenceRefDTO.model_validate(item))
            except Exception:
                continue
        return refs

    async def find_analyses_by_resume_id(self, db: AsyncSession, resume_id: int) -> list[ResumeAnalysisEntity]:
        result = await db.execute(
            select(ResumeAnalysisEntity)
            .where(ResumeAnalysisEntity.resume_id == resume_id)
            .order_by(ResumeAnalysisEntity.analyzed_at.desc())
        )
        return list(result.scalars().all())

    async def find_latest_analysis(self, db: AsyncSession, resume_id: int) -> ResumeAnalysisEntity | None:
        result = await db.execute(
            select(ResumeAnalysisEntity)
            .where(ResumeAnalysisEntity.resume_id == resume_id)
            .order_by(ResumeAnalysisEntity.analyzed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def to_list_item_dto(self, entity: ResumeEntity) -> ResumeListItemDTO:
        latest = entity.analyses[0] if entity.analyses else None
        return ResumeListItemDTO(
            id=entity.id,
            filename=entity.original_filename,
            file_size=entity.file_size,
            uploaded_at=entity.uploaded_at,
            access_count=entity.access_count,
            latest_score=latest.overall_score if latest else None,
            last_analyzed_at=latest.analyzed_at if latest else None,
            interview_count=0,
            analyze_status=entity.analyze_status,
            analyze_error=entity.analyze_error,
        )

    def to_detail_dto(self, entity: ResumeEntity) -> ResumeDetailDTO:
        analyses = [self._to_analysis_history_dto(a) for a in entity.analyses]
        return ResumeDetailDTO(
            id=entity.id,
            filename=entity.original_filename,
            file_size=entity.file_size,
            content_type=entity.content_type,
            storage_url=entity.storage_url,
            uploaded_at=entity.uploaded_at,
            access_count=entity.access_count,
            resume_text=entity.resume_text,
            analyze_status=entity.analyze_status,
            analyze_error=entity.analyze_error,
            analyses=analyses,
            canonical_profile=self.parse_canonical_profile(entity.canonical_profile_json)
            if self.canonical_is_fresh(entity, entity.resume_text)
            else None,
            canonical_status=self.canonical_status(entity, entity.resume_text),
            canonical_schema_version=entity.canonical_schema_version,
            canonical_extract_error=entity.canonical_extract_error,
            canonical_extracted_at=entity.canonical_extracted_at,
        )

    @staticmethod
    def _to_analysis_history_dto(entity: ResumeAnalysisEntity) -> AnalysisHistoryDTO:
        strengths = safe_json_loads(entity.strengths_json, [])
        raw_suggestions = safe_json_loads(entity.suggestions_json, [])
        suggestions = [Suggestion(**s) for s in raw_suggestions] if raw_suggestions else []
        raw_profile = safe_json_loads(entity.profile_json, None)
        profile = ResumeProfile(**raw_profile) if raw_profile else None

        return AnalysisHistoryDTO(
            id=entity.id,
            overall_score=entity.overall_score,
            content_score=entity.content_score,
            structure_score=entity.structure_score,
            skill_match_score=entity.skill_match_score,
            expression_score=entity.expression_score,
            project_score=entity.project_score,
            summary=entity.summary,
            analyzed_at=entity.analyzed_at,
            strengths=strengths,
            suggestions=suggestions,
            profile=profile,
        )


resume_persistence_service = ResumePersistenceService()
