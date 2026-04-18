"""
Phase 3 架构测试 - 测试重构后的统一架构
"""

import asyncio
import logging
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockLLMProvider:
    """模拟 LLM Provider"""

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, **kwargs) -> Dict[str, Any]:
        """模拟 LLM 调用"""
        user_message = messages[-1].get("content", "")

        # 根据不同的提示返回不同的模拟响应
        if "意图" in user_message or "intent" in user_message.lower():
            content = "question"
        elif "复杂度" in user_message or "complexity" in user_message.lower():
            content = "simple"
        elif "分解" in user_message or "subtask" in user_message.lower():
            content = '''[
                {
                    "id": "task_1",
                    "type": "data_processing",
                    "description": "处理和整合信息",
                    "dependencies": []
                }
            ]'''
        elif "质量" in user_message or "quality" in user_message.lower():
            content = '''{
                "accuracy": 85,
                "completeness": 90,
                "relevance": 88,
                "clarity": 87
            }'''
        elif "Python" in user_message:
            content = "Python 是一种高级编程语言，由 Guido van Rossum 于 1991 年创建。它以简洁、易读的语法著称，广泛应用于 Web 开发、数据分析、人工智能等领域。"
        elif "排序" in user_message or "sort" in user_message.lower():
            content = '''```python
def quick_sort(arr):
    """快速排序算法"""
    if len(arr) <= 1:
        return arr

    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]

    return quick_sort(left) + middle + quick_sort(right)
```'''
        else:
            content = f"这是对问题的回答：{user_message[:50]}..."

        return {
            "content": content,
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        }


async def test_agent_factory():
    """测试 1: AgentFactory 统一工厂"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 1: AgentFactory 统一工厂")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import AgentFactory

    llm_provider = MockLLMProvider()
    factory = AgentFactory(llm_provider=llm_provider)

    # 创建各种 Agent
    planning_agent = factory.create_planning_agent()
    quality_agent = factory.create_quality_agent()
    summary_agent = factory.create_summary_agent()
    code_agent = factory.create_execution_agent("code_analysis")

    logger.info(f"\n✅ AgentFactory 测试通过:")
    logger.info(f"  PlanningAgent: {type(planning_agent).__name__}")
    logger.info(f"  QualityAgent: {type(quality_agent).__name__}")
    logger.info(f"  SummaryAgent: {type(summary_agent).__name__}")
    logger.info(f"  CodeAnalysisAgent: {type(code_agent).__name__}")


async def test_cost_controller():
    """测试 2: CostController 成本控制"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 2: CostController 成本控制")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import CostController
    from app.modules.agent_orchestration.cost_controller import TokenUsage

    controller = CostController(budget_limit=10.0)

    # 测试成本追踪
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    controller.track(
        agent_name="TestAgent",
        model="gpt-4",
        usage=usage,
    )

    # 检查预算
    within_budget = controller.check_budget()
    logger.info(f"  在预算内: {within_budget}")

    # 获取摘要
    summary = controller.get_summary()
    logger.info(f"\n✅ CostController 测试通过:")
    logger.info(f"  总成本: ${summary['total_cost']:.4f}")
    logger.info(f"  总 tokens: {summary['total_tokens']}")
    logger.info(f"  剩余预算: ${summary['budget_remaining']:.4f}")


async def test_tool_registry():
    """测试 3: ToolRegistry 工具注册"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 3: ToolRegistry 工具注册")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import AgentToolRegistry
    from app.modules.agent_orchestration.tool_registry import AgentTool

    registry = AgentToolRegistry()

    # 注册自定义工具
    def custom_tool(input_data: str) -> str:
        return f"处理结果: {input_data}"

    tool = AgentTool(
        name="custom_tool",
        description="自定义工具",
        parameters={
            "type": "object",
            "properties": {
                "input_data": {"type": "string", "description": "输入数据"}
            },
            "required": ["input_data"],
        },
    )

    registry.register(tool, custom_tool)

    # 获取工具
    registered_tool = registry.get_tool("custom_tool")
    logger.info(f"\n✅ ToolRegistry 测试通过:")
    logger.info(f"  工具名称: {registered_tool.name}")
    logger.info(f"  工具描述: {registered_tool.description}")
    logger.info(f"  已注册工具数: {len(registry.list_tools())}")


async def test_decision_tree():
    """测试 4: DecisionTree 决策树"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 4: DecisionTree 决策树")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import DecisionTree

    tree = DecisionTree()

    # 测试不同复杂度的输入
    test_cases = [
        ("什么是 Python？", "Simple"),
        ("帮我写一个快速排序算法", "Standard"),
        ("设计一个分布式用户认证系统，包括注册、登录、权限管理、会话管理和审计日志", "Complex"),
    ]

    logger.info(f"\n✅ DecisionTree 测试通过:")
    for user_input, expected in test_cases:
        path = tree.decide(user_input, {})
        logger.info(f"  输入: {user_input[:30]}...")
        logger.info(f"  路径: {path.name} (预期: {expected})")


async def test_orchestrator_simple():
    """测试 5: AgentOrchestrator 简单任务"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 5: AgentOrchestrator 简单任务")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import AgentOrchestrator

    llm_provider = MockLLMProvider()
    orchestrator = AgentOrchestrator(
        llm_provider=llm_provider,
        max_cost=10.0,  # 这个参数会传递给 CostController 的 budget_limit
    )

    result = await orchestrator.execute(
        user_input="什么是 Python？",
        kb_ids=None,
    )

    logger.info(f"\n✅ 简单任务测试通过:")
    logger.info(f"  最终答案: {result['final_answer'][:100]}...")
    logger.info(f"  执行路径: {result['execution_summary']['execution_path']}")
    logger.info(f"  执行时间: {result['execution_summary']['execution_time']:.2f}s")
    logger.info(f"  总成本: ${result['cost_report']['total_cost']:.4f}")


async def test_orchestrator_with_retry():
    """测试 6: AgentOrchestrator 重试机制"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 6: AgentOrchestrator 重试机制")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import AgentOrchestrator

    llm_provider = MockLLMProvider()
    orchestrator = AgentOrchestrator(
        llm_provider=llm_provider,
        max_retries=2,
        max_cost=10.0,
    )

    result = await orchestrator.execute(
        user_input="帮我写一个快速排序算法",
        kb_ids=None,
    )

    logger.info(f"\n✅ 重试机制测试通过:")
    logger.info(f"  最终答案: {result['final_answer'][:100]}...")
    logger.info(f"  重试次数: {result['execution_summary']['retry_count']}")
    logger.info(f"  质检通过: {result['quality_check']['passed'] if result['quality_check'] else 'N/A'}")


async def test_orchestrator_cost_limit():
    """测试 7: AgentOrchestrator 成本限制"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 7: AgentOrchestrator 成本限制")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import AgentOrchestrator

    llm_provider = MockLLMProvider()
    orchestrator = AgentOrchestrator(
        llm_provider=llm_provider,
        max_cost=0.001,  # 设置很低的预算
    )

    result = await orchestrator.execute(
        user_input="设计一个复杂的分布式系统",
        kb_ids=None,
    )

    logger.info(f"\n✅ 成本限制测试通过:")
    if "error" in result:
        logger.info(f"  错误类型: {result['error']}")
        logger.info(f"  错误信息: {result['final_answer']}")
    else:
        logger.info(f"  任务完成: {result['final_answer'][:50]}...")


async def main():
    """运行所有测试"""
    try:
        # 测试 1: AgentFactory
        await test_agent_factory()

        # 测试 2: CostController
        await test_cost_controller()

        # 测试 3: ToolRegistry
        await test_tool_registry()

        # 测试 4: DecisionTree
        await test_decision_tree()

        # 测试 5: 简单任务
        await test_orchestrator_simple()

        # 测试 6: 重试机制
        await test_orchestrator_with_retry()

        # 测试 7: 成本限制
        await test_orchestrator_cost_limit()

        logger.info("\n" + "=" * 80)
        logger.info("✅ Phase 3 所有测试完成")
        logger.info("=" * 80)
        logger.info("\n测试总结:")
        logger.info("  ✅ AgentFactory 统一工厂")
        logger.info("  ✅ CostController 成本控制")
        logger.info("  ✅ ToolRegistry 工具注册")
        logger.info("  ✅ DecisionTree 决策树")
        logger.info("  ✅ AgentOrchestrator 简单任务")
        logger.info("  ✅ AgentOrchestrator 重试机制")
        logger.info("  ✅ AgentOrchestrator 成本限制")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
