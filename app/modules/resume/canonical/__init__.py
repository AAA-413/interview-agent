"""Resume Canonical 模块出口。

Canonical Resume 是 **resume domain artifact**，不是 interview-specific artifact，
因此独立成模块，不塞进 ``grading_service.py``，也不放进 interview 模块。

职责分工：

```text
Document Parser        文件 → 文本
Canonical Extractor    文本 → 候选 claim + source quote（LLM）
Canonical Validator    quote 是否真存在 / value 是否被支持 / span / id / dedup（代码）
Canonical Profile      保存 source-grounded resume facts
Evidence Selector      确定性选出与当前 project/topic 相关的事实
```

边界：Canonical 只证明「简历原文确实写了这句」，
**不证明**候选人写的内容在现实中为真。

关于惰性导出（PEP 562）
----------------------
``validator`` 会复用 PR2 的 ``normalize_evidence_text``，即依赖
``app.modules.interview.evaluation.models`` → ``app.modules.interview.schemas``；
而 ``interview.schemas`` 又要引用本模块的 ``ResumeEvidenceRefDTO``。
若在 ``__init__`` 里**立即**导入 validator，就会形成
``interview.schemas → resume.canonical → validator → interview.schemas`` 的循环。

因此这里只立即导出 **无 interview 依赖** 的 ``models``，
validator / extractor / selector 改为首次访问时惰性导入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.modules.resume.canonical.models import (
    MAX_EVIDENCE_REFS,
    MAX_RENDERED_TEXT_CHARS,
    RESUME_CANONICAL_SCHEMA_VERSION,
    RawCertificationDTO,
    RawEducationDTO,
    RawExperienceDTO,
    RawProjectDTO,
    RawResumeCanonicalDTO,
    RawSkillDTO,
    RawSourceBackedValue,
    ResumeCanonicalCertificationDTO,
    ResumeCanonicalClaimDTO,
    ResumeCanonicalEducationDTO,
    ResumeCanonicalExperienceDTO,
    ResumeCanonicalProfileDTO,
    ResumeCanonicalProjectDTO,
    ResumeCanonicalSkillDTO,
    ResumeCanonicalStatus,
    ResumeEvidenceBundleDTO,
    ResumeEvidenceRefDTO,
    ResumeEvidenceSpanDTO,
)

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查
    from app.modules.resume.canonical.extractor import ResumeCanonicalExtractor, resume_canonical_extractor
    from app.modules.resume.canonical.selector import ResumeEvidenceSelector, resume_evidence_selector
    from app.modules.resume.canonical.validator import ResumeCanonicalValidator, resume_canonical_validator

__all__ = [
    "MAX_EVIDENCE_REFS",
    "MAX_RENDERED_TEXT_CHARS",
    "RESUME_CANONICAL_SCHEMA_VERSION",
    "RawCertificationDTO",
    "RawEducationDTO",
    "RawExperienceDTO",
    "RawProjectDTO",
    "RawResumeCanonicalDTO",
    "RawSkillDTO",
    "RawSourceBackedValue",
    "ResumeCanonicalClaimDTO",
    "ResumeCanonicalEducationDTO",
    "ResumeCanonicalExperienceDTO",
    "ResumeCanonicalExtractor",
    "ResumeCanonicalProfileDTO",
    "ResumeCanonicalProjectDTO",
    "ResumeCanonicalCertificationDTO",
    "ResumeCanonicalSkillDTO",
    "ResumeCanonicalStatus",
    "ResumeCanonicalValidator",
    "ResumeEvidenceBundleDTO",
    "ResumeEvidenceRefDTO",
    "ResumeEvidenceSelector",
    "ResumeEvidenceSpanDTO",
    "resume_canonical_extractor",
    "resume_canonical_validator",
    "resume_evidence_selector",
]

_LAZY_MODULES: dict[str, tuple[str, str]] = {
    "ResumeCanonicalExtractor": ("app.modules.resume.canonical.extractor", "ResumeCanonicalExtractor"),
    "resume_canonical_extractor": ("app.modules.resume.canonical.extractor", "resume_canonical_extractor"),
    "ResumeCanonicalValidator": ("app.modules.resume.canonical.validator", "ResumeCanonicalValidator"),
    "resume_canonical_validator": ("app.modules.resume.canonical.validator", "resume_canonical_validator"),
    "ResumeEvidenceSelector": ("app.modules.resume.canonical.selector", "ResumeEvidenceSelector"),
    "resume_evidence_selector": ("app.modules.resume.canonical.selector", "resume_evidence_selector"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_MODULES.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    import importlib

    return getattr(importlib.import_module(module_name), attribute)


def __dir__() -> list[str]:
    return sorted(__all__)
