"""Resume Canonical Schema —— 简历事实的 source-grounded 表示。

设计边界（PR4）
--------------
Canonical Resume **不是简历总结**，也不是评分：

- 它只保存「简历原文明确支持的事实」，每一条都带经过代码校验的 source span；
- 不保存能力判断（"能力强"/"高级工程师"/"有架构经验"）、不保存推断出的熟练度；
- 不保存评分 / 推荐 / 润色结论。

它同时也 **不是事实真实性认证**：Canonical 只能证明「简历原文确实写过这句」，
不能证明候选人写的内容在现实中为真。真实性仍由面试环节的
PROJECT authenticity / follow-up / 多轮矛盾检测去验证。

Legacy ``ResumeProfile``（``app/modules/resume/schemas.py``）保留为
**评分历史与展示用的 compatibility artifact**，不是 interview factual source。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

#: Canonical schema 版本。发生 breaking semantic change 时必须 bump：
#: 字段语义、验证规则、extractor prompt、claim 类型任一变化。
#: bump 后即使 resume_text 未变，旧 canonical 也会被判定 STALE 并重新抽取。
RESUME_CANONICAL_SCHEMA_VERSION = "resume-canonical-v1"

# ---------------------------------------------------------------------------
# 常量：quote / evidence 预算
# ---------------------------------------------------------------------------

#: 单个 raw claim 最多允许的 evidence quote 数
MAX_QUOTES_PER_CLAIM = 2
#: 单个 quote 的最小 / 最大字符数（strip 之后）
MIN_QUOTE_CHARS = 6
MAX_QUOTE_CHARS = 240
#: 单个 canonical claim 最多保留的 evidence span 数
MAX_SPANS_PER_CLAIM = 2
#: Evidence Selector：单个 bundle 最多 refs
MAX_EVIDENCE_REFS = 6
#: Evidence Selector：rendered_text 最大字符数
MAX_RENDERED_TEXT_CHARS = 500

# ---------------------------------------------------------------------------
# Canonical status（derived，不落 DB enum）
# ---------------------------------------------------------------------------


class ResumeCanonicalStatus(str, Enum):
    READY = "READY"
    STALE = "STALE"
    FAILED = "FAILED"
    NOT_EXTRACTED = "NOT_EXTRACTED"


# ---------------------------------------------------------------------------
# Source span
# ---------------------------------------------------------------------------


class ResumeEvidenceSpanDTO(BaseModel):
    """简历原文中的一个精确片段。

    不变式：``resume_text[start_char:end_char] == quote``（左闭右开）。
    行号为 1-based，且 ``start_line <= end_line``。
    """

    quote: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int


# ---------------------------------------------------------------------------
# Canonical claim
# ---------------------------------------------------------------------------


class ResumeCanonicalClaimDTO(BaseModel):
    """一条简历事实。

    不变式：**value 必须至少有一个经过代码校验的 source span**。
    不存在「有 value 但 evidence_spans 为空」的 canonical claim —— 校验阶段
    拿不到合法证据的 claim 会被直接丢弃。
    """

    claim_id: str = Field(min_length=1)
    value: str = Field(min_length=1)
    evidence_spans: list[ResumeEvidenceSpanDTO] = Field(default_factory=list, min_length=1)


# ---------------------------------------------------------------------------
# Canonical entities
# ---------------------------------------------------------------------------


class ResumeCanonicalProjectDTO(BaseModel):
    """简历项目。只保存原文事实，不保存 project_quality / technical_depth / importance。"""

    project_id: str

    name: ResumeCanonicalClaimDTO | None = None
    role: ResumeCanonicalClaimDTO | None = None
    date_range: ResumeCanonicalClaimDTO | None = None

    technologies: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)
    responsibilities: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)
    achievements: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)
    metrics: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)


class ResumeCanonicalExperienceDTO(BaseModel):
    """工作 / 实习经历。

    ``experience_type`` **由代码从 source-backed claim 推导**，不采信 LLM enum：

    - 只有经过校验的原文 quote 里明确出现「实习 / intern / internship」才允许
      ``INTERNSHIP``；
    - 只有原文出现「工作 / 全职 / 正式 / 任职 / 就职 / employment」这类信号才允许
      ``WORK``；
    - 其余（含 LLM 给了类型但拿不出原文证据、或 quote 是编造的）一律 ``UNKNOWN``。

    禁止根据日期长短、候选人年龄、公司名或学校推断。
    """

    experience_id: str

    organization: ResumeCanonicalClaimDTO | None = None
    role: ResumeCanonicalClaimDTO | None = None
    date_range: ResumeCanonicalClaimDTO | None = None

    technologies: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)
    responsibilities: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)
    achievements: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)
    metrics: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)

    experience_type: Literal["WORK", "INTERNSHIP", "UNKNOWN"] = "UNKNOWN"


class ResumeCanonicalEducationDTO(BaseModel):
    """教育经历。禁止根据学校名 / 毕业年份 / 年龄推断学历层次。"""

    education_id: str

    institution: ResumeCanonicalClaimDTO | None = None
    degree: ResumeCanonicalClaimDTO | None = None
    major: ResumeCanonicalClaimDTO | None = None
    date_range: ResumeCanonicalClaimDTO | None = None


class ResumeCanonicalSkillDTO(BaseModel):
    """技术技能。

    ``proficiency`` **禁止推断**：只有原文明确写了「熟练 Java」「熟悉 Redis」
    这类表述才允许非空，否则必须为 ``None``。
    """

    skill_id: str

    name: ResumeCanonicalClaimDTO
    proficiency: ResumeCanonicalClaimDTO | None = None
    contexts: list[ResumeCanonicalClaimDTO] = Field(default_factory=list)


class ResumeCanonicalCertificationDTO(BaseModel):
    certification_id: str
    name: ResumeCanonicalClaimDTO
    date: ResumeCanonicalClaimDTO | None = None


# ---------------------------------------------------------------------------
# Canonical profile
# ---------------------------------------------------------------------------


class ResumeCanonicalProfileDTO(BaseModel):
    """Canonical Resume Profile —— interview 的事实来源。

    显式 **不包含**：summary / experience_level / has_projects / overall_score。
    这些都是 derived / display information，不是原文事实。
    """

    schema_version: str = RESUME_CANONICAL_SCHEMA_VERSION

    projects: list[ResumeCanonicalProjectDTO] = Field(default_factory=list)
    experiences: list[ResumeCanonicalExperienceDTO] = Field(default_factory=list)
    education: list[ResumeCanonicalEducationDTO] = Field(default_factory=list)
    skills: list[ResumeCanonicalSkillDTO] = Field(default_factory=list)
    certifications: list[ResumeCanonicalCertificationDTO] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Raw LLM DTO —— LLM 只输出 value + evidence_quotes
# ---------------------------------------------------------------------------
#
# 与 Canonical DTO 的关键区别：
#   - 没有 claim_id / entity_id：ID 全部由代码 deterministic 生成；
#   - 没有 start_char / line number：span 全部由代码按原文计算；
#   - evidence_quotes 是「模型声称的原文」，尚未经过任何校验。
# ---------------------------------------------------------------------------


class RawSourceBackedValue(BaseModel):
    """LLM 输出的一条「看起来像事实」的值 + 它声称的原文出处。"""

    value: str
    evidence_quotes: list[str] = Field(default_factory=list)


class RawProjectDTO(BaseModel):
    name: RawSourceBackedValue | None = None
    role: RawSourceBackedValue | None = None
    date_range: RawSourceBackedValue | None = None
    technologies: list[RawSourceBackedValue] = Field(default_factory=list)
    responsibilities: list[RawSourceBackedValue] = Field(default_factory=list)
    achievements: list[RawSourceBackedValue] = Field(default_factory=list)
    metrics: list[RawSourceBackedValue] = Field(default_factory=list)


class RawExperienceDTO(BaseModel):
    organization: RawSourceBackedValue | None = None
    role: RawSourceBackedValue | None = None
    date_range: RawSourceBackedValue | None = None
    technologies: list[RawSourceBackedValue] = Field(default_factory=list)
    responsibilities: list[RawSourceBackedValue] = Field(default_factory=list)
    achievements: list[RawSourceBackedValue] = Field(default_factory=list)
    metrics: list[RawSourceBackedValue] = Field(default_factory=list)
    # experience_type 也必须是 source-backed value：LLM 只输出「声称的类型 + 原文出处」，
    # 是否成立由 validator 按原文里的实习/全职标记判定，不直接采信 LLM enum。
    experience_type: RawSourceBackedValue | None = None


class RawEducationDTO(BaseModel):
    institution: RawSourceBackedValue | None = None
    degree: RawSourceBackedValue | None = None
    major: RawSourceBackedValue | None = None
    date_range: RawSourceBackedValue | None = None


class RawSkillDTO(BaseModel):
    name: RawSourceBackedValue | None = None
    proficiency: RawSourceBackedValue | None = None
    contexts: list[RawSourceBackedValue] = Field(default_factory=list)


class RawCertificationDTO(BaseModel):
    name: RawSourceBackedValue | None = None
    date: RawSourceBackedValue | None = None


class RawResumeCanonicalDTO(BaseModel):
    """Canonical Extractor 的 structured output 顶层模型。"""

    projects: list[RawProjectDTO] = Field(default_factory=list)
    experiences: list[RawExperienceDTO] = Field(default_factory=list)
    education: list[RawEducationDTO] = Field(default_factory=list)
    skills: list[RawSkillDTO] = Field(default_factory=list)
    certifications: list[RawCertificationDTO] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence refs（Interview 侧消费）
# ---------------------------------------------------------------------------

ENTITY_TYPE_PROJECT = "PROJECT"
ENTITY_TYPE_EXPERIENCE = "EXPERIENCE"
ENTITY_TYPE_SKILL = "SKILL"
ENTITY_TYPE_EDUCATION = "EDUCATION"
ENTITY_TYPE_CERTIFICATION = "CERTIFICATION"


class ResumeEvidenceRefDTO(BaseModel):
    """一条被面试引用的简历事实。

    ``quote`` 必须直接来自对应 ``ResumeEvidenceSpanDTO.quote``，不得重新生成、
    不得改写、不得拼接。真正 provenance 是 claim_id + span，不是 rendered_text。
    """

    claim_id: str = Field(min_length=1)
    entity_type: Literal["PROJECT", "EXPERIENCE", "SKILL", "EDUCATION", "CERTIFICATION"]
    entity_id: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    value: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    start_line: int
    end_line: int


class ResumeEvidenceBundleDTO(BaseModel):
    refs: list[ResumeEvidenceRefDTO] = Field(default_factory=list)
    rendered_text: str = ""


# ---------------------------------------------------------------------------
# claim kind —— 仅用于 stable id 与 selector 优先级，不是业务分类
# ---------------------------------------------------------------------------

CLAIM_KIND_NAME = "NAME"
CLAIM_KIND_ROLE = "ROLE"
CLAIM_KIND_DATE_RANGE = "DATE_RANGE"
CLAIM_KIND_TECHNOLOGY = "TECHNOLOGY"
CLAIM_KIND_RESPONSIBILITY = "RESPONSIBILITY"
CLAIM_KIND_ACHIEVEMENT = "ACHIEVEMENT"
CLAIM_KIND_METRIC = "METRIC"
CLAIM_KIND_ORGANIZATION = "ORGANIZATION"
CLAIM_KIND_INSTITUTION = "INSTITUTION"
CLAIM_KIND_DEGREE = "DEGREE"
CLAIM_KIND_MAJOR = "MAJOR"
CLAIM_KIND_PROFICIENCY = "PROFICIENCY"
CLAIM_KIND_CONTEXT = "CONTEXT"
CLAIM_KIND_CERT_DATE = "CERT_DATE"
