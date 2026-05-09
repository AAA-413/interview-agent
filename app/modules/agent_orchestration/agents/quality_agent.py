"""
QualityAgent - 质量检查 Agent（智能下载场景优化版）

两阶段评估架构：
- Phase A：逐任务规则评估（0次LLM调用）→ 检查下载成功、内容实质性、主题相关性
- Phase B：整体质量评估（1次LLM调用）→ 检查覆盖度、多样性

返回值新增字段：
- failed_task_indices: Phase A 识别的失败任务索引列表
- per_task_results: 每个任务的评估详情
- overall_issues: Phase B 发现的整体问题（传递给整合阶段，不触发重试）
"""

import logging
import re
from typing import Any, Dict, List, Optional

from app.common.ai.llm_provider_protocol import LLMProvider

logger = logging.getLogger(__name__)

# 模板内容关键词（用于检测低质量页面）
_BOILERPLATE_KEYWORDS = [
    "cookie", "privacy", "copyright", "terms of service", "all rights reserved",
    "cookie政策", "隐私政策", "版权声明", "版权所有", "用户协议",
    "navigation", "menu", "sidebar", "footer", "header",
    "导航", "菜单", "侧边栏", "页脚", "页眉",
    "subscribe", "newsletter", "sign up", "log in", "register",
    "订阅", "登录", "注册",
]

# 单任务通过阈值
_SUBSTANCE_PASS_THRESHOLD = 40
_RELEVANCE_PASS_THRESHOLD = 30
# 整体通过比例阈值
_PASS_RATIO_THRESHOLD = 0.5


class QualityAgent:
    """质量检查 Agent（智能下载场景优化版）"""

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    async def check(
        self,
        user_input: str,
        execution_results: List[Dict[str, Any]],
        plan: Dict[str, Any],
        expanded_keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        两阶段质量检查

        Args:
            user_input: 用户输入
            execution_results: 执行结果列表
            plan: 任务计划
            expanded_keywords: Phase B 输出的扩展关键词（重试时传入，提升 Phase A 匹配率）

        Returns:
            质量检查结果，包含：
            - passed: 是否通过质检
            - score: 总分（0-100）
            - failed_task_indices: Phase A 识别的失败任务索引列表
            - per_task_results: 每个任务的评估详情
            - overall_issues: Phase B 发现的整体问题
            - expanded_keywords: Phase B 输出的扩展关键词（供重试时使用）
            - issues: 兼容旧格式的问题列表
            - suggestions: 改进建议
        """
        logger.info("[QA] Starting two-phase quality check")
        logger.info("[QA] execution_results count: %d", len(execution_results))

        if not execution_results:
            return self._build_result(passed=False, score=0, issues=["没有执行结果"], failed_task_indices=[])

        # ============================================================
        # Phase A: 逐任务规则评估（0次LLM调用）
        # ============================================================
        per_task_results = self._evaluate_all_tasks(execution_results, user_input, expanded_keywords)
        passed_count = sum(1 for r in per_task_results if r["passed"])
        total_count = len(per_task_results)
        pass_ratio = passed_count / total_count if total_count > 0 else 0

        failed_task_indices = [r["task_index"] for r in per_task_results if not r["passed"]]

        logger.info("[QA] Phase A: %d/%d tasks passed (%.0f%%), failed_indices=%s",
                     passed_count, total_count, pass_ratio * 100, failed_task_indices)

        # 如果 <50% 任务通过 → 直接判定失败，不调 LLM
        if pass_ratio < _PASS_RATIO_THRESHOLD:
            issues = [r["reason"] for r in per_task_results if not r["passed"] and r["reason"]]
            return self._build_result(
                passed=False,
                score=int(pass_ratio * 100),
                issues=issues or [f"只有 {passed_count}/{total_count} 个任务通过质量检查"],
                failed_task_indices=failed_task_indices,
                per_task_results=per_task_results,
            )

        # 全部任务通过 → 跳过 Phase B，直接通过
        if not failed_task_indices and pass_ratio == 1.0:
            avg_substance = self._avg_score(per_task_results, "content_substance")
            avg_relevance = self._avg_score(per_task_results, "topic_relevance")
            score = int((avg_substance + avg_relevance) / 2)
            return self._build_result(
                passed=True,
                score=score,
                failed_task_indices=[],
                per_task_results=per_task_results,
            )

        # ============================================================
        # Phase B: 整体质量评估（1次LLM调用）
        # ============================================================
        # 只对通过 Phase A 的结果做整体评估
        passed_results = [r for r in per_task_results if r["passed"]]
        overall_result = await self._evaluate_overall(passed_results, user_input)

        # 计算总分：Phase A 平均分 * 0.6 + Phase B 分数 * 0.4
        avg_substance = self._avg_score(per_task_results, "content_substance")
        avg_relevance = self._avg_score(per_task_results, "topic_relevance")
        phase_a_score = (avg_substance + avg_relevance) / 2
        phase_b_score = (overall_result.get("coverage", 50) + overall_result.get("diversity", 50)) / 2
        total_score = int(phase_a_score * 0.6 + phase_b_score * 0.4)

        # Phase B 的问题不触发重试，传递给整合阶段
        overall_issues = overall_result.get("issues", [])
        # Phase B 输出的扩展关键词，供重试时 Phase A 使用
        new_expanded_keywords = overall_result.get("expanded_keywords", [])

        # 通过条件：有失败任务时需要分数更高
        if failed_task_indices:
            passed = total_score >= 60
        else:
            passed = total_score >= 50

        logger.info("[QA] Phase B: coverage=%d, diversity=%d, total_score=%d, passed=%s",
                     overall_result.get("coverage", 0), overall_result.get("diversity", 0),
                     total_score, passed)

        issues = [r["reason"] for r in per_task_results if not r["passed"] and r["reason"]]
        issues.extend(overall_issues)

        return self._build_result(
            passed=passed,
            score=total_score,
            issues=issues,
            failed_task_indices=failed_task_indices if not passed else [],
            per_task_results=per_task_results,
            overall_issues=overall_issues,
            expanded_keywords=new_expanded_keywords,
        )

    def _evaluate_all_tasks(
        self,
        execution_results: List[Dict[str, Any]],
        user_input: str,
        expanded_keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Phase A: 逐任务规则评估"""
        per_task_results = []
        for i, result in enumerate(execution_results):
            task_result = self._evaluate_per_task(i, result, user_input, expanded_keywords)
            per_task_results.append(task_result)
        return per_task_results

    def _evaluate_per_task(
        self,
        task_index: int,
        result: Dict[str, Any],
        user_input: str,
        expanded_keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Phase A: 单任务规则评估

        Returns:
            task_index, passed, download_success, content_substance, topic_relevance, reason, content_preview
        """
        # 1. 检查下载是否成功
        status = result.get("status")
        if status != "success":
            return {
                "task_index": task_index,
                "passed": False,
                "download_success": False,
                "content_substance": 0,
                "topic_relevance": 0,
                "reason": f"下载失败，状态: {status}",
                "content_preview": "",
            }

        # 2. 提取内容
        task_data = result.get("result", {})
        content = self._extract_content(task_data)

        # 3. 内容实质性评分
        substance = self._compute_substance(content)

        # 4. 主题相关性评分（宽松模式 + 扩展关键词）
        relevance = self._compute_relevance(content, user_input, expanded_keywords)

        # 5. 生成内容预览（用于 Phase B）
        content_preview = content[:800] if content else ""

        # 6. 判断是否通过
        passed = substance >= _SUBSTANCE_PASS_THRESHOLD and relevance >= _RELEVANCE_PASS_THRESHOLD
        reason = ""
        if not passed:
            reasons = []
            if substance < _SUBSTANCE_PASS_THRESHOLD:
                reasons.append(f"内容实质性不足({substance})")
            if relevance < _RELEVANCE_PASS_THRESHOLD:
                reasons.append(f"主题相关性不足({relevance})")
            reason = "，".join(reasons)

        logger.info("[QA] Task %d: substance=%d, relevance=%d, passed=%s, reason=%s",
                    task_index, substance, relevance, passed, reason)

        return {
            "task_index": task_index,
            "passed": passed,
            "download_success": True,
            "content_substance": substance,
            "topic_relevance": relevance,
            "reason": reason,
            "content_preview": content_preview,
        }

    def _extract_content(self, task_data: Any) -> str:
        """从任务结果中提取文本内容"""
        if isinstance(task_data, str):
            return task_data
        if isinstance(task_data, dict):
            # 优先取 content，其次 answer/code/design
            for key in ("content", "answer", "code", "design"):
                if key in task_data and task_data[key]:
                    return str(task_data[key])
            # search_web 结果：聚合多个 URL 的内容
            if "results" in task_data and isinstance(task_data["results"], list):
                parts = []
                for item in task_data["results"]:
                    if isinstance(item, dict):
                        parts.append(item.get("content", item.get("snippet", "")))
                return "\n\n".join(parts)
            # processed_data
            if "processed_data" in task_data:
                return str(task_data["processed_data"])
        return ""

    def _compute_substance(self, content: str) -> int:
        """
        内容实质性评分（0-100）

        - 长度 < 200 字符 → 0
        - 200-500字 → 50；500+字 → 80
        - 模板内容占比 > 30% → 扣20分
        - 句子密度：平均每行有效词数 > 5 → +10分
        """
        length = len(content)

        if length < 200:
            return 0

        # 基础分：基于长度
        if length < 500:
            base = 50
        else:
            base = 80

        # 模板内容检测
        content_lower = content.lower()
        boilerplate_count = sum(1 for kw in _BOILERPLATE_KEYWORDS if kw in content_lower)
        boilerplate_ratio = boilerplate_count / max(len(content.split()), 1)
        if boilerplate_ratio > 0.3:
            base -= 20

        # 句子密度：平均每行有效词数
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        if lines:
            words_per_line = sum(len(line.split()) for line in lines) / len(lines)
            if words_per_line > 5:
                base += 10

        return max(0, min(100, base))

    def _compute_relevance(
        self,
        content: str,
        user_input: str,
        expanded_keywords: Optional[List[str]] = None,
    ) -> int:
        """
        主题相关性评分（宽松模式，0-100）

        宽松策略：
        - 无法提取关键词 → 60（默认通过）
        - 提取到关键词但 0 命中 → 40（给机会，不直接判死）
        - 有命中 → 正常计算，最低 30
        - expanded_keywords（来自 Phase B）合并到关键词列表，提升重试匹配率
        """
        keywords = self._extract_keywords(user_input)
        # 合并 Phase B 输出的扩展关键词
        if expanded_keywords:
            keywords = list(set(keywords + expanded_keywords))

        if not keywords:
            return 60  # 无法提取关键词 → 默认通过

        content_lower = content.lower()
        hit_count = sum(1 for kw in keywords if kw.lower() in content_lower)

        if hit_count == 0:
            return 25  # 0 命中 → 低于阈值30，会被标记为相关性不足

        # 有命中 → 正常计算，最低 30
        relevance = int((hit_count / len(keywords)) * 100)
        return max(30, min(100, relevance))

    def _extract_keywords(self, text: str) -> List[str]:
        """
        从用户输入中提取关键词

        策略：按空格/标点分词，过滤停用词和短词
        """
        # 中英文混合分词：先按空格和标点分割
        tokens = re.split(r'[\s,，.。!！?？;；:：、\(\)（）\[\]【】]+', text)

        # 停用词
        stop_words = {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
            "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
            "请", "帮", "帮我", "想", "需要", "什么", "怎么", "如何", "哪些", "哪个",
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "about", "like",
            "through", "after", "over", "between", "out", "against", "during",
            "without", "before", "under", "around", "among", "and", "or", "but",
            "not", "no", "nor", "so", "yet", "both", "either", "neither",
            "each", "every", "all", "any", "few", "more", "most", "other",
            "some", "such", "than", "too", "very", "just", "because", "if",
            "when", "where", "how", "what", "which", "who", "whom", "this",
            "that", "these", "those", "i", "me", "my", "we", "our", "you",
            "your", "he", "him", "his", "she", "her", "it", "its", "they",
            "them", "their",
        }

        keywords = []
        for token in tokens:
            token = token.strip()
            if len(token) >= 2 and token.lower() not in stop_words:
                keywords.append(token)

        return keywords

    async def _evaluate_overall(
        self, passed_results: List[Dict[str, Any]], user_input: str
    ) -> Dict[str, Any]:
        """
        Phase B: 整体质量评估（1次LLM调用）

        发送元数据摘要 + 800字内容预览给 LLM，评估覆盖度和多样性。
        """
        if not passed_results:
            return {"coverage": 0, "diversity": 0, "issues": ["没有通过 Phase A 的结果"]}

        # 构建元数据摘要
        summary_parts = []
        for r in passed_results:
            meta = f"任务{r['task_index'] + 1}: 实质性:{r['content_substance']} 相关性:{r['topic_relevance']}"
            preview = r.get("content_preview", "")
            if preview:
                meta += f"\n内容预览（800字）: {preview}"
            summary_parts.append(meta)

        summary_text = "\n---\n".join(summary_parts)

        prompt = f"""请评估以下下载内容的整体质量。

用户需求：{user_input}

各任务评估结果：
{summary_text}

请从两个维度打分（0-100分）：
1. coverage（覆盖度）：内容是否覆盖了用户需求的多个方面？是否有重要方面缺失？
2. diversity（多样性）：来源是否多样？是否有大量重复内容？

同时：
- 列出发现的问题（如有），例如：内容重复度高、缺少某个重要方面的资料、内容质量参差不齐
- 提取用户需求的关键词和同义词（expanded_keywords），用于后续内容匹配。
  例如用户输入"Claude Code 使用方式"，应提取 ["Claude Code", "CLI", "Anthropic", "命令行工具", "编程助手", "使用教程", "快速上手"]

请以 JSON 格式返回：
{{
  "coverage": 75,
  "diversity": 80,
  "issues": ["问题1", "问题2"],
  "expanded_keywords": ["关键词1", "同义词1", "相关词1"]
}}

只返回 JSON，不要其他内容。"""

        try:
            response = await self.llm_provider.chat(
                [{"role": "user", "content": prompt}]
            )
            content = response.get("content", "")

            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                import json
                result = json.loads(json_match.group())
                if "coverage" in result and "diversity" in result:
                    result.setdefault("issues", [])
                    result.setdefault("expanded_keywords", [])
                    return result
        except Exception as e:
            logger.warning("[QA] Phase B LLM 评估失败: %s", e)

        # 降级：基于规则的评估
        return self._rule_based_overall_evaluation(passed_results)

    def _rule_based_overall_evaluation(
        self, passed_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Phase B 降级方案：基于规则的整体评估"""
        if not passed_results:
            return {"coverage": 0, "diversity": 0, "issues": []}

        # 覆盖度：基于通过任务数量
        count = len(passed_results)
        if count >= 5:
            coverage = 80
        elif count >= 3:
            coverage = 60
        else:
            coverage = 40

        # 多样性：基于内容预览的去重率
        previews = [r.get("content_preview", "") for r in passed_results if r.get("content_preview")]
        if len(previews) >= 2:
            unique_ratio = len(set(previews)) / len(previews)
            diversity = int(unique_ratio * 100)
        else:
            diversity = 50

        return {"coverage": coverage, "diversity": diversity, "issues": [], "expanded_keywords": []}

    def _avg_score(self, per_task_results: List[Dict[str, Any]], key: str) -> float:
        """计算平均分"""
        scores = [r[key] for r in per_task_results if key in r]
        return sum(scores) / len(scores) if scores else 0

    def _build_result(
        self,
        passed: bool,
        score: int,
        issues: Optional[List[str]] = None,
        failed_task_indices: Optional[List[int]] = None,
        per_task_results: Optional[List[Dict[str, Any]]] = None,
        overall_issues: Optional[List[str]] = None,
        expanded_keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """构建统一的返回结果"""
        return {
            "passed": passed,
            "score": score,
            "dimensions": {},  # 保留字段，兼容旧调用方
            "issues": issues or [],
            "suggestions": self._generate_suggestions(passed, issues or []),
            "failed_task_indices": failed_task_indices or [],
            "per_task_results": per_task_results or [],
            "overall_issues": overall_issues or [],
            "expanded_keywords": expanded_keywords or [],
        }

    def _generate_suggestions(self, passed: bool, issues: List[str]) -> List[str]:
        """生成改进建议"""
        if passed:
            return ["质量良好，可以直接进入整合阶段"]

        suggestions = []
        for issue in issues:
            if "实质性" in issue or "substance" in issue.lower():
                suggestions.append("重新下载内容更丰富的页面")
            elif "相关性" in issue or "relevance" in issue.lower():
                suggestions.append("调整搜索关键词以获取更相关的内容")
            elif "覆盖度" in issue or "coverage" in issue.lower():
                suggestions.append("补充更多来源以覆盖主题的各个方面")
            elif "重复" in issue or "diversity" in issue.lower():
                suggestions.append("整合时去重，保留最有价值的内容")

        if not suggestions:
            suggestions.append("重试失败的任务以提高整体质量")

        return suggestions
