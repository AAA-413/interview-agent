"""Deterministic Canonical Evidence Validator。

职责边界
--------
LLM 只负责「从哪里看起来像一个事实」；**代码负责确认这个事实能否在简历原文里找到证据**。

本模块是纯计算：

- 不查 DB
- 不调 LLM
- 不碰 ORM
- 相同输入 → 相同输出

校验规则
--------
1. **exact quote**：quote.strip() 必须是 cleaned resume_text 的精确连续子串
   （``resume_text.find(quote) >= 0``）。不允许 fuzzy / embedding / 语义近似。
2. **value support**：quote 存在还不够 —— normalize(value) 必须出现在
   normalize(某个合法 quote) 内，防止「真 quote 配假 value」。normalize 复用
   PR2 的 ``normalize_evidence_text``（忽略空白与大小写），但禁止语义模糊匹配。
3. **失败隔离**：单个非法 claim 只丢弃自己，不影响同一份简历的其它 claim，
   更不会让整次 canonical extraction FAILED（与 PR2/PR3 的 failure isolation 同源）。
"""

from __future__ import annotations

import hashlib

from app.modules.interview.evaluation.models import normalize_evidence_text
from app.modules.resume.canonical.models import (
    CLAIM_KIND_ACHIEVEMENT,
    CLAIM_KIND_CERT_DATE,
    CLAIM_KIND_CONTEXT,
    CLAIM_KIND_DATE_RANGE,
    CLAIM_KIND_DEGREE,
    CLAIM_KIND_INSTITUTION,
    CLAIM_KIND_MAJOR,
    CLAIM_KIND_METRIC,
    CLAIM_KIND_NAME,
    CLAIM_KIND_ORGANIZATION,
    CLAIM_KIND_PROFICIENCY,
    CLAIM_KIND_RESPONSIBILITY,
    CLAIM_KIND_ROLE,
    CLAIM_KIND_TECHNOLOGY,
    MAX_QUOTE_CHARS,
    MAX_QUOTES_PER_CLAIM,
    MAX_SPANS_PER_CLAIM,
    MIN_QUOTE_CHARS,
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
    ResumeEvidenceSpanDTO,
)

# stable id 的 hex 长度（12 hex = 「rc_a91f02c771ab」这类形态）
_ID_HEX_LEN = 12

# experience_type 的原文标记（normalize 后比对：去空白 + 小写）
# 只有 quote 里出现这些标记，才允许把 LLM 声称的类型写进 Canonical。
_INTERNSHIP_MARKERS: tuple[str, ...] = ("实习", "intern", "internship")
_WORK_MARKERS: tuple[str, ...] = ("工作", "全职", "正式", "任职", "就职", "employment", "full-time", "fulltime")


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_ID_HEX_LEN]


class ResumeCanonicalValidator:
    """把 raw LLM extraction 转换为 source-validated canonical profile。"""

    # ------------------------------------------------------------------
    # 顶层入口
    # ------------------------------------------------------------------

    def build(self, raw: RawResumeCanonicalDTO, resume_text: str) -> ResumeCanonicalProfileDTO:
        text = resume_text or ""
        profile = ResumeCanonicalProfileDTO()

        for raw_project in raw.projects or []:
            project = self._project(raw_project, text)
            if project is not None and project.project_id not in {item.project_id for item in profile.projects}:
                profile.projects.append(project)

        for raw_experience in raw.experiences or []:
            experience = self._experience(raw_experience, text)
            if experience is not None and experience.experience_id not in {
                item.experience_id for item in profile.experiences
            }:
                profile.experiences.append(experience)

        for raw_education in raw.education or []:
            education = self._education(raw_education, text)
            if education is not None and education.education_id not in {
                item.education_id for item in profile.education
            }:
                profile.education.append(education)

        for raw_skill in raw.skills or []:
            skill = self._skill(raw_skill, text)
            if skill is not None and skill.skill_id not in {item.skill_id for item in profile.skills}:
                profile.skills.append(skill)

        for raw_cert in raw.certifications or []:
            cert = self._certification(raw_cert, text)
            if cert is not None and cert.certification_id not in {
                item.certification_id for item in profile.certifications
            }:
                profile.certifications.append(cert)

        return profile

    # ------------------------------------------------------------------
    # quote 校验 + span 计算
    # ------------------------------------------------------------------

    @staticmethod
    def _span_for_quote(quote: str, resume_text: str) -> ResumeEvidenceSpanDTO | None:
        """把一条 quote 解析成精确 span。

        超长 quote **整条作废**，不做截断 —— 截断会篡改 LLM 声称的 source quote。
        模型应该改用第二条更短但合法的 quote。
        """
        candidate = (quote or "").strip()
        if not (MIN_QUOTE_CHARS <= len(candidate) <= MAX_QUOTE_CHARS):
            return None
        start = resume_text.find(candidate)
        if start < 0:
            return None
        end = start + len(candidate)
        return ResumeEvidenceSpanDTO(
            quote=candidate,
            start_char=start,
            end_char=end,
            start_line=resume_text.count("\n", 0, start) + 1,
            end_line=resume_text.count("\n", 0, end) + 1,
        )

    def _valid_spans(self, value: RawSourceBackedValue, resume_text: str) -> list[ResumeEvidenceSpanDTO]:
        """收集一条 raw value 的合法 span。

        只接受前 ``MAX_QUOTES_PER_CLAIM`` 条 quote，逐条做 exact substring 校验，
        再按 (start_char, quote) 去重。
        """
        spans: list[ResumeEvidenceSpanDTO] = []
        seen: set[tuple[int, str]] = set()
        for quote in list(value.evidence_quotes or [])[:MAX_QUOTES_PER_CLAIM]:
            span = self._span_for_quote(quote, resume_text)
            if span is None:
                continue
            fingerprint = (span.start_char, span.quote)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            spans.append(span)
            if len(spans) >= MAX_SPANS_PER_CLAIM:
                break
        return spans

    @staticmethod
    def _value_supported(value: str, spans: list[ResumeEvidenceSpanDTO]) -> bool:
        """value 是否被某个合法 quote 支持（忽略空白与大小写，不做语义匹配）。"""
        normalized_value = normalize_evidence_text(value)
        if not normalized_value:
            return False
        return any(normalized_value in normalize_evidence_text(span.quote) for span in spans)

    def claim(
        self, raw_value: RawSourceBackedValue | None, claim_kind: str, resume_text: str
    ) -> ResumeCanonicalClaimDTO | None:
        """把一条 raw value 转成 canonical claim；拿不到证据就返回 None（丢弃）。

        这是「LLM 不能把没有原文证据的 claim 塞进 Canonical」的唯一收敛点：
        - quotes 为空 → 丢弃（§71-J）
        - 所有 quote 都不是原文精确子串 → 丢弃（§71-B）
        - quote 真实但 value 不被支持 → 丢弃（§71-C）
        """
        if raw_value is None:
            return None
        value = (raw_value.value or "").strip()
        if not value:
            return None
        spans = self._valid_spans(raw_value, resume_text)
        if not spans:
            return None
        if not self._value_supported(value, spans):
            return None
        primary = spans[0]
        return ResumeCanonicalClaimDTO(
            claim_id=f"rc_{_stable_id('claim', claim_kind, normalize_evidence_text(value), primary.start_char, primary.end_char)}",
            value=value,
            evidence_spans=spans,
        )

    def claims(
        self, raw_values: list[RawSourceBackedValue], claim_kind: str, resume_text: str
    ) -> list[ResumeCanonicalClaimDTO]:
        """批量转换 + deterministic 去重（同 kind / 同 value / 同 span 只留一份）。"""
        result: list[ResumeCanonicalClaimDTO] = []
        seen: set[tuple[str, str, int, int]] = set()
        for raw_value in raw_values or []:
            claim = self.claim(raw_value, claim_kind, resume_text)
            if claim is None:
                continue
            primary = claim.evidence_spans[0]
            fingerprint = (claim_kind, normalize_evidence_text(claim.value), primary.start_char, primary.end_char)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result.append(claim)
        return result

    # ------------------------------------------------------------------
    # 实体构建
    # ------------------------------------------------------------------

    @staticmethod
    def _entity_id(prefix: str, entity_kind: str, primary: ResumeCanonicalClaimDTO) -> str:
        return f"{prefix}_{_stable_id('entity', entity_kind, primary.claim_id)}"

    @staticmethod
    def _first_claim(claims: list[ResumeCanonicalClaimDTO]) -> ResumeCanonicalClaimDTO | None:
        return claims[0] if claims else None

    def _project(self, raw: RawProjectDTO, resume_text: str) -> ResumeCanonicalProjectDTO | None:
        name = self.claim(raw.name, CLAIM_KIND_NAME, resume_text)
        role = self.claim(raw.role, CLAIM_KIND_ROLE, resume_text)
        date_range = self.claim(raw.date_range, CLAIM_KIND_DATE_RANGE, resume_text)
        technologies = self.claims(raw.technologies, CLAIM_KIND_TECHNOLOGY, resume_text)
        responsibilities = self.claims(raw.responsibilities, CLAIM_KIND_RESPONSIBILITY, resume_text)
        achievements = self.claims(raw.achievements, CLAIM_KIND_ACHIEVEMENT, resume_text)
        metrics = self.claims(raw.metrics, CLAIM_KIND_METRIC, resume_text)

        # 没有任何合法 claim 的项目整体丢弃（§27）
        primary = (
            name
            or role
            or self._first_claim(metrics)
            or self._first_claim(responsibilities)
            or self._first_claim(achievements)
            or self._first_claim(technologies)
            or date_range
        )
        if primary is None:
            return None

        return ResumeCanonicalProjectDTO(
            project_id=self._entity_id("rp", "project", primary),
            name=name,
            role=role,
            date_range=date_range,
            technologies=technologies,
            responsibilities=responsibilities,
            achievements=achievements,
            metrics=metrics,
        )

    def _experience(self, raw: RawExperienceDTO, resume_text: str) -> ResumeCanonicalExperienceDTO | None:
        organization = self.claim(raw.organization, CLAIM_KIND_ORGANIZATION, resume_text)
        role = self.claim(raw.role, CLAIM_KIND_ROLE, resume_text)
        date_range = self.claim(raw.date_range, CLAIM_KIND_DATE_RANGE, resume_text)
        technologies = self.claims(raw.technologies, CLAIM_KIND_TECHNOLOGY, resume_text)
        responsibilities = self.claims(raw.responsibilities, CLAIM_KIND_RESPONSIBILITY, resume_text)
        achievements = self.claims(raw.achievements, CLAIM_KIND_ACHIEVEMENT, resume_text)
        metrics = self.claims(raw.metrics, CLAIM_KIND_METRIC, resume_text)

        primary = (
            organization
            or role
            or self._first_claim(metrics)
            or self._first_claim(responsibilities)
            or self._first_claim(achievements)
            or self._first_claim(technologies)
            or date_range
        )
        if primary is None:
            return None

        return ResumeCanonicalExperienceDTO(
            experience_id=self._entity_id("re", "experience", primary),
            organization=organization,
            role=role,
            date_range=date_range,
            technologies=technologies,
            responsibilities=responsibilities,
            achievements=achievements,
            metrics=metrics,
            experience_type=self.experience_type(raw.experience_type, resume_text),
        )

    def experience_type(self, raw_value: RawSourceBackedValue | None, resume_text: str) -> str:
        """把 LLM 声称的 experience_type 变成 source-backed 判定结果。

        与常规 claim 的差别：这里**不要求** `normalize(value) in normalize(quote)`
        （"INTERNSHIP" 显然不会出现在中文原文里），而是要求：

        1. quote 必须是 exact substring（与其它 claim 同一套校验）；
        2. 校验通过的 quote 里必须出现对应类型的明确原文标记。

        拿不出证据、quote 是编造的、或原文没有对应标记 → 一律 `UNKNOWN`。
        """
        declared = (raw_value.value if raw_value else "").strip().upper()
        if declared not in {"WORK", "INTERNSHIP"}:
            return "UNKNOWN"
        spans = self._valid_spans(raw_value, resume_text)
        if not spans:
            return "UNKNOWN"
        haystack = normalize_evidence_text(" ".join(span.quote for span in spans))
        markers = _INTERNSHIP_MARKERS if declared == "INTERNSHIP" else _WORK_MARKERS
        return declared if any(marker in haystack for marker in markers) else "UNKNOWN"

    def _education(self, raw: RawEducationDTO, resume_text: str) -> ResumeCanonicalEducationDTO | None:
        institution = self.claim(raw.institution, CLAIM_KIND_INSTITUTION, resume_text)
        degree = self.claim(raw.degree, CLAIM_KIND_DEGREE, resume_text)
        major = self.claim(raw.major, CLAIM_KIND_MAJOR, resume_text)
        date_range = self.claim(raw.date_range, CLAIM_KIND_DATE_RANGE, resume_text)

        primary = institution or degree or major or date_range
        if primary is None:
            return None

        return ResumeCanonicalEducationDTO(
            education_id=self._entity_id("rd", "education", primary),
            institution=institution,
            degree=degree,
            major=major,
            date_range=date_range,
        )

    def _skill(self, raw: RawSkillDTO, resume_text: str) -> ResumeCanonicalSkillDTO | None:
        # name 是 canonical skill 的必填项，拿不到证据就整条丢弃
        name = self.claim(raw.name, CLAIM_KIND_NAME, resume_text)
        if name is None:
            return None
        return ResumeCanonicalSkillDTO(
            skill_id=self._entity_id("rs", "skill", name),
            name=name,
            # proficiency 只在原文明确写「熟练 X」时才存在；validator 不做任何推断
            proficiency=self.claim(raw.proficiency, CLAIM_KIND_PROFICIENCY, resume_text),
            contexts=self.claims(raw.contexts, CLAIM_KIND_CONTEXT, resume_text),
        )

    def _certification(self, raw: RawCertificationDTO, resume_text: str) -> ResumeCanonicalCertificationDTO | None:
        name = self.claim(raw.name, CLAIM_KIND_NAME, resume_text)
        if name is None:
            return None
        return ResumeCanonicalCertificationDTO(
            certification_id=self._entity_id("rt", "certification", name),
            name=name,
            date=self.claim(raw.date, CLAIM_KIND_CERT_DATE, resume_text),
        )


resume_canonical_validator = ResumeCanonicalValidator()
