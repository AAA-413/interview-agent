"""
QualityAgent - 质量检查 Agent

职责：
1. 验证执行结果的准确性
2. 检查答案的完整性
3. 评估内容的相关性
4. 判断是否需要重试
"""

import logging
from typing import Any, Dict, List, Optional

from app.common.ai.llm_provider_protocol import LLMProvider

logger = logging.getLogger(__name__)


class QualityAgent:
    """质量检查 Agent"""

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    async def check(
        self,
        user_input: str,
        execution_results: List[Dict[str, Any]],
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        检查执行结果质量

        Args:
            user_input: 用户输入
            execution_results: 执行结果列表
            plan: 任务计划

        Returns:
            质量检查结果，包含：
            - passed: 是否通过质检
            - score: 总分（0-100）
            - dimensions: 各维度评分
            - issues: 发现的问题
            - suggestions: 改进建议
        """
        logger.info("[QA] Starting quality check")
        logger.info(f"[QA] execution_results count: {len(execution_results)}")
        for i, r in enumerate(execution_results):
            logger.info(f"[QA] execution_results[{i}]: status={r.get('status')}, keys={list(r.keys())}")

        # 1. 检查执行状态
        all_success = all(r.get("status") == "success" for r in execution_results)
        if not all_success:
            failed_tasks = [r for r in execution_results if r.get("status") != "success"]
            return {
                "passed": False,
                "score": 0,
                "dimensions": {},
                "issues": [f"任务执行失败: {r.get('task_id')}" for r in failed_tasks],
                "suggestions": ["重新执行失败的任务"],
            }

        # 2. 整合执行结果
        integrated_result = self._integrate_results(execution_results)
        logger.info(f"[QA] integrated_result length: {len(integrated_result) if integrated_result else 0}")
        logger.info(f"[QA] integrated_result preview: {integrated_result[:200] if integrated_result else 'EMPTY'}")

        # 3. 多维度质量评估
        dimensions = await self._evaluate_dimensions(
            user_input=user_input,
            result=integrated_result,
            plan=plan,
        )

        # 4. 计算总分
        total_score = sum(dimensions.values()) / len(dimensions) if dimensions else 0

        # 5. 判断是否通过（降低阈值：总分 ≥50，各维度 ≥40）
        passed = total_score >= 50 and all(score >= 40 for score in dimensions.values())

        # 6. 生成问题和建议
        issues = self._identify_issues(dimensions)
        suggestions = self._generate_suggestions(dimensions, issues)

        logger.info(f"  质检结果: {'通过' if passed else '未通过'}, 总分: {total_score:.1f}")

        return {
            "passed": passed,
            "score": total_score,
            "dimensions": dimensions,
            "issues": issues,
            "suggestions": suggestions,
        }

    def _integrate_results(self, execution_results: List[Dict[str, Any]]) -> str:
        """整合执行结果"""
        integrated = []

        for result in execution_results:
            if result.get("status") == "success":
                task_result = result.get("result", {})

                if isinstance(task_result, dict):
                    # 提取主要内容
                    if "content" in task_result:
                        integrated.append(task_result["content"])
                    elif "answer" in task_result:
                        integrated.append(task_result["answer"])
                    elif "code" in task_result:
                        integrated.append(task_result["code"])
                    elif "design" in task_result:
                        integrated.append(task_result["design"])
                    elif "processed_data" in task_result:
                        integrated.append(str(task_result["processed_data"]))
                elif isinstance(task_result, str):
                    integrated.append(task_result)

        return "\n\n".join(integrated)

    async def _evaluate_dimensions(
        self,
        user_input: str,
        result: str,
        plan: Dict[str, Any],
    ) -> Dict[str, float]:
        """
        多维度评估

        Returns:
            各维度评分（0-100）：
            - accuracy: 准确性
            - completeness: 完整性
            - relevance: 相关性
            - clarity: 清晰度
        """
        try:
            prompt = f"""请评估以下回答的质量，从四个维度打分（0-100分）：

用户问题：{user_input}

回答内容：
{result[:2000]}  # 限制长度

评估维度：
1. accuracy（准确性）：回答是否准确、无错误
2. completeness（完整性）：回答是否完整、全面
3. relevance（相关性）：回答是否切题、相关
4. clarity（清晰度）：回答是否清晰、易懂

请以 JSON 格式返回评分：
{{
  "accuracy": 85,
  "completeness": 90,
  "relevance": 95,
  "clarity": 88
}}

只返回 JSON，不要其他内容。"""

            response = await self.llm_provider.chat(
                [{"role": "user", "content": prompt}]
            )

            content = response["content"]

            # 提取 JSON
            import json
            import re

            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                dimensions = json.loads(json_match.group())

                # 验证格式
                required_keys = ["accuracy", "completeness", "relevance", "clarity"]
                if all(key in dimensions for key in required_keys):
                    return {k: float(v) for k, v in dimensions.items()}

        except Exception as e:
            logger.warning(f"LLM 质量评估失败: {e}")

        # 降级方案：基于规则的评估
        return self._rule_based_evaluation(user_input, result)

    def _rule_based_evaluation(self, user_input: str, result: str) -> Dict[str, float]:
        """基于规则的质量评估"""
        dimensions = {}

        # 准确性：检查是否有明显错误标记
        error_indicators = ["错误", "不正确", "无法", "失败", "抱歉"]
        has_errors = any(indicator in result for indicator in error_indicators)
        dimensions["accuracy"] = 50 if has_errors else 80

        # 完整性：基于长度
        result_length = len(result)
        if result_length < 50:
            dimensions["completeness"] = 40
        elif result_length < 200:
            dimensions["completeness"] = 70
        else:
            dimensions["completeness"] = 85

        # 相关性：检查是否包含用户问题的关键词
        user_keywords = set(user_input.split())
        result_keywords = set(result.split())
        overlap = len(user_keywords & result_keywords) / len(user_keywords) if user_keywords else 0
        dimensions["relevance"] = min(100, overlap * 100 + 50)

        # 清晰度：检查结构化程度
        has_structure = any(marker in result for marker in ["1.", "2.", "-", "•", "##"])
        dimensions["clarity"] = 85 if has_structure else 70

        return dimensions

    def _identify_issues(self, dimensions: Dict[str, float]) -> List[str]:
        """识别质量问题"""
        issues = []

        if dimensions.get("accuracy", 0) < 70:
            issues.append("Accuracy insufficient: answer may contain errors or inaccurate information")

        if dimensions.get("completeness", 0) < 70:
            issues.append("Completeness insufficient: answer is not comprehensive, missing key information")

        if dimensions.get("relevance", 0) < 70:
            issues.append("Relevance insufficient: answer deviates from topic or not relevant enough")

        if dimensions.get("clarity", 0) < 70:
            issues.append("Clarity insufficient: answer is not clear or difficult to understand")

        return issues

    def _generate_suggestions(
        self,
        dimensions: Dict[str, float],
        issues: List[str],
    ) -> List[str]:
        """生成改进建议"""
        suggestions = []

        if dimensions.get("accuracy", 0) < 70:
            suggestions.append("Re-retrieve more accurate knowledge sources")
            suggestions.append("Use lower temperature parameter to improve accuracy")

        if dimensions.get("completeness", 0) < 70:
            suggestions.append("Expand answer content, supplement missing information")
            suggestions.append("Add more details and examples")

        if dimensions.get("relevance", 0) < 70:
            suggestions.append("Re-understand user intent, focus on core issues")
            suggestions.append("Filter irrelevant information, highlight key points")

        if dimensions.get("clarity", 0) < 70:
            suggestions.append("Optimize answer structure, use bullet points or paragraphs")
            suggestions.append("Simplify language, improve readability")

        if not suggestions:
            suggestions.append("质量良好，可以直接返回结果")

        return suggestions
