"""Hybrid Answer Evaluator 包。

- ``models``：权重 / 阈值 / guard 常量 / LLM 结构化输出模型 / EvaluationSnapshot
- ``hybrid_evaluator``：Deterministic Guard + LLM Semantic Evaluator + Evidence Validation
  + Score Calibration + Heuristic Fallback

旧 `DynamicAnswerEvaluationService` 保持不变，继续承担 hard guard provider、
heuristic fallback 与 coach hint 三个职责。
"""

from app.modules.interview.evaluation.hybrid_evaluator import (
    HybridAnswerEvaluationService,
    HybridEvaluationOutcome,
)
from app.modules.interview.evaluation.models import (
    EVALUATOR_VERSION,
    QUESTION_TYPE_DIMENSION_WEIGHTS,
    EvaluationSnapshot,
    GuardVerdict,
    LLMDimensionAssessment,
    LLMEvaluationResult,
    active_dimension_weights,
)

__all__ = [
    "EVALUATOR_VERSION",
    "QUESTION_TYPE_DIMENSION_WEIGHTS",
    "EvaluationSnapshot",
    "GuardVerdict",
    "HybridAnswerEvaluationService",
    "HybridEvaluationOutcome",
    "LLMDimensionAssessment",
    "LLMEvaluationResult",
    "active_dimension_weights",
]
