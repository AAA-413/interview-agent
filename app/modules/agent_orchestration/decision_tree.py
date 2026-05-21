"""
决策树：根据任务复杂度选择执行路径
"""

import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class ExecutionPath:
    """执行路径"""

    name: str  # simple/standard/complex
    description: str
    max_steps: int
    enable_retry: bool
    enable_quality_check: bool


class DecisionTree:
    """决策树：根据用户输入选择执行路径"""

    def __init__(self, knowledge_service=None):
        self.knowledge_service = knowledge_service

        # 定义三种执行路径
        self.paths = {
            "simple": ExecutionPath(
                name="simple",
                description="简单路径：直接检索+生成",
                max_steps=2,
                enable_retry=False,
                enable_quality_check=False,
            ),
            "standard": ExecutionPath(
                name="standard",
                description="标准路径：规划+执行+质检",
                max_steps=5,
                enable_retry=False,
                enable_quality_check=True,
            ),
            "complex": ExecutionPath(
                name="complex",
                description="复杂路径：完整四阶段+多次迭代",
                max_steps=15,
                enable_retry=True,
                enable_quality_check=True,
            ),
        }

    async def decide(self, user_input: str, kb_ids: List[int] = None, context: dict = None) -> ExecutionPath:
        """
        决策选择执行路径

        Args:
            user_input: 用户输入
            kb_ids: 知识库ID列表
            context: 额外上下文

        Returns:
            执行路径
        """
        logger.info("🎯 开始决策树分析...")

        # 1. 意图识别
        intent = await self._classify_intent(user_input)
        logger.info(f"意图识别: {intent}")

        # 2. 复杂度评估
        complexity = await self._estimate_complexity(user_input, context or {})
        logger.info(f"复杂度评估: {complexity}")

        # 3. 知识库匹配度
        kb_coverage = await self._check_knowledge_coverage(user_input, kb_ids)
        logger.info(f"知识库覆盖率: {kb_coverage:.2%}")

        # 4. 选择执行路径
        path = self._select_path(intent, complexity, kb_coverage)
        logger.info(f"✅ 选择执行路径: {path.name} - {path.description}")

        return path

    async def _classify_intent(self, user_input: str) -> str:
        """
        意图识别

        Returns:
            question/code_generation/analysis/debug/other
        """
        user_input_lower = user_input.lower()

        # 简单的关键词匹配（实际应该用 LLM 分类）
        if any(kw in user_input_lower for kw in ["什么", "为什么", "如何", "怎么", "?"]):
            return "question"
        elif any(kw in user_input_lower for kw in ["生成", "创建", "写", "实现"]):
            return "code_generation"
        elif any(kw in user_input_lower for kw in ["分析", "解释", "说明"]):
            return "analysis"
        elif any(kw in user_input_lower for kw in ["调试", "修复", "bug", "错误"]):
            return "debug"
        else:
            return "other"

    async def _estimate_complexity(self, user_input: str, context: dict) -> str:
        """
        复杂度评估

        Returns:
            simple/medium/complex
        """
        # 简单的启发式规则
        word_count = len(user_input)

        # 检查是否有多个子任务
        has_multiple_tasks = any(sep in user_input for sep in ["并且", "然后", "接着", "同时", "1.", "2.", "3."])

        if word_count < 50 and not has_multiple_tasks:
            return "simple"
        elif word_count < 200 and not has_multiple_tasks:
            return "medium"
        else:
            return "complex"

    async def _check_knowledge_coverage(self, user_input: str, kb_ids: List[int] = None) -> float:
        """
        检查知识库覆盖率

        Returns:
            覆盖率 0.0-1.0
        """
        if not kb_ids or not self.knowledge_service:
            return 0.0

        try:
            # 简单检索，看是否有相关知识
            results = await self.knowledge_service.search(query=user_input, kb_ids=kb_ids, top_k=3)

            if not results:
                return 0.0

            # 根据最高相似度评估覆盖率
            max_score = max(r.get("score", 0.0) for r in results)
            return max_score

        except Exception as e:
            logger.warning(f"知识库检索失败: {e}")
            return 0.0

    def _select_path(self, intent: str, complexity: str, kb_coverage: float) -> ExecutionPath:
        """
        选择执行路径

        决策逻辑：
        1. 简单问答 + 简单复杂度 → simple
        2. 中等复杂度 → standard
        3. 高复杂度 或 多步骤任务 → complex
        """
        # 简单路径：简单问答 + 简单复杂度
        if intent == "question" and complexity == "simple":
            return self.paths["simple"]

        # 简单路径：代码生成 + 简单复杂度 + 有知识库支持
        if intent == "code_generation" and complexity == "simple" and kb_coverage > 0.5:
            return self.paths["simple"]

        # 复杂路径：复杂任务
        if complexity == "complex":
            return self.paths["complex"]

        # 复杂路径：需要设计或架构
        if intent in ["code_generation", "other"] and complexity == "medium":
            return self.paths["complex"]

        # 标准路径：其他情况
        return self.paths["standard"]
