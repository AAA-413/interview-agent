"""Topic Coverage / TopicState / Adaptive Interview（PR3）。

模块划分：

- ``models.py``：canonical coverage targets（**唯一来源**）与 coverage 状态的
  纯计算工具（ratio / complete / 单调合并 / next_target）。
- ``tracker.py``：``TopicCoverageTracker`` 确定性 reducer，把「当前轮次的 coverage
  贡献」合并进 topic 级累计状态。

Covery DTO（``TopicCoveragePointDTO`` / ``TopicCoverageStateDTO`` / ``TopicStateDTO``）
放在 ``app.modules.interview.schemas``，与其它 API / 持久化共用 DTO 保持一致，
这里统一转出，调用方只 import 本包即可。
"""

from app.modules.interview.schemas import (
    TopicCoveragePointDTO,
    TopicCoverageStateDTO,
    TopicStateDTO,
)
from app.modules.interview.topic_state.models import (
    COVERAGE_STATE_VERSION,
    COVERAGE_STATUS_COVERED,
    COVERAGE_STATUS_NOT_COVERED,
    COVERAGE_STATUS_PARTIAL,
    COVERAGE_STATUS_RANK,
    COVERAGE_STATUS_SCORE,
    COVERAGE_TARGETS_BY_QUESTION_TYPE,
    CoverageTargetDefinition,
    build_coverage_state,
    canonical_exit_criteria,
    canonical_target_keys,
    coverage_ratio,
    coverage_target_map,
    coverage_targets_for,
    initial_coverage_points,
    is_complete,
    merge_coverage_status,
    select_next_target,
    target_intent,
    target_label,
)
from app.modules.interview.topic_state.tracker import (
    HEURISTIC_COVERAGE_MARKERS,
    TopicCoverageTracker,
    topic_coverage_tracker,
)

__all__ = [
    "COVERAGE_STATE_VERSION",
    "COVERAGE_STATUS_COVERED",
    "COVERAGE_STATUS_NOT_COVERED",
    "COVERAGE_STATUS_PARTIAL",
    "COVERAGE_STATUS_RANK",
    "COVERAGE_STATUS_SCORE",
    "COVERAGE_TARGETS_BY_QUESTION_TYPE",
    "HEURISTIC_COVERAGE_MARKERS",
    "CoverageTargetDefinition",
    "TopicCoveragePointDTO",
    "TopicCoverageStateDTO",
    "TopicCoverageTracker",
    "TopicStateDTO",
    "build_coverage_state",
    "canonical_exit_criteria",
    "canonical_target_keys",
    "coverage_ratio",
    "coverage_target_map",
    "coverage_targets_for",
    "initial_coverage_points",
    "is_complete",
    "merge_coverage_status",
    "select_next_target",
    "target_intent",
    "target_label",
    "topic_coverage_tracker",
]
