"""
Agent 编排框架测试示例
"""

import asyncio
import logging

from app.modules.agent_orchestration import (
    AgentChain,
    AgentFactory,
    CostController,
    DecisionTree,
    DynamicContext,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_simple_path():
    """测试简单路径"""
    logger.info("\n" + "="*80)
    logger.info("测试 1: 简单路径 (Simple Path)")
    logger.info("="*80)

    # 1. 创建上下文
    context = DynamicContext(
        user_input="什么是 Python？",
        max_step=2,
    )
    context.kb_ids = [1]

    # 2. 决策树评估
    decision_tree = DecisionTree()
    path = await decision_tree.decide(
        user_input=context.user_input,
        kb_ids=context.kb_ids,
    )

    logger.info(f"✅ 选择路径: {path.name}")

    # 3. 创建责任链（需要实际的依赖）
    # factory = AgentFactory(llm_provider, knowledge_service, cost_controller, tool_registry)
    # chain = factory.create_chain(path)
    # result = await chain.execute(context)

    logger.info("✅ 简单路径测试完成\n")


async def test_standard_path():
    """测试标准路径"""
    logger.info("\n" + "="*80)
    logger.info("测试 2: 标准路径 (Standard Path)")
    logger.info("="*80)

    # 1. 创建上下文
    context = DynamicContext(
        user_input="帮我分析这段代码的性能问题：for i in range(1000000): print(i)",
        max_step=5,
    )
    context.kb_ids = [1, 2]

    # 2. 决策树评估
    decision_tree = DecisionTree()
    path = await decision_tree.decide(
        user_input=context.user_input,
        kb_ids=context.kb_ids,
    )

    logger.info(f"✅ 选择路径: {path.name}")

    logger.info("✅ 标准路径测试完成\n")


async def test_complex_path():
    """测试复杂路径"""
    logger.info("\n" + "="*80)
    logger.info("测试 3: 复杂路径 (Complex Path)")
    logger.info("="*80)

    # 1. 创建上下文
    context = DynamicContext(
        user_input="设计一个分布式缓存系统，包括架构设计、技术选型、实现方案",
        max_step=15,
    )
    context.kb_ids = []

    # 2. 决策树评估
    decision_tree = DecisionTree()
    path = await decision_tree.decide(
        user_input=context.user_input,
        kb_ids=context.kb_ids,
    )

    logger.info(f"✅ 选择路径: {path.name}")

    logger.info("✅ 复杂路径测试完成\n")


async def test_cost_controller():
    """测试成本控制"""
    logger.info("\n" + "="*80)
    logger.info("测试 4: 成本控制 (Cost Controller)")
    logger.info("="*80)

    # 创建成本控制器
    cost_controller = CostController(budget_limit=1.0)

    # 模拟使用
    from app.modules.agent_orchestration.cost_controller import TokenUsage

    usage1 = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    cost_controller.track("Step1Analyzer", "qwen-plus", usage1)

    usage2 = TokenUsage(prompt_tokens=2000, completion_tokens=1000, total_tokens=3000)
    cost_controller.track("Step2Executor", "qwen-plus", usage2)

    # 检查预算
    logger.info(f"当前成本: ${cost_controller.total_cost:.4f}")
    logger.info(f"预算限制: ${cost_controller.budget_limit:.4f}")
    logger.info(f"是否在预算内: {cost_controller.check_budget()}")

    # 获取摘要
    summary = cost_controller.get_summary()
    logger.info(f"成本摘要: {summary}")

    logger.info("✅ 成本控制测试完成\n")


async def test_decision_tree():
    """测试决策树"""
    logger.info("\n" + "="*80)
    logger.info("测试 5: 决策树 (Decision Tree)")
    logger.info("="*80)

    decision_tree = DecisionTree()

    test_cases = [
        ("什么是 Python？", [1], "simple"),
        ("帮我写一个快速排序算法", [1, 2], "standard"),
        ("设计一个微服务架构", [], "complex"),
        ("解释一下 asyncio 的工作原理", [1], "simple"),
        ("优化这段代码并添加单元测试", [1, 2], "standard"),
    ]

    for user_input, kb_ids, expected_path in test_cases:
        path = await decision_tree.decide(user_input, kb_ids)
        status = "✅" if path.name == expected_path else "❌"
        logger.info(f"{status} 输入: {user_input[:30]}... -> 路径: {path.name} (期望: {expected_path})")

    logger.info("✅ 决策树测试完成\n")


async def main():
    """运行所有测试"""
    logger.info("\n" + "="*80)
    logger.info("🚀 Agent 编排框架测试")
    logger.info("="*80 + "\n")

    try:
        await test_decision_tree()
        await test_cost_controller()
        await test_simple_path()
        await test_standard_path()
        await test_complex_path()

        logger.info("\n" + "="*80)
        logger.info("🎉 所有测试完成")
        logger.info("="*80 + "\n")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
