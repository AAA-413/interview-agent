"""
AgentOrchestrator - 核心编排器

职责：
1. 协调各个 Agent 的执行
2. 管理执行流程
3. 处理重试逻辑
4. 记录执行历史
5. 集成成本控制和工具注册
"""

import logging
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.common.ai.llm_provider_protocol import LLMProvider

if TYPE_CHECKING:
    from app.modules.knowledge_base.rag_service import KnowledgeService

from .agent_factory import AgentFactory
from .cost_controller import CostController
from .decision_tree import DecisionTree
from .tool_registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """核心编排器"""

    def __init__(
        self,
        llm_provider: LLMProvider,
        knowledge_service: Optional[Any] = None,
        max_retries: int = 2,
        max_cost: float = 10.0,
    ):
        self.llm_provider = llm_provider
        self.knowledge_service = knowledge_service
        self.max_retries = max_retries

        # 初始化成本控制器
        self.cost_controller = CostController(budget_limit=max_cost)

        # 初始化工具注册表
        self.tool_registry = AgentToolRegistry()
        self._register_builtin_tools()

        # 初始化决策树（优先使用智能决策树）
        try:
            from .smart_decision_tree import SmartDecisionTree
            self.decision_tree = SmartDecisionTree(
                llm_provider=llm_provider,
                knowledge_service=knowledge_service,
                cost_controller=self.cost_controller,
            )
            logger.info("✅ 使用智能决策树（LLM驱动）")
        except Exception as e:
            logger.warning(f"智能决策树初始化失败，使用基础决策树: {e}")
            self.decision_tree = DecisionTree(knowledge_service=knowledge_service)

        # 初始化 Agent 工厂
        self.agent_factory = AgentFactory(
            llm_provider=llm_provider,
            knowledge_service=knowledge_service,
            cost_controller=self.cost_controller,
            tool_registry=self.tool_registry,
        )

        # 初始化各个 Agent（延迟创建）
        self._planning_agent = None
        self._quality_agent = None
        self._summary_agent = None

    def _register_builtin_tools(self):
        """注册内置工具"""
        from .tool_registry import BUILTIN_TOOLS

        for tool in BUILTIN_TOOLS:
            # 这里可以注册工具处理函数
            # 目前先注册工具定义
            logger.info(f"📦 注册工具: {tool.name}")

    @property
    def planning_agent(self):
        """延迟创建 PlanningAgent"""
        if self._planning_agent is None:
            self._planning_agent = self.agent_factory.create_planning_agent()
        return self._planning_agent

    @property
    def quality_agent(self):
        """延迟创建 QualityAgent"""
        if self._quality_agent is None:
            self._quality_agent = self.agent_factory.create_quality_agent()
        return self._quality_agent

    @property
    def summary_agent(self):
        """延迟创建 SummaryAgent"""
        if self._summary_agent is None:
            self._summary_agent = self.agent_factory.create_summary_agent()
        return self._summary_agent

    async def execute(
        self,
        user_input: str,
        kb_ids: Optional[List[int]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行完整的 Agent 编排流程

        Args:
            user_input: 用户输入
            kb_ids: 知识库ID列表
            context: 额外上下文

        Returns:
            执行结果，包含：
            - final_answer: 最终答案
            - sources: 引用来源
            - execution_summary: 执行摘要
            - plan: 任务计划
            - execution_results: 执行结果列表
            - quality_check: 质量检查结果
            - cost_report: 成本报告
        """
        start_time = time.time()
        logger.info(f"🚀 开始 Agent 编排: {user_input[:50]}...")

        try:
            # 阶段 0：智能决策树选择执行路径
            decision_result = await self.decision_tree.decide(
                user_input=user_input,
                kb_ids=kb_ids,
                context=context,
            )

            # 检查是否是 DecisionResult 对象（智能决策树）
            if hasattr(decision_result, 'path'):
                execution_path = decision_result.path
                logger.info(f"🌲 智能决策: {execution_path.name} (置信度: {decision_result.confidence:.2%})")
                logger.info(f"   理由: {decision_result.reasoning}")
                logger.info(f"   预估成本: ${decision_result.estimated_cost:.4f}")
            else:
                # 基础决策树返回 ExecutionPath
                execution_path = decision_result
                logger.info(f"🌲 决策树选择路径: {execution_path.name}")

            # 阶段 1：规划
            plan = await self.planning_agent.plan(
                user_input=user_input,
                kb_ids=kb_ids,
                context=context,
            )
            logger.info(f"✅ 规划完成: {plan.get('complexity')} 复杂度, {len(plan.get('subtasks', []))} 个子任务")

            # 检查成本预算
            estimated_tokens = plan.get("total_estimated_tokens", 5000)
            if not self.cost_controller.check_budget():
                logger.warning("⚠️ 成本预算不足，任务中止")
                return {
                    "final_answer": "抱歉，当前任务预计成本超出预算，无法执行。",
                    "error": "BUDGET_EXCEEDED",
                    "cost_report": self.cost_controller.get_summary(),
                }

            # 阶段 2：执行（带重试）
            execution_results = None
            quality_check = None
            retry_count = 0

            while retry_count <= self.max_retries:
                # 检查成本预算（重试前）
                if retry_count > 0 and not self.cost_controller.check_budget():
                    logger.warning("⚠️ 成本预算不足，停止重试")
                    break

                # 执行子任务
                execution_results = await self._execute_tasks(
                    subtasks=plan.get("subtasks", []),
                    user_input=user_input,
                    kb_ids=kb_ids,
                    plan=plan,
                )
                logger.info(f"✅ 执行完成: {len(execution_results)} 个任务")

                # 阶段 3：质检（如果需要）
                if plan.get("requires_quality_check", False):
                    quality_check = await self.quality_agent.check(
                        user_input=user_input,
                        execution_results=execution_results,
                        plan=plan,
                    )
                    logger.info(f"✅ 质检完成: {'通过' if quality_check.get('passed') else '未通过'}")

                    # 如果质检通过或达到最大重试次数，跳出循环
                    if quality_check.get("passed") or retry_count >= self.max_retries:
                        break

                    # 质检未通过，准备重试
                    retry_count += 1
                    logger.warning(f"⚠️ 质检未通过，准备第 {retry_count} 次重试")

                    # 根据质检建议调整计划
                    plan = await self._adjust_plan(plan, quality_check)
                else:
                    # 不需要质检，直接跳出
                    break

            # 阶段 4：总结
            summary = await self.summary_agent.summarize(
                user_input=user_input,
                execution_results=execution_results,
                quality_check=quality_check,
                plan=plan,
            )
            logger.info("✅ 总结完成")

            # 计算总耗时
            execution_time = time.time() - start_time

            # 获取成本报告
            cost_report = self.cost_controller.get_summary()

            result = {
                "final_answer": summary.get("final_answer"),
                "sources": summary.get("sources", []),
                "execution_summary": {
                    **summary.get("execution_summary", {}),
                    "execution_time": execution_time,
                    "retry_count": retry_count,
                    "execution_path": execution_path.name,
                },
                "plan": plan,
                "execution_results": execution_results,
                "quality_check": quality_check,
                "cost_report": cost_report,
            }

            logger.info(f"🎉 Agent 编排完成，耗时 {execution_time:.2f}s，成本 ${cost_report['total_cost']:.4f}")
            return result

        except Exception as e:
            logger.error(f"❌ Agent 编排失败: {e}", exc_info=True)
            raise

    async def _execute_tasks(
        self,
        subtasks: List[Dict[str, Any]],
        user_input: str,
        kb_ids: Optional[List[int]],
        plan: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        执行子任务

        根据执行策略选择顺序执行或并行执行
        """
        strategy = plan.get("strategy", "sequential")

        if strategy == "sequential":
            return await self._execute_sequential(subtasks, user_input, kb_ids, plan)
        elif strategy == "parallel":
            return await self._execute_parallel(subtasks, user_input, kb_ids, plan)
        elif strategy == "hybrid":
            return await self._execute_hybrid(subtasks, user_input, kb_ids, plan)
        else:
            return await self._execute_sequential(subtasks, user_input, kb_ids, plan)

    async def _execute_sequential(
        self,
        subtasks: List[Dict[str, Any]],
        user_input: str,
        kb_ids: Optional[List[int]],
        plan: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """顺序执行子任务"""
        results = []
        previous_results = []

        for task in subtasks:
            # 创建执行上下文
            context = {
                "user_input": user_input,
                "kb_ids": kb_ids or [],
                "plan": plan,
                "previous_results": previous_results,
            }

            # 使用 agent_factory 创建 Agent
            agent = self.agent_factory.create_execution_agent(
                agent_type=task.get("type")
            )

            result = await agent.execute(task, context)

            # 追踪成本（如果有 token 使用信息）
            if "metadata" in result and "tokens" in result["metadata"]:
                from .cost_controller import TokenUsage
                tokens = result["metadata"]["tokens"]
                usage = TokenUsage(
                    prompt_tokens=tokens // 3,  # 估算
                    completion_tokens=tokens * 2 // 3,
                    total_tokens=tokens,
                )
                self.cost_controller.track(
                    agent_name=f"ExecutionAgent_{task.get('type')}",
                    model=self.llm_provider.model_name,
                    usage=usage,
                )

            results.append(result)
            previous_results.append(result)

        return results

    async def _execute_parallel(
        self,
        subtasks: List[Dict[str, Any]],
        user_input: str,
        kb_ids: Optional[List[int]],
        plan: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """并行执行子任务"""
        import asyncio

        # 创建所有任务
        tasks = []
        for subtask in subtasks:
            context = {
                "user_input": user_input,
                "kb_ids": kb_ids or [],
                "plan": plan,
                "previous_results": [],
            }

            agent = self.agent_factory.create_execution_agent(
                agent_type=subtask.get("type")
            )

            tasks.append(agent.execute(subtask, context))

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常并追踪成本
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "task_id": subtasks[i].get("id"),
                    "status": "failed",
                    "error": str(result),
                })
            else:
                # 追踪成本
                if "metadata" in result and "tokens" in result["metadata"]:
                    tokens = result["metadata"]["tokens"]
                    self.cost_controller.track(
                        model=self.llm_provider.model_name,
                        input_tokens=tokens // 3,
                        output_tokens=tokens * 2 // 3,
                    )
                processed_results.append(result)

        return processed_results

    async def _execute_hybrid(
        self,
        subtasks: List[Dict[str, Any]],
        user_input: str,
        kb_ids: Optional[List[int]],
        plan: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """混合执行：根据依赖关系分层并行执行"""
        import asyncio

        # 构建依赖图
        task_map = {task["id"]: task for task in subtasks}
        results_map = {}

        # 拓扑排序，分层执行
        executed = set()
        all_results = []

        while len(executed) < len(subtasks):
            # 找出所有依赖已满足的任务
            ready_tasks = []
            for task in subtasks:
                task_id = task["id"]
                if task_id in executed:
                    continue

                dependencies = task.get("dependencies", [])
                if all(dep in executed for dep in dependencies):
                    ready_tasks.append(task)

            if not ready_tasks:
                # 检测到循环依赖
                logger.error("检测到循环依赖")
                break

            # 并行执行这一层的任务
            layer_tasks = []
            for task in ready_tasks:
                # 获取依赖任务的结果
                previous_results = [results_map[dep] for dep in task.get("dependencies", []) if dep in results_map]

                context = {
                    "user_input": user_input,
                    "kb_ids": kb_ids or [],
                    "plan": plan,
                    "previous_results": previous_results,
                }

                agent = self.agent_factory.create_execution_agent(
                    agent_type=task.get("type")
                )

                layer_tasks.append(agent.execute(task, context))

            # 执行这一层
            layer_results = await asyncio.gather(*layer_tasks, return_exceptions=True)

            # 记录结果并追踪成本
            for i, result in enumerate(layer_results):
                task_id = ready_tasks[i]["id"]
                executed.add(task_id)

                if isinstance(result, Exception):
                    result = {
                        "task_id": task_id,
                        "status": "failed",
                        "error": str(result),
                    }
                else:
                    # 追踪成本
                    if "metadata" in result and "tokens" in result["metadata"]:
                        tokens = result["metadata"]["tokens"]
                        self.cost_controller.track(
                            model=self.llm_provider.model_name,
                            input_tokens=tokens // 3,
                            output_tokens=tokens * 2 // 3,
                        )

                results_map[task_id] = result
                all_results.append(result)

        return all_results

    async def _adjust_plan(
        self,
        plan: Dict[str, Any],
        quality_check: Dict[str, Any],
    ) -> Dict[str, Any]:
        """根据质检结果调整计划"""
        # 简单实现：保持原计划，但可以在这里根据质检建议调整
        # 例如：增加子任务、调整执行策略等

        suggestions = quality_check.get("suggestions", [])
        logger.info(f"根据质检建议调整计划: {suggestions}")

        # 这里可以实现更复杂的计划调整逻辑
        # 目前保持原计划不变

        return plan
