"""
PlanningAgent - 任务规划 Agent

职责：
1. 理解用户意图
2. 检索相关知识
3. 分解任务为子任务
4. 生成执行计划
"""

import logging
from typing import Any, Dict, List, Optional

from app.common.ai.llm_provider_protocol import LLMProvider

logger = logging.getLogger(__name__)


class PlanningAgent:
    """任务规划 Agent"""

    def __init__(
        self,
        llm_provider: LLMProvider,
        knowledge_service: Optional[Any] = None,  # 改为 Any 避免导入错误
    ):
        self.llm_provider = llm_provider
        self.knowledge_service = knowledge_service

    async def plan(
        self,
        user_input: str,
        kb_ids: Optional[List[int]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        生成任务执行计划

        Args:
            user_input: 用户输入
            kb_ids: 知识库ID列表
            context: 额外上下文信息

        Returns:
            任务计划字典，包含：
            - intent: 用户意图
            - complexity: 任务复杂度
            - subtasks: 子任务列表
            - knowledge: 相关知识
            - strategy: 执行策略
        """
        logger.info(f"🎯 开始任务规划: {user_input[:50]}...")

        # 1. 理解用户意图
        intent = await self._classify_intent(user_input)
        logger.info(f"  意图识别: {intent}")

        # 2. 检索相关知识
        knowledge = []
        if self.knowledge_service and kb_ids:
            knowledge = await self._retrieve_knowledge(user_input, kb_ids)
            logger.info(f"  知识检索: {len(knowledge)} 个相关片段")

        # 3. 评估任务复杂度
        complexity = await self._estimate_complexity(user_input, knowledge)
        logger.info(f"  复杂度评估: {complexity}")

        # 4. 分解子任务
        subtasks = await self._decompose_tasks(user_input, intent, knowledge, complexity)
        logger.info(f"  子任务分解: {len(subtasks)} 个子任务")

        # 5. 确定执行策略
        strategy = self._determine_strategy(complexity, subtasks)
        logger.info(f"  执行策略: {strategy}")

        plan = {
            "intent": intent,
            "complexity": complexity,
            "subtasks": subtasks,
            "knowledge": knowledge,
            "strategy": strategy,
            "requires_quality_check": complexity in ["medium", "complex"],
        }

        return plan

    async def _classify_intent(self, user_input: str) -> str:
        """
        识别用户意图

        Returns:
            意图类型：question/code_generation/analysis/debug/design/other
        """
        # 关键词匹配
        keywords = {
            "question": ["什么", "为什么", "如何", "怎么", "是什么", "解释", "介绍"],
            "code_generation": ["写", "实现", "生成", "创建", "开发", "编写代码"],
            "analysis": ["分析", "评估", "比较", "优缺点", "性能"],
            "debug": ["调试", "错误", "bug", "修复", "问题"],
            "design": ["设计", "架构", "方案", "规划"],
        }

        user_input_lower = user_input.lower()
        for intent, words in keywords.items():
            if any(word in user_input_lower for word in words):
                return intent

        # 使用 LLM 进行更精确的意图识别
        try:
            prompt = f"""请识别以下用户输入的意图类型，只返回一个类别：
question（问答）、code_generation（代码生成）、analysis（分析）、debug（调试）、design（设计）、other（其他）

用户输入：{user_input}

只返回类别名称，不要其他内容。"""

            response = await self.llm_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )

            intent = response.get("content", "other").strip().lower()
            if intent in ["question", "code_generation", "analysis", "debug", "design"]:
                return intent

        except Exception as e:
            logger.warning(f"LLM 意图识别失败: {e}")

        return "other"

    async def _retrieve_knowledge(
        self,
        query: str,
        kb_ids: List[int],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        检索相关知识

        Returns:
            知识片段列表，每个包含：content、score、source
        """
        if not self.knowledge_service:
            return []

        try:
            results = await self.knowledge_service.search(
                query=query,
                kb_ids=kb_ids,
                top_k=top_k,
            )

            knowledge = []
            for result in results:
                knowledge.append({
                    "content": result.get("content", ""),
                    "score": result.get("score", 0.0),
                    "source": result.get("source", ""),
                    "kb_id": result.get("kb_id"),
                })

            return knowledge

        except Exception as e:
            logger.error(f"知识检索失败: {e}")
            return []

    async def _estimate_complexity(
        self,
        user_input: str,
        knowledge: List[Dict[str, Any]],
    ) -> str:
        """
        评估任务复杂度

        Returns:
            复杂度：simple/medium/complex
        """
        # 基于规则的初步评估
        input_length = len(user_input)
        knowledge_coverage = len(knowledge) / 5.0  # 假设 top_k=5

        # 简单任务特征
        if input_length < 50 and knowledge_coverage > 0.6:
            return "simple"

        # 复杂任务特征
        complex_indicators = ["设计", "架构", "系统", "完整", "详细", "多个", "所有"]
        if any(indicator in user_input for indicator in complex_indicators):
            return "complex"

        if input_length > 200:
            return "complex"

        # 默认中等复杂度
        return "medium"

    async def _decompose_tasks(
        self,
        user_input: str,
        intent: str,
        knowledge: List[Dict[str, Any]],
        complexity: str,
    ) -> List[Dict[str, Any]]:
        """
        分解子任务

        Returns:
            子任务列表，每个包含：
            - id: 子任务ID
            - type: 任务类型
            - description: 任务描述
            - dependencies: 依赖的子任务ID列表
        """
        # 简单任务不需要分解
        if complexity == "simple":
            return [{
                "id": "task_1",
                "type": "knowledge_search",
                "description": "检索知识并生成答案",
                "dependencies": [],
            }]

        # 使用 LLM 分解任务
        try:
            knowledge_context = "\n".join([
                f"- {k['content'][:100]}..." for k in knowledge[:3]
            ]) if knowledge else "无相关知识"

            prompt = f"""请将以下用户任务分解为具体的子任务。

用户任务：{user_input}
任务意图：{intent}
相关知识：
{knowledge_context}

请按照以下格式返回子任务列表（JSON格式）：
[
  {{
    "id": "task_1",
    "type": "knowledge_search | code_analysis | data_processing | design",
    "description": "子任务描述",
    "dependencies": []
  }},
  ...
]

要求：
1. 每个子任务应该是独立、可执行的
2. 子任务之间可以有依赖关系
3. 子任务数量控制在 2-5 个
4. type 只能是：knowledge_search、code_analysis、data_processing、design 之一

只返回 JSON 数组，不要其他内容。"""

            response = await self.llm_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            content = response.get("content", "[]")

            # 提取 JSON
            import json
            import re

            # 尝试提取 JSON 数组
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                subtasks = json.loads(json_match.group())

                # 验证格式
                if isinstance(subtasks, list) and len(subtasks) > 0:
                    return subtasks

        except Exception as e:
            logger.warning(f"LLM 任务分解失败: {e}")

        # 降级方案：根据意图生成默认子任务
        return self._generate_default_subtasks(intent)

    def _generate_default_subtasks(self, intent: str) -> List[Dict[str, Any]]:
        """生成默认子任务"""
        # 如果没有知识库服务，不生成 knowledge_search 任务
        has_kb = self.knowledge_service is not None

        if intent == "code_generation":
            if has_kb:
                return [
                    {
                        "id": "task_1",
                        "type": "knowledge_search",
                        "description": "检索相关代码示例和最佳实践",
                        "dependencies": [],
                    },
                    {
                        "id": "task_2",
                        "type": "code_analysis",
                        "description": "生成代码实现",
                        "dependencies": ["task_1"],
                    },
                ]
            else:
                return [
                    {
                        "id": "task_1",
                        "type": "code_analysis",
                        "description": "生成代码实现",
                        "dependencies": [],
                    },
                ]
        elif intent == "design":
            if has_kb:
                return [
                    {
                        "id": "task_1",
                        "type": "knowledge_search",
                        "description": "检索相关设计模式和架构方案",
                        "dependencies": [],
                    },
                    {
                        "id": "task_2",
                        "type": "design",
                        "description": "设计系统架构",
                        "dependencies": ["task_1"],
                    },
                ]
            else:
                return [
                    {
                        "id": "task_1",
                        "type": "design",
                        "description": "设计系统架构",
                        "dependencies": [],
                    },
                ]
        else:
            if has_kb:
                return [
                    {
                        "id": "task_1",
                        "type": "knowledge_search",
                        "description": "检索相关信息",
                        "dependencies": [],
                    },
                    {
                        "id": "task_2",
                        "type": "data_processing",
                        "description": "处理和整合信息",
                        "dependencies": ["task_1"],
                    },
                ]
            else:
                return [
                    {
                        "id": "task_1",
                        "type": "data_processing",
                        "description": "处理和整合信息",
                        "dependencies": [],
                    },
                ]

    def _determine_strategy(
        self,
        complexity: str,
        subtasks: List[Dict[str, Any]],
    ) -> str:
        """
        确定执行策略

        Returns:
            策略：sequential（顺序）/parallel（并行）/hybrid（混合）
        """
        # 简单任务：顺序执行
        if complexity == "simple" or len(subtasks) <= 1:
            return "sequential"

        # 检查是否有依赖关系
        has_dependencies = any(task.get("dependencies") for task in subtasks)

        if has_dependencies:
            return "hybrid"  # 有依赖的并行执行
        else:
            return "parallel"  # 完全并行执行
