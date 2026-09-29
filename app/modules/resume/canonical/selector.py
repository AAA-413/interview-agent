"""Resume Evidence Selector —— 确定性选择与当前 project/topic 相关的简历事实。

职责边界
--------
Selector 只能：

```text
筛选 / 排序 / 去重 / 截断
```

Selector **不能**：

```text
总结 / 改写 / 推断 / 查 DB / 调 LLM / embedding / RAG
```

``rendered_text`` 只是 UI / prompt 兼容用的展示串，真正的 provenance 是 ``refs``
（claim_id + 原始 source quote）。rendered_text 完全由被选中的 refs 的 quote
deterministic 拼接而成，**绝不混入 LLM 重写值**。
"""

from __future__ import annotations

from app.modules.interview.evaluation.models import normalize_evidence_text
from app.modules.resume.canonical.models import (
    ENTITY_TYPE_PROJECT,
    MAX_EVIDENCE_REFS,
    MAX_RENDERED_TEXT_CHARS,
    ResumeCanonicalClaimDTO,
    ResumeCanonicalProfileDTO,
    ResumeCanonicalProjectDTO,
    ResumeEvidenceBundleDTO,
    ResumeEvidenceRefDTO,
)

#: claim_type → 优先级（数字越小越优先）
_CLAIM_TYPE_PRIORITY: dict[str, int] = {
    "ROLE": 2,
    "METRIC": 3,
    "RESPONSIBILITY": 4,
    "ACHIEVEMENT": 5,
    "TECHNOLOGY": 6,
    "NAME": 7,
    "DATE_RANGE": 8,
}

_DEFAULT_PRIORITY = 9


class ResumeEvidenceSelector:
    """把 canonical project 里的事实确定性地选成一个 evidence bundle。"""

    def for_project(
        self,
        profile: ResumeCanonicalProfileDTO,
        project: ResumeCanonicalProjectDTO,
        *,
        topic_key: str | None = None,
        skill_key: str | None = None,
        keywords: tuple[str, ...] | None = None,
    ) -> ResumeEvidenceBundleDTO:
        keyword_set = self._keyword_set(topic_key, skill_key, keywords)
        candidates: list[tuple[int, int, int, ResumeEvidenceRefDTO]] = []

        for order, (claim_type, claim) in enumerate(self._project_claims(project)):
            ref = self._ref(ENTITY_TYPE_PROJECT, project.project_id, claim_type, claim)
            match_rank = 0 if self._matches(claim, keyword_set) else 1
            priority = _CLAIM_TYPE_PRIORITY.get(claim_type, _DEFAULT_PRIORITY)
            candidates.append((match_rank, priority, order, ref))

        # 一级：是否命中 topic/skill 关键词；二级：claim_type 优先级；
        # 三级：实体内的自然顺序（保证完全 deterministic）
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3].claim_id))
        refs = self._dedup([item[3] for item in candidates])[:MAX_EVIDENCE_REFS]
        return ResumeEvidenceBundleDTO(refs=refs, rendered_text=self._render(refs))

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _project_claims(project: ResumeCanonicalProjectDTO) -> list[tuple[str, ResumeCanonicalClaimDTO]]:
        pairs: list[tuple[str, ResumeCanonicalClaimDTO]] = []
        if project.name is not None:
            pairs.append(("NAME", project.name))
        if project.role is not None:
            pairs.append(("ROLE", project.role))
        if project.date_range is not None:
            pairs.append(("DATE_RANGE", project.date_range))
        for claim in project.metrics:
            pairs.append(("METRIC", claim))
        for claim in project.responsibilities:
            pairs.append(("RESPONSIBILITY", claim))
        for claim in project.achievements:
            pairs.append(("ACHIEVEMENT", claim))
        for claim in project.technologies:
            pairs.append(("TECHNOLOGY", claim))
        return pairs

    @staticmethod
    def _keyword_set(topic_key: str | None, skill_key: str | None, keywords: tuple[str, ...] | None) -> frozenset[str]:
        raw: list[str] = []
        if topic_key:
            raw.extend(part for part in str(topic_key).replace("-", "_").split("_") if len(part) > 2)
        if skill_key:
            raw.extend(part for part in str(skill_key).replace("-", "_").split("_") if len(part) > 2)
        raw.extend(item for item in keywords or () if item and len(item) > 2)
        return frozenset(normalize_evidence_text(item) for item in raw)

    @staticmethod
    def _matches(claim: ResumeCanonicalClaimDTO, keyword_set: frozenset[str]) -> bool:
        if not keyword_set:
            return False
        normalized_value = normalize_evidence_text(claim.value)
        return any(keyword in normalized_value for keyword in keyword_set)

    @staticmethod
    def _ref(entity_type: str, entity_id: str, claim_type: str, claim: ResumeCanonicalClaimDTO) -> ResumeEvidenceRefDTO:
        # quote / 行号直接取自已校验的 source span，绝不重新生成
        span = claim.evidence_spans[0]
        return ResumeEvidenceRefDTO(
            claim_id=claim.claim_id,
            entity_type=entity_type,  # type: ignore[arg-type]
            entity_id=entity_id,
            claim_type=claim_type,
            value=claim.value,
            quote=span.quote,
            start_line=span.start_line,
            end_line=span.end_line,
        )

    @staticmethod
    def _dedup(refs: list[ResumeEvidenceRefDTO]) -> list[ResumeEvidenceRefDTO]:
        seen: set[str] = set()
        result: list[ResumeEvidenceRefDTO] = []
        for ref in refs:
            if ref.claim_id in seen:
                continue
            seen.add(ref.claim_id)
            result.append(ref)
        return result

    @staticmethod
    def _render(refs: list[ResumeEvidenceRefDTO]) -> str:
        """由选中 refs 的 source quote deterministic 拼接，不做任何总结或改写。"""
        parts: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            quote = ref.quote.strip()
            if not quote or quote in seen:
                continue
            candidate = "；".join([*parts, quote]) if parts else quote
            if len(candidate) > MAX_RENDERED_TEXT_CHARS:
                if not parts:
                    # 单条就超限时截断，保证不返回空串
                    return quote[:MAX_RENDERED_TEXT_CHARS]
                break
            seen.add(quote)
            parts.append(quote)
        return "；".join(parts)[:MAX_RENDERED_TEXT_CHARS]


resume_evidence_selector = ResumeEvidenceSelector()
