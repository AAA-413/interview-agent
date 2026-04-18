"""
智能决策树：基于 LLM 的路径判断 + 成本控制 + 动态上下文

设计目标：
1. 简单路径 80%：快速响应，低成本
2. 标准路径 15%：平衡质量和成本
3. 复杂路径 5%：高质量，允许高成本

核心机制：
- LLM 驱动的复杂度评估
- 动态成本预算分配
- 上下文感知的路径选择
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutionPath:
    """执行路径"""

    name: str  # simple/standard/complex
    description: str
    max_steps: int
    enable_retry: bool
    enable_quality_check: bool
    cost_budget: float  # 成本预算（美元）
    context_window: int  # 上下文窗口大小


@dataclass
class DecisionResult:
    """决策结果"""

    path: ExecutionPath
    confidence: float  # 置信度 0.0-1.0
    reasoning: str  # 决策理由
    estimated_cost: float  # 预估成本
    context_summary: Dict[str, Any]  # 上下文摘要


class SmartDecisionTree:
    """智能决策树"""

    def __init__(self, llm_provider, knowledge_service=None, cost_controller=None):
        """
        Args:
            llm_provider: LLM 提供者
            knowledge_service: 知识库服务（可选）
            cost_controller: 成本控制器（可选）
        """
        self.llm_provider = llm_provider
        self.knowledge_service = knowledge_service
        self.cost_controller = cost_controller

        # 定义三种执行路径（符合 80/15/5 分布）
        self.paths = {
            "simple": ExecutionPath(
                name="simple",
                description="简单路径：直接检索+生成（80%任务）",
                max_steps=2,
                enable_retry=False,
                enable_quality_check=False,
                cost_budget=0.10,  # $0.10
                context_window=4000,
            ),
            "standard": ExecutionPath(
                name="standard",
                description="标准路径：规划+执行+质检（15%任务）",
                max_steps=5,
                enable_retry=True,
                enable_quality_check=True,
                cost_budget=0.50,  # $0.50
                context_window=8000,
            ),
            "complex": ExecutionPath(
                name="complex",
                description="复杂路径：完整四阶段+多次迭代（5%任务）",
                max_steps=15,
                enable_retry=True,
                enable_quality_check=True,
                cost_budget=2.00,  # $2.00
                context_window=16000,
            ),
        }

    async def decide(
        self,
        user_input: str,
        kb_ids: Optional[List[int]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> DecisionResult:
        """
        智能决策选择执行路径

        Args:
            user_input: 用户输入
            kb_ids: 知识库ID列表
            context: 额外上下文（历史对话、用户偏好等）

        Returns:
            决策结果
        """
        logger.info("🎯 开始智能决策分析...")

        # 1. 构建决策上下文
        decision_context = await self._build_decision_context(user_input, kb_ids, context)

        # 2. LLM 驱动的复杂度评估
        complexity_analysis = await self._analyze_complexity_with_llm(
            user_input, decision_context
        )

        # 3. 选择执行路径
        path = self._select_path_by_analysis(complexity_analysis)

        # 4. 成本预算检查
        if self.cost_controller:
            if not self.cost_controller.check_budget():
                logger.warning("⚠️ 预算不足，降级到简单路径")
                path = self.paths["simple"]

        # 5. 构建决策结果
        result = DecisionResult(
            path=path,
            confidence=complexity_analysis.get("confidence", 0.8),
            reasoning=complexity_analysis.get("reasoning", "基于规则的决策"),
            estimated_cost=complexity_analysis.get("estimated_cost", path.cost_budget),
            context_summary=decision_context,
        )

        logger.info(f"✅ 选择路径: {path.name} (置信度: {result.confidence:.2%})")
        logger.info(f"   理由: {result.reasoning}")
        logger.info(f"   预估成本: ${result.estimated_cost:.4f}")

        return result

    async def _build_decision_context(
        self,
        user_input: str,
        kb_ids: Optional[List[int]],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """构建决策上下文"""
        decision_context = {
            "user_input_length": len(user_input),
            "has_knowledge_base": bool(kb_ids),
            "kb_count": len(kb_ids) if kb_ids else 0,
        }

        # 知识库覆盖率
        if kb_ids and self.knowledge_service:
            try:
                kb_coverage = await self._check_knowledge_coverage(user_input, kb_ids)
                decision_context["kb_coverage"] = kb_coverage
            except Exception as e:
                logger.warning(f"知识库检索失败: {e}")
                decision_context["kb_coverage"] = 0.0
        else:
            decision_context["kb_coverage"] = 0.0

        # 历史上下文
        if context:
            decision_context["has_history"] = bool(context.get("history"))
            decision_context["history_length"] = len(context.get("history", []))
            decision_context["user_preference"] = context.get("preference", {})

        # 成本状态
        if self.cost_controller:
            summary = self.cost_controller.get_summary()
            decision_context["budget_remaining"] = summary["budget_remaining"]
            decision_context["budget_usage_rate"] = (
                summary["total_cost"] / summary["budget_limit"]
                if summary["budget_limit"] > 0
                else 0
            )

        return decision_context

    async def _analyze_complexity_with_llm(
        self, user_input: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用 LLM 分析任务复杂度"""

        # 构建分析提示词
        prompt = self._build_complexity_analysis_prompt(user_input, context)

        try:
            # 调用 LLM（使用当前配置的模型）
            response = await self.llm_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # 低温度，更确定性
            )

            # 解析响应
            analysis = self._parse_llm_response(response)
            return analysis

        except Exception as e:
            logger.warning(f"LLM 分析失败，使用规则回退: {e}")
            return self._fallback_rule_based_analysis(user_input, context)

    def _build_complexity_analysis_prompt(
        self, user_input: str, context: Dict[str, Any]
    ) -> str:
        """构建复杂度分析提示词"""
        return f"""你是一个任务复杂度分析专家。请分析以下用户请求的复杂度，并选择合适的执行路径。

用户请求：
{user_input}

上下文信息：
- 输入长度: {context['user_input_length']} 字符
- 知识库覆盖率: {context.get('kb_coverage', 0):.2%}
- 剩余预算: ${context.get('budget_remaining', 0):.2f}

执行路径选项：
1. simple（80%任务）：简单问答、直接检索，成本 $0.10
2. standard（15%任务）：需要规划和质检，成本 $0.50
3. complex（5%任务）：多步骤、需要迭代，成本 $2.00

分析要点：
- 简单路径：单一概念问答、基础操作指导、无需多步推理
- 标准路径：代码生成+解释、性能分析、需要规划和质检
- 复杂路径：架构设计、分布式系统、多轮迭代、复杂推理

示例（Few-shot Learning）：

示例 1 - Simple:
输入："什么是 Python？"
输出：{{"path": "simple", "confidence": 0.95, "reasoning": "简单概念问答，答案确定", "estimated_cost": 0.10, "key_factors": ["概念问答", "单一问题"]}}

示例 2 - Simple:
输入："如何安装 pip？"
输出：{{"path": "simple", "confidence": 0.95, "reasoning": "基础操作指导，标准流程", "estimated_cost": 0.10, "key_factors": ["操作指导", "标准流程"]}}

示例 3 - Standard:
输入："帮我写一个快速排序算法，并解释原理"
输出：{{"path": "standard", "confidence": 0.90, "reasoning": "需要代码生成和原理解释，需要规划和质检", "estimated_cost": 0.50, "key_factors": ["代码生成", "原理解释", "需要质检"]}}

示例 4 - Standard:
输入："分析这段代码的性能问题并给出优化建议"
输出：{{"path": "standard", "confidence": 0.90, "reasoning": "需要代码分析和优化方案，需要规划", "estimated_cost": 0.50, "key_factors": ["代码分析", "优化建议"]}}

示例 5 - Complex:
输入："设计一个分布式用户认证系统，包括注册、登录、权限管理"
输出：{{"path": "complex", "confidence": 0.95, "reasoning": "分布式系统架构设计，多个模块，需要详细规划和迭代", "estimated_cost": 2.00, "key_factors": ["架构设计", "分布式系统", "多模块"]}}

现在请分析上面的用户请求，按以下 JSON 格式回复：
{{
  "path": "simple|standard|complex",
  "confidence": 0.0-1.0,
  "reasoning": "选择理由（一句话）",
  "estimated_cost": 预估成本（美元）,
  "key_factors": ["关键因素1", "关键因素2"]
}}

只返回 JSON，不要其他内容。"""

    def _parse_llm_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """解析 LLM 响应"""
        import json
        import re

        # 获取响应内容
        content = response.get("content", "")

        # 提取 JSON
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 解析失败，返回默认值
        return {
            "path": "standard",
            "confidence": 0.5,
            "reasoning": "LLM 响应解析失败，使用默认路径",
            "estimated_cost": 0.5,
            "key_factors": [],
        }

    def _fallback_rule_based_analysis(
        self, user_input: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """规则回退分析"""
        word_count = context["user_input_length"]
        kb_coverage = context.get("kb_coverage", 0.0)

        # 简单规则
        if word_count < 50 and kb_coverage > 0.6:
            return {
                "path": "simple",
                "confidence": 0.7,
                "reasoning": "短问题且知识库覆盖良好",
                "estimated_cost": 0.10,
                "key_factors": ["短输入", "高知识库覆盖"],
            }
        elif word_count < 200:
            return {
                "path": "standard",
                "confidence": 0.6,
                "reasoning": "中等长度问题",
                "estimated_cost": 0.50,
                "key_factors": ["中等输入长度"],
            }
        else:
            return {
                "path": "complex",
                "confidence": 0.5,
                "reasoning": "长问题或多步骤任务",
                "estimated_cost": 2.00,
                "key_factors": ["长输入"],
            }

    def _select_path_by_analysis(self, analysis: Dict[str, Any]) -> ExecutionPath:
        """根据分析结果选择路径"""
        path_name = analysis.get("path", "standard")

        # 验证路径名称
        if path_name not in self.paths:
            logger.warning(f"无效路径 {path_name}，使用 standard")
            path_name = "standard"

        return self.paths[path_name]

    async def _check_knowledge_coverage(
        self, user_input: str, kb_ids: List[int]
    ) -> float:
        """检查知识库覆盖率"""
        if not self.knowledge_service:
            return 0.0

        try:
            results = await self.knowledge_service.search(
                query=user_input, kb_ids=kb_ids, top_k=3
            )

            if not results:
                return 0.0

            max_score = max(r.get("score", 0.0) for r in results)
            return max_score

        except Exception as e:
            logger.warning(f"知识库检索失败: {e}")
            return 0.0

    def get_path_statistics(self) -> Dict[str, Any]:
        """获取路径统计信息（用于监控 80/15/5 分布）"""
        # TODO: 实现路径使用统计
        return {
            "simple_usage": 0,
            "standard_usage": 0,
            "complex_usage": 0,
            "target_distribution": {"simple": 0.80, "standard": 0.15, "complex": 0.05},
        }
