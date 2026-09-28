"""Canonical Coverage Targets 与 coverage 状态的确定性工具。

为什么要有这个模块
------------------

coverage 状态**不能**用自由文本 strengths/gaps 当 key：

- strengths/gaps 是 LLM 每轮生成的自由文本，同一件事每轮措辞都不同；
- 用自由文本累计无法判断「这个点到底问清楚了没有」，也无法跨轮去重；
- Planner 的 exit_criteria、Tracker 的合并逻辑、Policy 的目标选择如果各自维护
  一套字符串，语义一定会漂移。

因此这里定义**唯一来源**：每个 question_type 一组固定的 coverage target，
每个 target 带 ``key / label / description / intent / priority``。

- Planner 的 ``exit_criteria`` 从 ``label`` 生成（不再自己写死字符串）；
- Evaluator prompt / 校验从 ``description`` 与 ``key`` 生成；
- Policy 用 ``intent`` 决定追问方向、用 ``priority`` 决定同一状态下的优先顺序。

本模块只做纯计算，不查 DB、不调 LLM、不碰 ORM。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.modules.interview.context.models import FollowUpIntent
from app.modules.interview.schemas import (
    COVERAGE_STATUS_COVERED,
    COVERAGE_STATUS_NOT_COVERED,
    COVERAGE_STATUS_PARTIAL,
    TopicCoveragePointDTO,
    TopicCoverageStateDTO,
)

COVERAGE_STATE_VERSION = "topic-coverage-v1"

#: 每个 target 最多保留的 unique exact quote 数
MAX_EVIDENCE_PER_TARGET = 3
#: 单轮 LLM coverage 输出里，每个 target 最多接受的 quote 数
MAX_COVERAGE_QUOTES_PER_TURN = 2
#: 单个 quote 的最大字符数（与 PR2 评分证据保持一致）
MAX_COVERAGE_QUOTE_CHARS = 120


class CoverageTargetDefinition(BaseModel):
    """一个 canonical coverage target 的完整定义。"""

    key: str
    label: str
    description: str
    intent: str
    priority: int


# ---------------------------------------------------------------------------
# 唯一来源：QuestionType -> 有序 canonical targets
# ---------------------------------------------------------------------------

PROJECT_COVERAGE_TARGETS: tuple[CoverageTargetDefinition, ...] = (
    CoverageTargetDefinition(
        key="PROJECT_GOAL",
        label="能说清项目目标",
        description="是否说清了项目要解决什么问题、面向什么用户、达成什么目标",
        intent=FollowUpIntent.VERIFY_IMPLEMENTATION.value,
        priority=1,
    ),
    CoverageTargetDefinition(
        key="PROJECT_OWNERSHIP",
        label="能说明个人贡献",
        description="是否明确说明了本人负责、设计、实现或主导了什么",
        intent=FollowUpIntent.VERIFY_OWNERSHIP.value,
        priority=2,
    ),
    CoverageTargetDefinition(
        key="PROJECT_RESULT_VALIDATION",
        label="能给出结果或验证方式",
        description="是否给出了结果、指标、验证方式或上线前后比较",
        intent=FollowUpIntent.VERIFY_METRIC.value,
        priority=3,
    ),
    CoverageTargetDefinition(
        key="PROJECT_TRADEOFF_OR_FAILURE",
        label="能补充一个技术取舍或异常处理",
        description="是否说明了至少一个技术取舍、替代方案，或异常/失败时的处理方式",
        intent=FollowUpIntent.VERIFY_TRADEOFF.value,
        priority=4,
    ),
)

KNOWLEDGE_COVERAGE_TARGETS: tuple[CoverageTargetDefinition, ...] = (
    CoverageTargetDefinition(
        key="KNOWLEDGE_DEFINITION",
        label="能给出准确定义",
        description="是否给出了准确的概念定义或边界界定",
        intent=FollowUpIntent.VERIFY_IMPLEMENTATION.value,
        priority=1,
    ),
    CoverageTargetDefinition(
        key="KNOWLEDGE_MECHANISM",
        label="能说明核心机制",
        description="是否讲清了内部机制、执行流程或关键步骤",
        intent=FollowUpIntent.VERIFY_IMPLEMENTATION.value,
        priority=2,
    ),
    CoverageTargetDefinition(
        key="KNOWLEDGE_SCENARIO",
        label="能给出工程场景",
        description="是否给出了实际适用的工程场景或落地经验",
        intent=FollowUpIntent.VERIFY_IMPLEMENTATION.value,
        priority=3,
    ),
    CoverageTargetDefinition(
        key="KNOWLEDGE_BOUNDARY",
        label="能指出边界或风险",
        description="是否指出了限制、不适用场景、风险或易踩坑的边界条件",
        intent=FollowUpIntent.VERIFY_BOUNDARY.value,
        priority=4,
    ),
)

SYSTEM_DESIGN_COVERAGE_TARGETS: tuple[CoverageTargetDefinition, ...] = (
    CoverageTargetDefinition(
        key="SYSTEM_COMPONENTS",
        label="能拆分核心模块",
        description="是否拆出了核心模块/组件以及各自职责",
        intent=FollowUpIntent.VERIFY_IMPLEMENTATION.value,
        priority=1,
    ),
    CoverageTargetDefinition(
        key="SYSTEM_DATA_FLOW",
        label="能说明数据流",
        description="是否说明了请求/数据在主链路里的流向与关键节点",
        intent=FollowUpIntent.VERIFY_IMPLEMENTATION.value,
        priority=2,
    ),
    CoverageTargetDefinition(
        key="SYSTEM_RELIABILITY",
        label="能覆盖可靠性",
        description="是否覆盖了容错、降级、幂等、一致性或监控等可靠性设计",
        intent=FollowUpIntent.VERIFY_FAILURE.value,
        priority=3,
    ),
    CoverageTargetDefinition(
        key="SYSTEM_TRADEOFF",
        label="能说明至少一个取舍",
        description="是否说明了至少一个架构取舍及其代价",
        intent=FollowUpIntent.VERIFY_TRADEOFF.value,
        priority=4,
    ),
)

#: QuestionType -> canonical targets（顺序即 priority 升序）
COVERAGE_TARGETS_BY_QUESTION_TYPE: dict[str, tuple[CoverageTargetDefinition, ...]] = {
    "PROJECT": PROJECT_COVERAGE_TARGETS,
    "KNOWLEDGE": KNOWLEDGE_COVERAGE_TARGETS,
    "SYSTEM_DESIGN": SYSTEM_DESIGN_COVERAGE_TARGETS,
}

#: 未知 question_type 的兜底（按知识题处理，与 active dimension 权重口径一致）
FALLBACK_COVERAGE_TARGETS = KNOWLEDGE_COVERAGE_TARGETS


def coverage_targets_for(question_type: str | None) -> tuple[CoverageTargetDefinition, ...]:
    return COVERAGE_TARGETS_BY_QUESTION_TYPE.get((question_type or "").upper(), FALLBACK_COVERAGE_TARGETS)


def coverage_target_map(question_type: str | None) -> dict[str, CoverageTargetDefinition]:
    return {definition.key: definition for definition in coverage_targets_for(question_type)}


def canonical_target_keys(question_type: str | None) -> tuple[str, ...]:
    return tuple(definition.key for definition in coverage_targets_for(question_type))


def canonical_exit_criteria(question_type: str | None) -> list[str]:
    """Planner 的 exit_criteria 从 canonical label 生成，避免语义漂移。"""
    return [definition.label for definition in coverage_targets_for(question_type)]


def target_label(question_type: str | None, target_key: str | None) -> str | None:
    if not target_key:
        return None
    definition = coverage_target_map(question_type).get(target_key)
    return definition.label if definition else None


def target_intent(question_type: str | None, target_key: str | None) -> str | None:
    if not target_key:
        return None
    definition = coverage_target_map(question_type).get(target_key)
    return definition.intent if definition else None


# ---------------------------------------------------------------------------
# coverage status 语义与计算
# ---------------------------------------------------------------------------

#: NOT_COVERED = 0 / PARTIAL = 0.5 / COVERED = 1（固定，不随题型变化）
COVERAGE_STATUS_SCORE: dict[str, float] = {
    COVERAGE_STATUS_NOT_COVERED: 0.0,
    COVERAGE_STATUS_PARTIAL: 0.5,
    COVERAGE_STATUS_COVERED: 1.0,
}

#: 单调合并用的等级（只允许升，不允许降）
COVERAGE_STATUS_RANK: dict[str, int] = {
    COVERAGE_STATUS_NOT_COVERED: 0,
    COVERAGE_STATUS_PARTIAL: 1,
    COVERAGE_STATUS_COVERED: 2,
}

#: rank -> status（用于 max(rank) 之后还原）
COVERAGE_RANK_STATUS: dict[int, str] = {
    0: COVERAGE_STATUS_NOT_COVERED,
    1: COVERAGE_STATUS_PARTIAL,
    2: COVERAGE_STATUS_COVERED,
}


def merge_coverage_status(previous: str, current: str) -> str:
    """单调合并：``next = max(previous, current)``。

    允许 NOT_COVERED → PARTIAL → COVERED，
    禁止任何降级（COVERED 之后不会再回到 PARTIAL/NOT_COVERED）。
    contradiction 由 ``evaluation.signals.risks`` 表达，不通过 coverage 降级。
    """
    left = COVERAGE_STATUS_RANK.get(previous, 0)
    right = COVERAGE_STATUS_RANK.get(current, 0)
    return COVERAGE_RANK_STATUS[max(left, right)]


def coverage_ratio(points: dict[str, TopicCoveragePointDTO]) -> float:
    """覆盖度 = 各 target 得分之和 / target 数（NOT=0 / PARTIAL=0.5 / COVERED=1）。"""
    if not points:
        return 0.0
    total = sum(COVERAGE_STATUS_SCORE.get(point.status, 0.0) for point in points.values())
    return round(total / len(points), 4)


def is_complete(points: dict[str, TopicCoveragePointDTO]) -> bool:
    """**严格** complete：所有 target 都是 COVERED。

    刻意不使用 ``coverage_ratio >= 阈值`` 冒充 complete —— 少了任何一个
    criterion 都不算问清楚。
    """
    if not points:
        return False
    return all(point.status == COVERAGE_STATUS_COVERED for point in points.values())


def partition_keys(points: dict[str, TopicCoveragePointDTO]) -> tuple[list[str], list[str], list[str]]:
    covered: list[str] = []
    partial: list[str] = []
    unresolved: list[str] = []
    for key, point in points.items():
        if point.status == COVERAGE_STATUS_COVERED:
            covered.append(key)
        elif point.status == COVERAGE_STATUS_PARTIAL:
            partial.append(key)
        else:
            unresolved.append(key)
    return covered, partial, unresolved


def select_next_target(
    points: dict[str, TopicCoveragePointDTO],
    question_type: str | None,
) -> CoverageTargetDefinition | None:
    """next_target 优先级：NOT_COVERED > PARTIAL > COVERED（同状态内按 canonical priority）。

    全部 COVERED 时返回 ``None``。
    """
    for status in (COVERAGE_STATUS_NOT_COVERED, COVERAGE_STATUS_PARTIAL):
        for definition in coverage_targets_for(question_type):
            point = points.get(definition.key)
            if point is None or point.status == status:
                return definition
    return None


def build_coverage_state(
    points: dict[str, TopicCoveragePointDTO],
    question_type: str | None,
) -> TopicCoverageStateDTO:
    """从 points 重算派生字段（唯一入口，不要在别处手算）。"""
    covered, partial, unresolved = partition_keys(points)
    next_target = select_next_target(points, question_type)
    return TopicCoverageStateDTO(
        version=COVERAGE_STATE_VERSION,
        points=points,
        covered_keys=covered,
        partial_keys=partial,
        unresolved_keys=unresolved,
        coverage_ratio=coverage_ratio(points),
        complete=is_complete(points),
        next_target_key=next_target.key if next_target else None,
        next_target_label=next_target.label if next_target else None,
    )


def initial_coverage_points(question_type: str | None) -> dict[str, TopicCoveragePointDTO]:
    return {
        definition.key: TopicCoveragePointDTO(
            target_key=definition.key,
            label=definition.label,
            status=COVERAGE_STATUS_NOT_COVERED,
        )
        for definition in coverage_targets_for(question_type)
    }


# ---------------------------------------------------------------------------
# Label -> key 反查（用于把自由文本 kind 的输入映射回 canonical target）
# ---------------------------------------------------------------------------

LABEL_TO_TARGET_KEY: dict[str, str] = {
    definition.label: definition.key for targets in COVERAGE_TARGETS_BY_QUESTION_TYPE.values() for definition in targets
}
