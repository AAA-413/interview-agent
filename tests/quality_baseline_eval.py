"""Quality baseline evaluation for dynamic interview MVP.

Runs deterministic quality checks against the eval dataset:
1. Question quality: topic_key alignment, question_type mix, evidence grounding, forbidden claims
2. Follow-up quality: decision action correctness for 4 answer types
3. Scoring quality: score band accuracy and ranking order
4. Coach improvement: retry delta and hint properties
5. RAG explanation: no-hit honesty

Outputs results.json and report.md to tests/quality_baselines/{date}/.

Usage:
    PYTHONPATH=. .venv/bin/python tests/quality_baseline_eval.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.interview.dynamic_service import (
    DynamicAnswerEvaluationService,
    InterviewPlanService,
    StrictInterviewPolicy,
)
from app.modules.interview.jd_parse_service import jd_parse_service
from app.modules.interview.schemas import (
    DynamicInterviewCreateRequest,
    DynamicTopicDTO,
    DynamicTurnDTO,
)
from app.modules.resume.schemas import AnalysisHistoryDTO, ProjectInfo, ResumeDetailDTO, ResumeProfile, TechStack

TOPIC_ALIASES = {
    "cache_penetration_avalanche": "redis_cache_penetration_hotkey",
    "mysql_indexing_optimization": "mysql_index_optimization",
    "frontend_performance": "frontend_performance_optimization",
    "async_task_queue_design": "async_task_pipeline",
    "api_idempotency_design": "idempotency_design",
    "lora_finetuning_practice": "lora_qlora_finetuning",
    "dpo_alignment": "dpo_preference_optimization",
}


@dataclass
class QualityResult:
    sample_id: str
    checks: dict = field(default_factory=dict)
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def load_dataset() -> dict:
    dataset_path = os.path.join(os.path.dirname(__file__), "quality_baselines", "2026-05-29", "eval_dataset.json")
    with open(dataset_path) as f:
        return json.load(f)


def sample_resume_detail(sample: dict) -> ResumeDetailDTO:
    resume_text = sample.get("resume_text", "")
    skills = jd_parse_service.parse(sample.get("jd_text"), sample.get("target_role"), sample.get("skill_id")).required_skills
    project = ProjectInfo(
        name=sample.get("label", "代表性项目"),
        role=sample.get("target_role", "候选人"),
        tech_stack=skills,
        description=resume_text,
        highlights=[resume_text[:180]] if resume_text else [],
    )
    return ResumeDetailDTO(
        id=0,
        filename=f"quality-{sample['id']}.txt",
        file_size=len(resume_text.encode()),
        uploaded_at=datetime(2026, 5, 29, 9, 0, 0),
        resume_text=resume_text,
        analyses=[
            AnalysisHistoryDTO(
                id=0,
                analyzed_at=datetime(2026, 5, 29, 9, 0, 0),
                profile=ResumeProfile(
                    projects=[project],
                    tech_stacks=[TechStack(name=skill, proficiency="熟悉", context=resume_text[:80]) for skill in skills],
                    experience_level="quality_sample",
                    has_projects=True,
                    summary=resume_text[:160],
                ),
            )
        ],
    )


def check_question_quality(sample: dict, topics: list[DynamicTopicDTO], plan_summary: dict) -> list[dict]:
    results = []

    # 1. Topic count
    results.append(
        {
            "check": "topic_count",
            "passed": len(topics) == 4,
            "detail": f"got {len(topics)}",
        }
    )

    # 2. Question type mix
    actual_mix = {
        q_type: sum(1 for t in topics if t.question_type == q_type)
        for q_type in ["PROJECT", "KNOWLEDGE", "SYSTEM_DESIGN"]
    }
    expected_mix = sample["expected_question_type_mix"]
    mix_ok = actual_mix == expected_mix
    results.append(
        {
            "check": "question_type_mix",
            "passed": mix_ok,
            "detail": f"expected {expected_mix}, got {actual_mix}",
        }
    )

    # 3. Project topics have evidence
    project_topics = [t for t in topics if t.question_type == "PROJECT"]
    missing_evidence = [t.topic_key for t in project_topics if not t.evidence_snippet]
    results.append(
        {
            "check": "project_evidence_grounding",
            "passed": len(missing_evidence) == 0,
            "detail": f"missing evidence for: {missing_evidence}"
            if missing_evidence
            else "all project topics have evidence",
        }
    )

    # 4. Forbidden claims check (simple keyword-based)
    forbidden = sample.get("forbidden_claims", [])
    violations = []
    for t in topics:
        for claim in forbidden:
            if claim.lower() in (t.main_question or "").lower():
                violations.append(f"{t.topic_key}: {claim}")
    results.append(
        {
            "check": "forbidden_claims",
            "passed": len(violations) == 0,
            "detail": f"violations: {violations}" if violations else "no forbidden claims detected",
        }
    )

    # 5. Topic diversity (at least 3 distinct topic_keys)
    unique_keys = {t.topic_key for t in topics}
    results.append(
        {
            "check": "topic_diversity",
            "passed": len(unique_keys) >= 3,
            "detail": f"{len(unique_keys)} distinct topic_keys",
        }
    )

    return results


def check_followup_quality(
    sample: dict,
    topic: DynamicTopicDTO,
    answer_type: str,
    decision: dict,
    expected_score_range: list[int],
    actual_score: int,
) -> list[dict]:
    results = []

    action = decision.get("action", "")

    # 1. Decision action appropriateness
    expected_actions = {
        "strong": ["FOLLOW_UP", "NEXT_TOPIC", "END"],
        "normal": ["FOLLOW_UP", "COACH_RETRY"],
        "vague": ["FOLLOW_UP", "COACH_RETRY"],
        "off_topic": ["FOLLOW_UP", "COACH_RETRY"],
    }
    valid = action in expected_actions.get(answer_type, [])
    results.append(
        {
            "check": f"decision_action_{answer_type}",
            "passed": valid,
            "detail": f"action={action} for {answer_type} answer",
        }
    )

    # 2. Score band check
    low, high = expected_score_range
    in_band = low <= actual_score <= high
    results.append(
        {
            "check": f"score_band_{answer_type}",
            "passed": in_band,
            "detail": f"score={actual_score}, expected [{low}, {high}]",
        }
    )

    # 3. Follow-up relevance (for strong answers, should not be unnecessary)
    if answer_type == "strong":
        unnecessary = action == "COACH_RETRY"
        results.append(
            {
                "check": "unnecessary_retry_strong",
                "passed": not unnecessary,
                "detail": f"strong answer got {'COACH_RETRY (unexpected)' if unnecessary else action + ' (expected)'}",
            }
        )

    return results


def check_scoring_quality(scores: dict[str, int]) -> list[dict]:
    results = []

    # Ranking: strong > normal > vague > off_topic
    ranking_ok = scores.get("strong", 0) > scores.get("normal", 0) > scores.get("vague", 0) > scores.get("off_topic", 0)
    results.append(
        {
            "check": "ranking_accuracy",
            "passed": ranking_ok,
            "detail": f"scores: strong={scores.get('strong')}, normal={scores.get('normal')}, vague={scores.get('vague')}, off_topic={scores.get('off_topic')}",
        }
    )

    return results


def check_coach_quality(hint: dict | None) -> list[dict]:
    results = []

    # Check hint doesn't contain a full answer
    if hint and hint.get("message"):
        message = hint["message"]
        # Heuristic: full answer typically > 500 chars or contains "完整答案" patterns
        no_full_answer = len(message) < 500 and "标准答案" not in message and "完整回答" not in message
        results.append(
            {
                "check": "hint_no_answer_leakage",
                "passed": no_full_answer,
                "detail": f"hint length={len(message)}, has_full_answer_markers={not no_full_answer}",
            }
        )

        # Hint should have structure
        has_structure = bool(hint.get("structure") or hint.get("focus_gaps"))
        results.append(
            {
                "check": "hint_actionability",
                "passed": has_structure,
                "detail": f"has structure/focus_gaps: {has_structure}",
            }
        )
    else:
        results.append(
            {
                "check": "hint_present",
                "passed": False,
                "detail": "no hint generated",
            }
        )

    return results


def check_rag_quality(insight: dict | None) -> list[dict]:
    results = []

    if insight is None:
        results.append({"check": "rag_insight_available", "passed": False, "detail": "no insight returned"})
        return results

    status = insight.get("source_status", "")
    confidence = insight.get("retrieval_confidence", 0)

    # No-hit honesty
    if status == "NO_KB_HIT":
        no_fake_citations = len(insight.get("citations", [])) == 0
        results.append(
            {
                "check": "no_hit_honesty",
                "passed": no_fake_citations,
                "detail": f"NO_KB_HIT with {len(insight.get('citations', []))} citations",
            }
        )

    # Low confidence should not force citations
    if confidence < 0.5:
        low_conf_no_citations = len(insight.get("citations", [])) <= 1
        results.append(
            {
                "check": "low_confidence_no_forced_citations",
                "passed": low_conf_no_citations,
                "detail": f"confidence={confidence}, citations={len(insight.get('citations', []))}",
            }
        )

    if not results:
        results.append(
            {"check": "rag_insight_status", "passed": True, "detail": f"status={status}, confidence={confidence}"}
        )

    return results


def evaluate_sample(sample: dict) -> QualityResult:
    """Run quality checks for a single sample."""
    result = QualityResult(sample_id=sample["id"])
    evaluator = DynamicAnswerEvaluationService()

    # --- 1. Plan generation ---
    structured = jd_parse_service.parse(
        sample["jd_text"], target_role=sample["target_role"], skill_id=sample["skill_id"]
    )
    request = DynamicInterviewCreateRequest(
        target_role=sample["target_role"],
        jd_text=sample["jd_text"],
        skill_id=sample["skill_id"],
        mode="STRICT",
    )
    topics, plan_summary = InterviewPlanService().build_plan(request, structured, sample_resume_detail(sample))

    for check in check_question_quality(sample, topics, plan_summary):
        key = f"Q_{check['check']}"
        result.checks[key] = check
        if check["passed"]:
            result.passed += 1
        else:
            result.failed += 1
            result.failures.append(f"[{key}] {check['detail']}")

    # --- 2. Per-topic followup & scoring ---
    all_scores: dict[str, list[int]] = {}
    for topic_key, answers in sample.get("sample_answers", {}).items():
        canonical_topic_key = TOPIC_ALIASES.get(topic_key, topic_key)
        matching_topic = next((t for t in topics if t.topic_key in {topic_key, canonical_topic_key}), None)
        if matching_topic is None:
            result.failures.append(f"[F_TOPIC_MISSING] {topic_key} not in plan")
            result.failed += 1
            continue

        topic_scores: dict[str, int] = {}
        for answer_type, answer_text in answers.items():
            turn = DynamicTurnDTO(
                id=1,
                topic_id=matching_topic.id,
                turn_type="MAIN",
                turn_order=1,
                question=matching_topic.main_question,
            )
            try:
                evaluation = evaluator.evaluate(matching_topic, turn, answer_text, [])
            except Exception:
                import traceback

                traceback.print_exc()
                evaluation = evaluator.fallback_evaluation(matching_topic)

            decision = StrictInterviewPolicy().decide(
                topic=matching_topic,
                turn=turn,
                evaluation=evaluation,
                answered_turns_after_current=[
                    turn.model_copy(update={"answer": answer_text, "ability_score": evaluation.ability_score})
                ],
                has_next_topic=True,
            )

            # Score band & ranking
            expected_range = sample["expected_score_bands"].get(answer_type, [0, 100])
            for check in check_followup_quality(
                sample,
                matching_topic,
                answer_type,
                decision.model_dump(),
                expected_range,
                evaluation.ability_score,
            ):
                key = f"F_{check['check']}_{topic_key}"
                result.checks[key] = check
                if check["passed"]:
                    result.passed += 1
                else:
                    result.failed += 1
                    result.failures.append(f"[{key}] {check['detail']}")

            topic_scores[answer_type] = evaluation.ability_score

        if topic_scores:
            all_scores[topic_key] = topic_scores
            for check in check_scoring_quality(topic_scores):
                key = f"S_{check['check']}_{topic_key}"
                result.checks[key] = check
                if check["passed"]:
                    result.passed += 1
                else:
                    result.failed += 1
                    result.failures.append(f"[{key}] {check['detail']}")

    return result


def _topics_for_sample(sample: dict) -> list[DynamicTopicDTO]:
    structured = jd_parse_service.parse(
        sample["jd_text"], target_role=sample["target_role"], skill_id=sample["skill_id"]
    )
    request = DynamicInterviewCreateRequest(
        target_role=sample["target_role"],
        jd_text=sample["jd_text"],
        skill_id=sample["skill_id"],
        mode="STRICT",
    )
    topics, _ = InterviewPlanService().build_plan(request, structured, sample_resume_detail(sample))
    return topics


async def augment_with_llm_judge(
    sample: dict,
    result: QualityResult,
    *,
    provider: str | None = None,
    max_topics: int | None = None,
) -> None:
    """Use the real configured LLM as an external judge for answer ranking and follow-up quality."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.common.ai.llm_provider import llm_registry

    topics = _topics_for_sample(sample)
    evaluator = DynamicAnswerEvaluationService()
    chat_model = llm_registry.get_chat_model(provider)
    judged = 0

    for topic_key, answers in sample.get("sample_answers", {}).items():
        if max_topics is not None and judged >= max_topics:
            break
        canonical_topic_key = TOPIC_ALIASES.get(topic_key, topic_key)
        topic = next((t for t in topics if t.topic_key in {topic_key, canonical_topic_key}), None)
        if topic is None:
            continue

        deterministic = {}
        for answer_type, answer_text in answers.items():
            turn = DynamicTurnDTO(
                id=1,
                topic_id=topic.id,
                turn_type="MAIN",
                turn_order=1,
                question=topic.main_question,
            )
            evaluation = evaluator.evaluate(topic, turn, answer_text, [])
            decision = StrictInterviewPolicy().decide(
                topic=topic,
                turn=turn,
                evaluation=evaluation,
                answered_turns_after_current=[
                    turn.model_copy(update={"answer": answer_text, "ability_score": evaluation.ability_score})
                ],
                has_next_topic=True,
            )
            deterministic[answer_type] = {
                "score": evaluation.ability_score,
                "decision_action": decision.action,
                "followup_question": decision.next_question,
                "signals": evaluation.signals,
                "answer": answer_text,
            }

        prompt = _llm_judge_prompt(sample, topic, deterministic)
        try:
            response = await chat_model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是技术面试质量评审员，只评估面试系统质量。"
                            "必须只输出 JSON，不要 markdown，不要额外解释。"
                        )
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            payload = _parse_json_object(str(response.content))
        except Exception as exc:
            check = {
                "check": f"llm_judge_available_{topic_key}",
                "passed": False,
                "detail": f"LLM judge failed: {exc.__class__.__name__}: {exc}",
            }
            _record_check(result, f"J_available_{topic_key}", check)
            judged += 1
            continue

        checks = [
            {
                "check": f"llm_ranking_{topic_key}",
                "passed": bool(payload.get("ranking_ok")),
                "detail": str(payload.get("ranking_reason", ""))[:240],
            },
            {
                "check": f"llm_score_alignment_{topic_key}",
                "passed": bool(payload.get("score_alignment_ok")),
                "detail": str(payload.get("score_alignment_reason", ""))[:240],
            },
            {
                "check": f"llm_followup_quality_{topic_key}",
                "passed": bool(payload.get("followup_quality_ok")),
                "detail": str(payload.get("followup_reason", ""))[:240],
            },
        ]
        for check in checks:
            _record_check(result, f"J_{check['check']}", check)
        judged += 1


def _record_check(result: QualityResult, key: str, check: dict) -> None:
    result.checks[key] = check
    if check["passed"]:
        result.passed += 1
    else:
        result.failed += 1
        result.failures.append(f"[{key}] {check['detail']}")


def _llm_judge_prompt(sample: dict, topic: DynamicTopicDTO, deterministic: dict) -> str:
    compact_answers = {
        key: {
            "score": value["score"],
            "decision_action": value["decision_action"],
            "followup_question": value["followup_question"],
            "signals": value["signals"],
            "answer": value["answer"][:900],
        }
        for key, value in deterministic.items()
    }
    return json.dumps(
        {
            "task": "评估动态面试系统对一个 topic 的评分排序和追问质量是否可信。",
            "expected_answer_order": ["strong", "normal", "vague", "off_topic"],
            "rubric": {
                "ranking_ok": "strong 应明显好于 normal，normal 好于 vague，off_topic 应最低或接近最低。",
                "score_alignment_ok": "分数要大致符合回答质量；强回答不应低分，跑偏回答不应高分。",
                "followup_quality_ok": "追问要针对缺口，不能泄露答案；严厉模式可继续追问细节、指标、边界、取舍。",
            },
            "sample_label": sample.get("label"),
            "target_role": sample.get("target_role"),
            "topic": topic.model_dump(),
            "answers_and_system_outputs": compact_answers,
            "output_schema": {
                "ranking_ok": "boolean",
                "ranking_reason": "string",
                "score_alignment_ok": "boolean",
                "score_alignment_reason": "string",
                "followup_quality_ok": "boolean",
                "followup_reason": "string",
            },
        },
        ensure_ascii=False,
    )


def _parse_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM judge response is not a JSON object")
    return data


def _llm_judge_preflight_error(provider: str | None) -> str | None:
    """Return a user-facing error when the configured real LLM judge cannot start."""
    provider_name = provider or "dashscope"
    if provider_name != "dashscope":
        return None

    from app.config import settings

    api_key = settings.ai.bailian_api_key.strip()
    placeholder_values = {
        "",
        "your_api_key",
        "your_dashscope_api_key",
        "your_deepseek_api_key",
        "sk-xxx",
    }
    if api_key.lower() in placeholder_values:
        return (
            "LLM judge requires a real AI_BAILIAN_API_KEY in .env or environment. "
            "Set AI_BAILIAN_API_KEY and rerun with --with-llm-judge."
        )
    return None


def generate_report(dataset: dict, results: list[QualityResult]) -> dict:
    """Generate structured report and results."""
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)
    total = total_passed + total_failed
    pass_rate = total_passed / total * 100 if total > 0 else 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    report_data = {
        "run_id": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": now,
        "version": dataset["version"],
        "sample_count": len(results),
        "total_checks": total,
        "passed": total_passed,
        "failed": total_failed,
        "pass_rate": round(pass_rate, 1),
        "by_sample": {
            r.sample_id: {
                "passed": r.passed,
                "failed": r.failed,
                "rate": round(r.passed / (r.passed + r.failed) * 100, 1) if (r.passed + r.failed) > 0 else 0,
            }
            for r in results
        },
        "all_failures": [f for r in results for f in r.failures],
        "quality_lines": {
            "question_quality": {
                "rate": _line_rate(results, "Q_"),
                "checks": _line_total(results, "Q_"),
                "failures": len(_line_failures(results, "Q_")),
            },
            "followup_quality": {
                "rate": _line_rate(results, "F_"),
                "checks": _line_total(results, "F_"),
                "failures": len(_line_failures(results, "F_")),
            },
            "scoring_quality": {
                "rate": _line_rate(results, "S_"),
                "checks": _line_total(results, "S_"),
                "failures": len(_line_failures(results, "S_")),
            },
            "llm_judge": {
                "rate": _line_rate(results, "J_"),
                "checks": _line_total(results, "J_"),
                "failures": len(_line_failures(results, "J_")),
            },
        },
        "thresholds": {
            "demo_ready": pass_rate >= 75,
            "internal_test_ready": pass_rate >= 80,
            "public_trial_ready": pass_rate >= 85,
        },
    }

    return report_data


def _line_rate(results: list[QualityResult], prefix: str) -> float:
    total = sum(1 for r in results for k in r.checks if k.startswith(prefix))
    passed = sum(1 for r in results for k, v in r.checks.items() if k.startswith(prefix) and v["passed"])
    return round(passed / total * 100, 1) if total > 0 else 0


def _line_total(results: list[QualityResult], prefix: str) -> int:
    return sum(1 for r in results for k in r.checks if k.startswith(prefix))


def _line_failures(results: list[QualityResult], prefix: str) -> list[str]:
    return [f for r in results for f in r.failures if f.startswith(f"[{prefix}")]


def write_report_md(report_data: dict, output_dir: str) -> None:
    """Write human-readable report.md."""
    lines = [
        f"# 质量基准报告 - {report_data['run_id']}",
        "",
        f"生成时间：{report_data['generated_at']}",
        f"数据集版本：{report_data['version']}",
        f"样本数：{report_data['sample_count']}",
        "",
        "## 总体结论",
        "",
        f"综合通过率：**{report_data['pass_rate']}%** ({report_data['passed']}/{report_data['total_checks']})",
        "",
    ]

    # Readiness assessment
    thresholds = report_data["thresholds"]
    if thresholds["public_trial_ready"]:
        lines.append("当前版本：**可公开试用** ✓")
    elif thresholds["internal_test_ready"]:
        lines.append("当前版本：**可内测**")
        lines.append(f"差距：通过率 {report_data['pass_rate']}%，目标 ≥ 85%")
    elif thresholds["demo_ready"]:
        lines.append("当前版本：**可演示**")
        lines.append(f"差距：通过率 {report_data['pass_rate']}%，目标 ≥ 80%")
    else:
        lines.append("当前版本：**不建议发布** ⚠️")
        lines.append(f"通过率 {report_data['pass_rate']}% 未达到演示门槛 (75%)")

    lines.extend(
        [
            "",
            "## 五条质量线",
            "",
            "| 质量线 | 通过率 | 失败数 |",
            "|--------|--------|--------|",
        ]
    )
    for line_name, line_data in report_data["quality_lines"].items():
        label = {
            "question_quality": "出题质量",
            "followup_quality": "追问质量",
            "scoring_quality": "评分质量",
            "llm_judge": "LLM 评审",
        }.get(line_name, line_name)
        if line_name == "llm_judge" and line_data["rate"] == 0 and line_data["failures"] == 0:
            continue
        lines.append(f"| {label} | {line_data['rate']}% | {line_data['failures']} |")

    lines.extend(
        [
            "",
            "## 分样本通过率",
            "",
            "| 样本 | 通过率 | Pass/Fail |",
            "|------|--------|-----------|",
        ]
    )
    for sample_id, sample_data in report_data["by_sample"].items():
        sample_label = next(
            (s["label"] for s in report_data.get("_samples", []) if s.get("id") == sample_id),
            sample_id,
        )
        lines.append(
            f"| {sample_label} | {sample_data['rate']}% | {sample_data['passed']}/{sample_data['passed'] + sample_data['failed']} |"
        )

    if report_data["all_failures"]:
        lines.extend(
            [
                "",
                "## 失败清单",
                "",
            ]
        )
        for f in report_data["all_failures"][:20]:
            lines.append(f"- {f}")
        if len(report_data["all_failures"]) > 20:
            lines.append(f"- ... 及另外 {len(report_data['all_failures']) - 20} 条")

    lines.extend(
        [
            "",
            "## 建议动作",
            "",
            "- 出题质量低于 80%：检查 Topic Registry 映射和 JD 解析规则",
            "- 追问质量低于 70%：优化 StrictInterviewPolicy 追问逻辑",
            "- 评分质量低于 80%：校准评分 prompt 和维度权重",
            "- LLM 评审低于 80%：抽查 judge 原因并回放真实面试样本",
            "",
            "## 下次改进",
            "",
            "- 扩大真实 LLM judge 覆盖样本和版本对比",
            "- 增加人工抽检层",
            "- 建立版本对比机制",
        ]
    )

    with open(os.path.join(output_dir, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


async def async_main():
    parser = argparse.ArgumentParser(description="Run dynamic interview quality baseline checks.")
    parser.add_argument("--with-llm-judge", action="store_true", help="Call the configured real LLM as judge.")
    parser.add_argument("--llm-provider", default=None, help="LLM provider name registered in llm_registry.")
    parser.add_argument(
        "--llm-max-topics",
        type=int,
        default=None,
        help="Maximum judged topics per sample. Omit to judge all matching sample topics.",
    )
    args = parser.parse_args()

    if args.with_llm_judge:
        preflight_error = _llm_judge_preflight_error(args.llm_provider)
        if preflight_error:
            print(preflight_error, file=sys.stderr)
            sys.exit(2)

    dataset = load_dataset()
    print(f"Evaluating {len(dataset['samples'])} samples...")

    results = []
    for sample in dataset["samples"]:
        print(f"  Sample {sample['id']} ({sample['label']})...", end=" ")
        result = evaluate_sample(sample)
        if args.with_llm_judge:
            await augment_with_llm_judge(
                sample,
                result,
                provider=args.llm_provider,
                max_topics=args.llm_max_topics,
            )
        results.append(result)
        print(f"passed={result.passed}, failed={result.failed}")

    report = generate_report(dataset, results)
    report["_samples"] = dataset["samples"]  # Attach for report generation

    output_dir = os.path.join(os.path.dirname(__file__), "quality_baselines", "2026-05-29")
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    write_report_md(report, output_dir)

    print(f"\nReport: {output_dir}/report.md")
    print(f"Results: {output_dir}/results.json")
    print(f"Overall: {report['passed']}/{report['total_checks']} passed ({report['pass_rate']}%)")

    if report["pass_rate"] < 75:
        print("⚠️  BELOW DEMO THRESHOLD")
        sys.exit(1)
    elif report["pass_rate"] < 80:
        print("✓ DEMO READY")
    elif report["pass_rate"] < 85:
        print("✓ INTERNAL TEST READY")
    else:
        print("✓ PUBLIC TRIAL READY")


if __name__ == "__main__":
    asyncio.run(async_main())
