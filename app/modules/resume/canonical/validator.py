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
    MIN_BOUNDARY_QUOTE_CHARS,
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
    def _span_supports_value(value: str, span: ResumeEvidenceSpanDTO) -> bool:
        """**单个** span 是否独立支持 value（忽略空白与大小写，不做语义匹配）。"""
        normalized_value = normalize_evidence_text(value)
        if not normalized_value:
            return False
        return normalized_value in normalize_evidence_text(span.quote)

    def claim(
        self, raw_value: RawSourceBackedValue | None, claim_kind: str, resume_text: str
    ) -> ResumeCanonicalClaimDTO | None:
        """把一条 raw value 转成 canonical claim；拿不到证据就返回 None（丢弃）。

        这是「LLM 不能把没有原文证据的 claim 塞进 Canonical」的唯一收敛点：
        - quotes 为空 → 丢弃（§71-J）
        - 所有 quote 都不是原文精确子串 → 丢弃（§71-B）
        - quote 真实但 value 不被支持 → 丢弃（§71-C）

        并且**逐 span 过滤**：``evidence_spans`` 只保留**独立支持** value 的 span。
        只要 any span 支持就保存全部，会把「恰好真实但与本 claim 无关」的 quote
        也持久化（Selector 固定取 ``evidence_spans[0]``，会直接把它带进 Topic）。
        """
        if raw_value is None:
            return None
        value = (raw_value.value or "").strip()
        if not value:
            return None
        supporting = [
            span for span in self._valid_spans(raw_value, resume_text) if self._span_supports_value(value, span)
        ]
        if not supporting:
            return None
        primary = supporting[0]
        return ResumeCanonicalClaimDTO(
            claim_id=f"rc_{_stable_id('claim', claim_kind, normalize_evidence_text(value), primary.start_char, primary.end_char)}",
            value=value,
            evidence_spans=supporting,
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
        window: tuple[int, int] | None,
    ) -> ResumeCanonicalClaimDTO | None:
        """只保留落在本 project window 内的 span；一个都不剩则丢弃该 claim。

        这是「claim → correct resume entity」的收敛点：即使 quote 本身完全真实，
        只要它落在别的 project 区域，就必须从本 project 中删除。

        ``window is None``（无法建立 verified source scope）时只对 identity claims
        调用，按原样保留 —— 它们是实体自身的标识，不参与 locality 裁剪。
        """
        if claim is None:
            return None
        if window is None:
            return claim
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

    @staticmethod
    def _boundary_span(quote: str | None, resume_text: str) -> ResumeEvidenceSpanDTO | None:
        """把 source scope 边界标记解析成 span。

        边界标记**不是 claim**：不需要自证 value，只要求 exact + unique，
        且长度下限比 claim quote 低（真实边界常常只有 2~4 个字，如「工作经历」）。
        """
        candidate = (quote or "").strip()
        if not (MIN_BOUNDARY_QUOTE_CHARS <= len(candidate) <= MAX_QUOTE_CHARS):
            return None
        start = resume_text.find(candidate)
        if start < 0:
            return None
        if resume_text.find(candidate, start + 1) >= 0:
            return None
        end = start + len(candidate)
        return ResumeEvidenceSpanDTO(
            quote=candidate,
            start_char=start,
            end_char=end,
            start_line=resume_text.count("\n", 0, start) + 1,
            end_line=resume_text.count("\n", 0, end) + 1,
        )

    def _resolve_projects(self, raw_projects: list[RawProjectDTO], resume_text: str) -> list[ResumeCanonicalProjectDTO]:
        """把 raw projects 落到由**原文自身**确定的 closed source scope 上。

        ```text
        Raw Projects
              ↓ 先验证 identity claims（name / date_range / role）
        确定 project anchor（优先 name）与 identity start = min(identity spans, scope_start)
              ↓ verified scope_end（原文行，exact + unique）给出 closed window 右界
            window = [identity_start, scope_end.end_char]
              ↓ 只保留完全落在 window 内的 claims
        按 anchor 文档顺序输出的 Canonical projects
        ```

        为什么不能再用「anchor → EOF」：Extractor 的 projects[] 并不保证完整。
        若原文有项目 A / 项目 B，而 LLM 只抽出 A 且错误地把 B 的 MySQL claim 挂在 A 上，
        ``[A, EOF)`` 会把它放行；同理最后一个 project 会把后续的
        「工作经历 / 专业技能」section 全部吸进来。因此右界必须来自原文里的
        一条**已验证边界**，而不是「后面还有没有 RawProjectDTO」。

        拿不出合法 scope_end 时 **保守处理**：该项目只保留 identity claims，
        不再默认把 anchor 之后到文末的一切都算作本项目。

        没有任何可用 anchor 的 structured project 直接 drop —— 优先保证 precision，
        不为了 recall 继续信任 LLM 的 entity grouping。
        """
        staged: list[tuple] = []
        for raw_project in raw_projects or []:
            name = self.claim(raw_project.name, CLAIM_KIND_NAME, resume_text)
            role = self.claim(raw_project.role, CLAIM_KIND_ROLE, resume_text)
            date_range = self.claim(raw_project.date_range, CLAIM_KIND_DATE_RANGE, resume_text)
            anchor_claim = name or date_range or role
            if anchor_claim is None:
                continue
            identity = [claim for claim in (name, role, date_range) if claim is not None]
            # P1：window.start 不能固定等于 name.start —— 常见格式里 date_range /
            # role 排在 name 前面（"2025.01-2025.06 / 智能面试系统 / 后端开发"），
            # 用 min(...) 才不会把合法 identity claim 裁掉。entity id 仍优先 name。
            identity_start = min(claim.evidence_spans[0].start_char for claim in identity)
            staged.append(
                (anchor_claim.evidence_spans[0].start_char, identity_start, raw_project, name, role, date_range)
            )

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
        for index, (anchor, identity_start, raw_project, name, role, date_range) in enumerate(staged):
            next_anchor = staged[index + 1][0] if index + 1 < len(staged) else None
            window = self._project_window(raw_project, resume_text, identity_start, next_anchor)
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

    def _project_window(
        self,
        raw: RawProjectDTO,
        resume_text: str,
        identity_start: int,
        next_anchor: int | None,
    ) -> tuple[int, int] | None:
        """由原文确定该项目 closed source scope；无法确定时返回 None（保守）。"""
        start = identity_start
        scope_start = self._boundary_span(raw.scope_start_quote, resume_text)
        if scope_start is not None:
            start = min(start, scope_start.start_char)

        scope_end = self._boundary_span(raw.scope_end_quote, resume_text)
        if scope_end is None:
            return None
        end = scope_end.end_char
        # 防御：即使 scope_end 被幻觉指到别的项目区域，也不能越过下一个 project 的 anchor
        if next_anchor is not None:
            end = min(end, next_anchor)
        if end <= start:
            return None
        return (start, end)

    def _project_in_window(
        self,
        raw: RawProjectDTO,
        resume_text: str,
        *,
        window: tuple[int, int] | None,
        name: ResumeCanonicalClaimDTO | None,
        role: ResumeCanonicalClaimDTO | None,
        date_range: ResumeCanonicalClaimDTO | None,
    ) -> ResumeCanonicalProjectDTO | None:
        if window is None:
            # 无法建立 verified source scope → 只保留 identity claims（precision first）
            technologies: list[ResumeCanonicalClaimDTO] = []
            responsibilities: list[ResumeCanonicalClaimDTO] = []
            achievements: list[ResumeCanonicalClaimDTO] = []
            metrics: list[ResumeCanonicalClaimDTO] = []
        else:
            technologies = self._claims_in_window(raw.technologies, CLAIM_KIND_TECHNOLOGY, resume_text, window)
            responsibilities = self._claims_in_window(
                raw.responsibilities, CLAIM_KIND_RESPONSIBILITY, resume_text, window
            )
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
        2. **每个 span 独立**含有对应类型的明确标记 —— 不把多个 span 拼起来再
           ``any(marker)``，否则「公司名 + 后端开发实习生」两条都会留下，
           而公司名并不支持 INTERNSHIP。

        拿不出证据、quote 编造、或原文没有对应标记 → ``None``
        （不是持久化一个没有 provenance 的 ``UNKNOWN``）。
        """
        declared = (raw_value.value if raw_value else "").strip().upper()
        if declared not in {"WORK", "INTERNSHIP"}:
            return None
        supporting = [
            span for span in self._valid_spans(raw_value, resume_text) if self._experience_span_supports(declared, span)
        ]
        if not supporting:
            return None
        primary = supporting[0]
        return ResumeCanonicalClaimDTO(
            claim_id=f"rc_{_stable_id('claim', CLAIM_KIND_EXPERIENCE_TYPE, normalize_evidence_text(declared), primary.start_char, primary.end_char)}",
            value=declared,
            evidence_spans=supporting,
        )

    @staticmethod
    def _experience_span_supports(declared: str, span: ResumeEvidenceSpanDTO) -> bool:
        """单个 span 是否独立含有 declared 类型的明确标记。

        标记判定用两套 haystack：

        - 中文标记用 normalize 后的文本做 substring（``实习`` / ``工作经历`` …）；
        - 英文标记用**保留空白与词边界**的原文做 regex（``\\binterns?\\b`` 等），
          否则 normalize 会把空格删掉导致词边界失效，且 ``internal`` /
          ``international`` 会被 ``intern`` 误命中。
        """
        raw_haystack = span.quote.lower()
        norm_haystack = normalize_evidence_text(span.quote)
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
