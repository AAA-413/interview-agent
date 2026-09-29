"""Canonical Resume Extractor —— 只做信息抽取，不做判断。

职责边界
--------
本组件唯一的职责是「从简历原文里指出哪里看起来像一个事实」，输出
``value + evidence_quotes``。**它不决定这些 quote 是否真的存在** —— 那是
``ResumeCanonicalValidator`` 的事。

与 ``ResumeGradingService`` 是两个不同职责、两个 failure domain：
- Grading 负责评分与建议（legacy ResumeProfile）；
- Canonical 负责事实抽取（source-grounded facts）。
任一方失败不得拖垮另一方。

复用现有的 ``structured_output_invoker`` / ``llm_registry``，不新造 AI client。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.common.ai.structured_output import structured_output_invoker
from app.common.error_code import ErrorCode
from app.common.prompt_utils import load_prompt, render_template
from app.modules.resume.canonical.models import (
    RawCertificationDTO,
    RawEducationDTO,
    RawExperienceDTO,
    RawProjectDTO,
    RawResumeCanonicalDTO,
    RawSkillDTO,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


class _StructuredDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _RawSourceBackedValueDTO(_StructuredDTO):
    value: str
    evidence_quotes: list[str] = Field(alias="evidenceQuotes", default_factory=list)


class _RawProjectDTO(_StructuredDTO):
    name: _RawSourceBackedValueDTO | None = None
    role: _RawSourceBackedValueDTO | None = None
    date_range: _RawSourceBackedValueDTO | None = Field(alias="dateRange", default=None)
    technologies: list[_RawSourceBackedValueDTO] = Field(default_factory=list)
    responsibilities: list[_RawSourceBackedValueDTO] = Field(default_factory=list)
    achievements: list[_RawSourceBackedValueDTO] = Field(default_factory=list)
    metrics: list[_RawSourceBackedValueDTO] = Field(default_factory=list)


class _RawExperienceDTO(_StructuredDTO):
    organization: _RawSourceBackedValueDTO | None = None
    role: _RawSourceBackedValueDTO | None = None
    date_range: _RawSourceBackedValueDTO | None = Field(alias="dateRange", default=None)
    technologies: list[_RawSourceBackedValueDTO] = Field(default_factory=list)
    responsibilities: list[_RawSourceBackedValueDTO] = Field(default_factory=list)
    achievements: list[_RawSourceBackedValueDTO] = Field(default_factory=list)
    metrics: list[_RawSourceBackedValueDTO] = Field(default_factory=list)
    experience_type: str = Field(alias="experienceType", default="UNKNOWN")


class _RawEducationDTO(_StructuredDTO):
    institution: _RawSourceBackedValueDTO | None = None
    degree: _RawSourceBackedValueDTO | None = None
    major: _RawSourceBackedValueDTO | None = None
    date_range: _RawSourceBackedValueDTO | None = Field(alias="dateRange", default=None)


class _RawSkillDTO(_StructuredDTO):
    name: _RawSourceBackedValueDTO | None = None
    proficiency: _RawSourceBackedValueDTO | None = None
    contexts: list[_RawSourceBackedValueDTO] = Field(default_factory=list)


class _RawCertificationDTO(_StructuredDTO):
    name: _RawSourceBackedValueDTO | None = None
    date: _RawSourceBackedValueDTO | None = None


class _ExtractionResultDTO(_StructuredDTO):
    projects: list[_RawProjectDTO] = Field(default_factory=list)
    experiences: list[_RawExperienceDTO] = Field(default_factory=list)
    education: list[_RawEducationDTO] = Field(default_factory=list)
    skills: list[_RawSkillDTO] = Field(default_factory=list)
    certifications: list[_RawCertificationDTO] = Field(default_factory=list)


def _to_value(dto: _RawSourceBackedValueDTO | None):
    if dto is None:
        return None
    from app.modules.resume.canonical.models import RawSourceBackedValue

    return RawSourceBackedValue(value=dto.value, evidence_quotes=list(dto.evidence_quotes or []))


def _to_values(dtos) -> list:
    from app.modules.resume.canonical.models import RawSourceBackedValue

    return [
        RawSourceBackedValue(value=item.value, evidence_quotes=list(item.evidence_quotes or [])) for item in dtos or []
    ]


class ResumeCanonicalExtractor:
    """把 cleaned resume text 交给 LLM 抽取 raw source-backed claims。

    输出仍是 **未校验** 的 raw claims（quote 只是模型声称的原文），
    必须经 ``ResumeCanonicalValidator`` 才能进入 Canonical Profile。
    """

    def __init__(self):
        self._system_prompt = load_prompt(_PROMPTS_DIR, "resume-canonical-extractor-system.md")
        self._user_prompt_template = load_prompt(_PROMPTS_DIR, "resume-canonical-extractor-user.md")

    async def extract(self, chat_model: ChatOpenAI, resume_text: str) -> RawResumeCanonicalDTO:
        # §20：resume 正文是不可信数据，用 JSON string 包裹后再进模板，
        # 避免其中的「忽略之前要求 / 输出某个 JSON」被当成指令结构。
        user_prompt = render_template(
            self._user_prompt_template,
            {"resumeTextJson": json.dumps(resume_text or "", ensure_ascii=False)},
        )
        dto = await structured_output_invoker.invoke(
            chat_model=chat_model,
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            output_model=_ExtractionResultDTO,
            error_code=ErrorCode.AI_SERVICE_ERROR,
            error_prefix="简历事实抽取失败：",
            log_context="简历 canonical 抽取",
        )
        return self._to_raw(dto)

    @staticmethod
    def _to_raw(dto: _ExtractionResultDTO) -> RawResumeCanonicalDTO:
        return RawResumeCanonicalDTO(
            projects=[
                RawProjectDTO(
                    name=_to_value(item.name),
                    role=_to_value(item.role),
                    date_range=_to_value(item.date_range),
                    technologies=_to_values(item.technologies),
                    responsibilities=_to_values(item.responsibilities),
                    achievements=_to_values(item.achievements),
                    metrics=_to_values(item.metrics),
                )
                for item in dto.projects or []
            ],
            experiences=[
                RawExperienceDTO(
                    organization=_to_value(item.organization),
                    role=_to_value(item.role),
                    date_range=_to_value(item.date_range),
                    technologies=_to_values(item.technologies),
                    responsibilities=_to_values(item.responsibilities),
                    achievements=_to_values(item.achievements),
                    metrics=_to_values(item.metrics),
                    experience_type=item.experience_type
                    if item.experience_type in {"WORK", "INTERNSHIP"}
                    else "UNKNOWN",
                )
                for item in dto.experiences or []
            ],
            education=[
                RawEducationDTO(
                    institution=_to_value(item.institution),
                    degree=_to_value(item.degree),
                    major=_to_value(item.major),
                    date_range=_to_value(item.date_range),
                )
                for item in dto.education or []
            ],
            skills=[
                RawSkillDTO(
                    name=_to_value(item.name),
                    proficiency=_to_value(item.proficiency),
                    contexts=_to_values(item.contexts),
                )
                for item in dto.skills or []
            ],
            certifications=[
                RawCertificationDTO(
                    name=_to_value(item.name),
                    date=_to_value(item.date),
                )
                for item in dto.certifications or []
            ],
        )


resume_canonical_extractor = ResumeCanonicalExtractor()
