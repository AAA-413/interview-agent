"""Hybrid Evaluator 的模型、权重、阈值与规则常量。

设计原则（PR2）：

- LLM 只负责「语义判断」（每个 active dimension 的分数 + 证据）
- 规则负责「硬约束与校准」（hard guard / evidence cap / confidence / 最终分数计算）
- 最终 ``ability_score`` 由代码计算，LLM 不直接决定
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from app.modules.interview.schemas import (
    KNOWLEDGE_VERDICT_INSUFFICIENT,
    DynamicTopicDTO,
    DynamicTurnDTO,
    KnowledgeGroundingDTO,
)

# evaluator 版本：参与 SingleFlight key，改语义/权重/阈值时必须 bump
#
# v2（PR2 review round 4）改变了实际评分语义：unique evidence span 校准、
# 高分证据门槛、UNGROUNDED_POSITIVE_DIMENSION 拒绝、previous score 移出 prompt、
# rubric dimension mapping。
# v3（PR3）改变了 structured output schema 与 prompt 语义：新增 current-turn
# coverage assessment（canonical coverage targets）。
# v4（PR5）改变了 prompt（KNOWLEDGE_EVIDENCE）、structured output（knowledge_grounding）、
# confidence 语义（grounded KNOWLEDGE 可解除 0.75 cap）与 SingleFlight 输入
# （grounding fingerprint：KB 重新索引后必须换 key）。
# SingleFlight 会把结果写入 Redis（result TTL 默认 600s），
# 版本号不变时滚动部署期间新代码会读到旧 evaluator 写入的缓存结果。
EVALUATOR_VERSION = "hybrid-evaluator-v4"

# ---------------- active dimensions & weights ----------------

#: 每个 question_type 真正激活的维度与权重（权重和为 1.0）
QUESTION_TYPE_DIMENSION_WEIGHTS: dict[str, dict[str, float]] = {
    "PROJECT": {"authenticity": 0.35, "technical_depth": 0.40, "communication_structure": 0.25},
    "KNOWLEDGE": {"knowledge_accuracy": 0.50, "technical_depth": 0.30, "communication_structure": 0.20},
    "SYSTEM_DESIGN": {"system_thinking": 0.45, "technical_depth": 0.35, "communication_structure": 0.20},
}

#: 未知 question_type 的兜底权重（按知识题处理）
FALLBACK_DIMENSION_WEIGHTS = QUESTION_TYPE_DIMENSION_WEIGHTS["KNOWLEDGE"]

DIMENSION_LABELS: dict[str, str] = {
    "authenticity": "个人职责与真实性",
    "technical_depth": "技术深度",
    "knowledge_accuracy": "知识准确性",
    "system_thinking": "系统设计思维",
    "communication_structure": "表达结构",
}


def active_dimension_weights(question_type: str) -> dict[str, float]:
    return QUESTION_TYPE_DIMENSION_WEIGHTS.get((question_type or "").upper(), FALLBACK_DIMENSION_WEIGHTS)


def normalize_evidence_text(text: str | None) -> str:
    """证据比对用的归一化：去掉所有空白并小写（对换行/缩进不敏感）。

    评分证据（PR2）与 coverage 证据（PR3）共用这一份实现，
    避免出现两套「相似但不一致」的 substring 校验。
    """
    return "".join(str(text or "").split()).lower()


def filter_active_dimension_scores(question_type: str, scores: dict[str, int]) -> dict[str, int]:
    """只保留当前 question_type 真正 active 的维度分。

    **所有** evaluation_method（HYBRID_LLM / HEURISTIC_FALLBACK / RULE_ONLY）都必须
    满足「dimension_scores 恰好等于 active dimensions」：

    - 旧 heuristic evaluator 为了兼容历史 dashboard 会同时返回 5 个维度；
    - 若 fallback 路径把它原样带出去，PROJECT 题就会凭空多出
      ``knowledge_accuracy`` / ``system_thinking`` 这类与本轮无关的假分，
      并且污染 report 的维度聚合。

    因此 deterministic / fallback / catastrophic fallback 一律经过这里收敛。
    """

    active = active_dimension_weights(question_type)
    return {dimension: int(scores[dimension]) for dimension in active if dimension in scores}


# ---------------- evidence ----------------

MAX_EVIDENCE_QUOTE_CHARS = 120
MAX_EVIDENCE_PER_DIMENSION = 3
MAX_EVIDENCE_TOTAL = 12
#: 低于该分数时，同一条原文证据的 assessment 记为 RISK（说明为什么不足）
EVIDENCE_SUPPORT_THRESHOLD = 60
#: 正常长度回答若一条有效证据都没有 → 该次语义评分不可信，回退 heuristic
MIN_ANSWER_CHARS_FOR_EVIDENCE = 40

# ---------------- calibration ----------------

#: 高分要求证据支撑，否则 cap
HIGH_SCORE_THRESHOLD = 85
HIGH_SCORE_CAP = 84
HIGH_SCORE_MIN_EVIDENCE = 2
HIGH_SCORE_MIN_DIMENSIONS = 2

# ---------------- guard ----------------

#: 极短回答阈值（字符数，code point 计）
VERY_SHORT_ANSWER_CHARS = 20
VERY_SHORT_CAP = 45
#: 明显泛化且无实现细节
GENERIC_CAP = 60
#: 明显替换题目/跑题
OFF_TOPIC_CAP = 45
#: 回答过短（不足以下结论）——与旧 heuristic 行为保持一致
SHORT_ANSWER_CHARS = 60
SHORT_CAP = 55

GUARD_EMPTY = "EMPTY"
GUARD_VERY_SHORT = "VERY_SHORT"
GUARD_SHORT = "SHORT"
GUARD_GENERIC = "GENERIC"
GUARD_OFF_TOPIC = "OFF_TOPIC"

# ---------------- confidence ----------------

RULE_ONLY_CONFIDENCE = 1.0
FALLBACK_CONFIDENCE = 0.35
#: KNOWLEDGE 本轮没有 RAG / reference answer factual grounding，置信度封顶
KNOWLEDGE_CONFIDENCE_CAP = 0.75
#: (最少有效证据条数, 置信度)
CONFIDENCE_TIERS: tuple[tuple[int, float], ...] = ((3, 0.90), (2, 0.80), (1, 0.65))

# ---------------- signals / feedback ----------------

MAX_SIGNAL_ITEMS = 5
MAX_SIGNAL_CHARS = 60
MAX_FEEDBACK_CHARS = 200
#: feedback 里「已讲到 / 下一步重点」单句的截断长度（比 signals 更短，保证 1~3 句）
FEEDBACK_STRENGTH_CHARS = 36
#: 不允许把「证据不足」写成「造假」这类越界判断
BANNED_SIGNAL_PHRASES = ("造假", "作弊", "欺骗", "根本不会", "显然不会", "完全不配")


# ---------------- LLM structured output ----------------


class LLMDimensionAssessment(BaseModel):
    dimension: str
    score: int = Field(ge=0, le=100)
    assessment: str = ""
    evidence_quotes: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class LLMCoverageAssessment(BaseModel):
    """**当前回答**对某个 canonical coverage target 的贡献（PR3）。

    只描述 CURRENT CANDIDATE ANSWER：previous turns 只用于理解上下文，
    不得把历史回答当作本轮 evidence。
    """

    target_key: str
    status: str = "NOT_COVERED"
    evidence_quotes: list[str] = Field(default_factory=list)


class LLMKnowledgeGroundingAssessment(BaseModel):
    """LLM 对「候选人回答 vs Knowledge Evidence」的语义判断（**未经校验**）。"""

    verdict: str = KNOWLEDGE_VERDICT_INSUFFICIENT
    evidence_ids: list[str] = Field(default_factory=list)
    candidate_quotes: list[str] = Field(default_factory=list)


class LLMEvaluationResult(BaseModel):
    dimensions: list[LLMDimensionAssessment] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    # PR3：与 dimensions 共用同一次 structured output，不额外增加 LLM 调用
    coverage: list[LLMCoverageAssessment] = Field(default_factory=list)
    # PR5：KNOWLEDGE 题的 factual grounding assessment（同为「软」字段）
    knowledge_grounding: LLMKnowledgeGroundingAssessment | None = None

    @field_validator("coverage", mode="before")
    @classmethod
    def _tolerate_malformed_coverage(cls, value):
        """把 coverage 的结构性错误与 dimensions 的严格校验隔离。

        coverage 是 PR3 新增的「软」字段：它哪怕是结构性 malformed（不是 list、
        元素不是 dict、元素 schema 不合法），也必须**保守降级为空**，而**绝不允许**
        让整次 ``LLMEvaluationResult`` 的 Pydantic 校验失败，否则会连带把已经可信的
        score（dimensions）打成 ``HEURISTIC_FALLBACK`` —— 这违反 PR3「score 与
        coverage 是两个独立失败域」的核心原则。

        dimensions 保持严格：本 validator 只作用于 coverage，不碰 dimensions。
        """
        if not isinstance(value, list):
            return []
        valid: list[LLMCoverageAssessment] = []
        for item in value:
            # 两种合法来源都要接受：raw JSON 解析出的 dict，以及代码内部直接构造的
            # LLMCoverageAssessment 实例（测试 / 组合路径）。
            if isinstance(item, LLMCoverageAssessment):
                valid.append(item)
                continue
            if not isinstance(item, dict):
                continue
            try:
                valid.append(LLMCoverageAssessment.model_validate(item))
            except Exception:
                continue
        return valid

    @field_validator("knowledge_grounding", mode="before")
    @classmethod
    def _tolerate_malformed_grounding(cls, value):
        """把 grounding 的结构性错误与 dimensions 的严格校验隔离（与 coverage 同一原则）。

        ``knowledge_grounding`` 不是 dict / schema 非法 → 保守降级为 ``None``，
        绝不能因此让整次 structured output 校验失败、把已经可信的 score 打成
        ``HEURISTIC_FALLBACK`` —— 语义评估与知识溯源是两个独立失败域。
        """
        if value is None or isinstance(value, LLMKnowledgeGroundingAssessment):
            return value
        if not isinstance(value, dict):
            return None
        try:
            return LLMKnowledgeGroundingAssessment.model_validate(value)
        except Exception:
            return None


# ---------------- snapshot / guard ----------------


class EvaluationSnapshot(BaseModel):
    """Evaluation 所需的不可变数据快照（全部为 plain scalar / DTO）。

    必须在独立 read session 内构造，**不得把 ORM entity 带出该 session**。
    """

    session_entity_id: int
    session_id: str
    user_id: int
    session_status: str
    interview_mode: str
    llm_provider: str | None = None

    topic: DynamicTopicDTO
    turn: DynamicTurnDTO
    previous_turns: list[DynamicTurnDTO] = Field(default_factory=list)

    #: PR5：E0 刚 load 出来时一定是 None；Grounding 完成后用 model_copy 注入，
    #: 再交给 hybrid evaluator。仍然是 plain DTO，不带 ORM。
    knowledge_grounding: KnowledgeGroundingDTO | None = None


@dataclass(frozen=True)
class GuardVerdict:
    """Deterministic hard guard 的结论。

    - ``hard_caps``：最终分上限集合（取最小值生效）
    - ``skip_semantic``：是否跳过 LLM semantic evaluation
    - ``rule_only``：是否属于 RULE_ONLY（空回答等硬失败）
    """

    flags: list[str] = field(default_factory=list)
    hard_caps: list[int] = field(default_factory=list)
    skip_semantic: bool = False
    rule_only: bool = False
    reason: str = ""

    @property
    def cap(self) -> int | None:
        return min(self.hard_caps) if self.hard_caps else None
