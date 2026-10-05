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
1. **exact quote 且全局唯一**：quote.strip() 必须是 cleaned resume_text 的精确连续
   子串，并且在原文中**只出现一次** —— 出现两次时 ``find()`` 只能指向第一处，
   不构成可靠 provenance，直接判 ambiguous 作废。不允许 fuzzy / embedding / 语义近似。
2. **value support**：quote 存在还不够 —— normalize(value) 必须出现在
   normalize(某个合法 quote) 内，防止「真 quote 配假 value」。normalize 复用
   PR2 的 ``normalize_evidence_text``（忽略空白与大小写），但禁止语义模糊匹配。
2.5 **entity locality（PROJECT）**：claim → resume 还不够，还必须满足
   claim → **correct resume entity**。PROJECT 先用 identity claim（name /
   date_range / role）定 anchor，按 anchor 顺序切出不重叠 window，只保留落在
   本 window 内的 claims。没有可用 anchor 的 structured project 直接丢弃。
3. **失败隔离**：单个非法 claim 只丢弃自己，不影响同一份简历的其它 claim，
   更不会让整次 canonical extraction FAILED（与 PR2/PR3 的 failure isolation 同源）。
"""

from __future__ import annotations

import hashlib
import re

from app.modules.interview.evaluation.models import normalize_evidence_text
from app.modules.resume.canonical.models import (
    CLAIM_KIND_ACHIEVEMENT,
    CLAIM_KIND_CERT_DATE,
    CLAIM_KIND_CONTEXT,
    CLAIM_KIND_DATE_RANGE,
    CLAIM_KIND_DEGREE,
    CLAIM_KIND_EXPERIENCE_TYPE,
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

# experience_type 的原文标记。只有 quote 里出现这些标记，才允许把 LLM 声称的类型
# 写进 Canonical。注意这里刻意**不使用**「工作」「正式」「intern」这类过宽的裸词：
#   「负责 Agent 工作流编排」/「系统正式上线」/「Internal Developer Platform」
#   都不是雇佣类型信号。
#
# 中文标记在 normalize 后的文本上做 substring 比对。
_INTERNSHIP_CN_MARKERS: tuple[str, ...] = ("实习",)
_WORK_CN_MARKERS: tuple[str, ...] = ("工作经历", "全职", "正式员工", "正式职工", "任职于", "就职于", "入职")

# 英文标记必须用词边界 regex，且在**未经 normalize**（保留空白）的原文上匹配：
# normalize 会删掉空白，导致 \b 失效；裸 "intern" 会误命中 internal / international。
_INTERNSHIP_EN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\binterns?\b"),
    re.compile(r"\binternships?\b"),
)
_WORK_EN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfull[-\s]?time\b"),
    re.compile(r"\bemployment\b"),
    re.compile(r"\bemployed\b"),
    re.compile(r"\bpermanent\b"),
)


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

        # PROJECT 走两阶段：identity anchor → window → locality 过滤
        profile.projects = self._resolve_projects(raw.projects or [], text)

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
        """把一条 quote 解析成**全局唯一**的精确 span。

        两条硬规则：

        1. 超长 / 过短 quote **整条作废**，不做截断 —— 截断会篡改 LLM 声称的
           source quote。模型应该改用第二条合法 quote。
        2. quote 必须在 ``resume_text`` 中**只出现一次**。若同一句话在简历里
           出现两次（例如两个项目都写「使用 Redis 进行缓存」），``find()`` 只能
           指向第一处，这不是可靠 provenance —— 本 PR 采取最保守策略直接判为
           ambiguous 并作废，不去猜第几处。

        Extractor prompt 已要求「尽量带足上下文」，因此模型应输出
        「项目 B 使用 Redis 进行缓存并实现热点保护」这类可唯一定位的 quote。
        """
        candidate = (quote or "").strip()
        if not (MIN_QUOTE_CHARS <= len(candidate) <= MAX_QUOTE_CHARS):
            return None
        start = resume_text.find(candidate)
        if start < 0:
            return None
        if resume_text.find(candidate, start + 1) >= 0:
            # 出现多次 → 无法确定是哪一处，拒绝
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

    # ------------------------------------------------------------------
    # PR4 review：project entity locality（claim 必须属于正确的 project）
    # ------------------------------------------------------------------

    def _rebuild_claim(
        self, claim: ResumeCanonicalClaimDTO, claim_kind: str, spans: list[ResumeEvidenceSpanDTO]
    ) -> ResumeCanonicalClaimDTO:
        """用裁剪后的 spans 重建 claim（claim_id 随 primary span 重新计算）。"""
        primary = spans[0]
        return ResumeCanonicalClaimDTO(
            claim_id=f"rc_{_stable_id('claim', claim_kind, normalize_evidence_text(claim.value), primary.start_char, primary.end_char)}",
            value=claim.value,
            evidence_spans=spans,
        )

    def _clip_claim(
        self,
        claim: ResumeCanonicalClaimDTO | None,
        claim_kind: str,
        window: tuple[int, int],
    ) -> ResumeCanonicalClaimDTO | None:
        """只保留落在本 project window 内的 span；一个都不剩则丢弃该 claim。

        这是「claim → correct resume entity」的收敛点：即使 quote 本身完全真实，
        只要它落在别的 project 区域，就必须从本 project 中删除。
        """
        if claim is None:
            return None
        start, end = window
        kept = [span for span in claim.evidence_spans if start <= span.start_char and span.end_char <= end]
        if not kept:
            return None
        return self._rebuild_claim(claim, claim_kind, kept)

    def _claims_in_window(
        self,
        raw_values: list[RawSourceBackedValue],
        claim_kind: str,
        resume_text: str,
        window: tuple[int, int],
    ) -> list[ResumeCanonicalClaimDTO]:
        result: list[ResumeCanonicalClaimDTO] = []
        for claim in self.claims(raw_values, claim_kind, resume_text):
            clipped = self._clip_claim(claim, claim_kind, window)
            if clipped is not None:
                result.append(clipped)
        return result

    def _resolve_projects(self, raw_projects: list[RawProjectDTO], resume_text: str) -> list[ResumeCanonicalProjectDTO]:
        """按原文 anchor 把 raw projects 落到互不重叠的 window 上。

        ```text
        Raw Projects
              ↓ 先验证 identity claims（name / date_range / role）
        确定 project anchor（优先 name）
              ↓ anchor start_char 升序 → 建立不重叠 window
            [a0, a1) / [a1, a2) / [a2, len)
              ↓ 每个 project 只保留落在自己 window 内的 claims
        按 anchor 文档顺序输出的 Canonical projects
        ```

        没有任何可用 anchor 的 structured project 直接 drop —— 本 PR 优先保证
        precision，不为了 recall 继续信任 LLM 的 entity grouping。
        """
        staged: list[
            tuple[
                int,
                RawProjectDTO,
                ResumeCanonicalClaimDTO | None,
                ResumeCanonicalClaimDTO | None,
                ResumeCanonicalClaimDTO | None,
            ]
        ] = []
        for raw_project in raw_projects or []:
            name = self.claim(raw_project.name, CLAIM_KIND_NAME, resume_text)
            role = self.claim(raw_project.role, CLAIM_KIND_ROLE, resume_text)
            date_range = self.claim(raw_project.date_range, CLAIM_KIND_DATE_RANGE, resume_text)
            anchor_claim = name or date_range or role
            if anchor_claim is None:
                continue
            staged.append((anchor_claim.evidence_spans[0].start_char, raw_project, name, role, date_range))

        if not staged:
            return []
        staged.sort(key=lambda item: item[0])

        # 同一 anchor 只保留第一个（同名 quote 无法区分是哪一个项目）
        deduped: list[tuple] = []
        seen_anchors: set[int] = set()
        for item in staged:
            if item[0] in seen_anchors:
                continue
            seen_anchors.add(item[0])
            deduped.append(item)
        staged = deduped

        projects: list[ResumeCanonicalProjectDTO] = []
        seen_ids: set[str] = set()
        for index, (anchor, raw_project, name, role, date_range) in enumerate(staged):
            end = staged[index + 1][0] if index + 1 < len(staged) else len(resume_text)
            window = (anchor, end)
            project = self._project_in_window(
                raw_project,
                resume_text,
                window=window,
                name=self._clip_claim(name, CLAIM_KIND_NAME, window),
                role=self._clip_claim(role, CLAIM_KIND_ROLE, window),
                date_range=self._clip_claim(date_range, CLAIM_KIND_DATE_RANGE, window),
            )
            if project is None or project.project_id in seen_ids:
                continue
            seen_ids.add(project.project_id)
            projects.append(project)
        return projects

    def _project_in_window(
        self,
        raw: RawProjectDTO,
        resume_text: str,
        *,
        window: tuple[int, int],
        name: ResumeCanonicalClaimDTO | None,
        role: ResumeCanonicalClaimDTO | None,
        date_range: ResumeCanonicalClaimDTO | None,
    ) -> ResumeCanonicalProjectDTO | None:
        technologies = self._claims_in_window(raw.technologies, CLAIM_KIND_TECHNOLOGY, resume_text, window)
        responsibilities = self._claims_in_window(raw.responsibilities, CLAIM_KIND_RESPONSIBILITY, resume_text, window)
        achievements = self._claims_in_window(raw.achievements, CLAIM_KIND_ACHIEVEMENT, resume_text, window)
        metrics = self._claims_in_window(raw.metrics, CLAIM_KIND_METRIC, resume_text, window)

        # 没有任何合法 claim（或在 window 内一个都不剩）→ 整体丢弃（§27）
        primary = name or date_range or role
        if primary is None:
            primary = (
                self._first_claim(metrics)
                or self._first_claim(responsibilities)
                or self._first_claim(achievements)
                or self._first_claim(technologies)
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

    def experience_type(
        self, raw_value: RawSourceBackedValue | None, resume_text: str
    ) -> ResumeCanonicalClaimDTO | None:
        """把 LLM 声称的 experience_type 变成 source-backed claim（保留 provenance）。

        与常规 claim 的差别：这里**不要求** `normalize(value) in normalize(quote)`
        （"INTERNSHIP" 显然不会出现在中文原文里），而是要求：

        1. quote 必须是 exact substring（与其它 claim 同一套校验）；
        2. 校验通过的 quote 里必须出现对应类型的**明确标记**。

        标记判定用两套 haystack：

        - 中文标记用 normalize 后的文本做 substring（``实习`` / ``工作经历`` …）；
        - 英文标记用**保留空白与词边界**的原文做 regex（``\\binterns?\\b`` 等），
          否则 normalize 会把空格删掉导致词边界失效，且 ``internal`` /
          ``international`` 会被 ``intern`` 误命中。

        拿不出证据、quote 编造、或原文没有对应标记 → ``None``
        （不是持久化一个没有 provenance 的 ``UNKNOWN``）。
        """
        declared = (raw_value.value if raw_value else "").strip().upper()
        if declared not in {"WORK", "INTERNSHIP"}:
            return None
        spans = self._valid_spans(raw_value, resume_text)
        if not spans:
            return None
        if not self._experience_type_supported(declared, spans):
            return None
        primary = spans[0]
        return ResumeCanonicalClaimDTO(
            claim_id=f"rc_{_stable_id('claim', CLAIM_KIND_EXPERIENCE_TYPE, normalize_evidence_text(declared), primary.start_char, primary.end_char)}",
            value=declared,
            evidence_spans=spans,
        )

    @staticmethod
    def _experience_type_supported(declared: str, spans: list[ResumeEvidenceSpanDTO]) -> bool:
        raw_haystack = " ".join(span.quote for span in spans).lower()
        norm_haystack = normalize_evidence_text(raw_haystack)
        if declared == "INTERNSHIP":
            if any(marker in norm_haystack for marker in _INTERNSHIP_CN_MARKERS):
                return True
            return any(pattern.search(raw_haystack) for pattern in _INTERNSHIP_EN_PATTERNS)
        if any(marker in norm_haystack for marker in _WORK_CN_MARKERS):
            return True
        return any(pattern.search(raw_haystack) for pattern in _WORK_EN_PATTERNS)

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
