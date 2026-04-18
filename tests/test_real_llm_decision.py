"""
真实 LLM 测试 - 智能决策树调优

目标：
1. 验证 80/15/5 路径分布
2. 测试决策准确性
3. 优化提示词
4. 收集性能数据
"""

import asyncio
import logging
import os
import sys
from typing import Dict, List

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_real_llm_decision_tree():
    """测试 1: 真实 LLM 决策树"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 1: 真实 LLM 智能决策树")
    logger.info("=" * 80)

    from app.common.ai.llm_provider import llm_registry
    from app.common.ai.llm_adapter import LLMProviderAdapter
    from app.modules.agent_orchestration.smart_decision_tree import SmartDecisionTree
    from app.modules.agent_orchestration import CostController

    # 初始化 LLM（使用适配器）
    langchain_model = llm_registry.default
    llm_provider = LLMProviderAdapter(langchain_model)

    # 初始化决策树
    cost_controller = CostController(budget_limit=10.0)
    decision_tree = SmartDecisionTree(
        llm_provider=llm_provider,
        cost_controller=cost_controller,
    )

    # 测试简单问题
    result = await decision_tree.decide(
        user_input="什么是 Python？",
        kb_ids=None,
        context=None,
    )

    logger.info(f"\n✅ 简单问题决策:")
    logger.info(f"  路径: {result.path.name}")
    logger.info(f"  置信度: {result.confidence:.2%}")
    logger.info(f"  理由: {result.reasoning}")
    logger.info(f"  预估成本: ${result.estimated_cost:.4f}")
    logger.info(f"  关键因素: {result.context_summary}")


async def test_path_distribution_real():
    """测试 2: 真实路径分布（80/15/5）"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 2: 真实路径分布验证")
    logger.info("=" * 80)

    from app.common.ai.llm_provider import llm_registry
    from app.common.ai.llm_adapter import LLMProviderAdapter
    from app.modules.agent_orchestration.smart_decision_tree import SmartDecisionTree
    from app.modules.agent_orchestration import CostController

    # 初始化
    langchain_model = llm_registry.default
    llm_provider = LLMProviderAdapter(langchain_model)
    cost_controller = CostController(budget_limit=100.0)
    decision_tree = SmartDecisionTree(
        llm_provider=llm_provider,
        cost_controller=cost_controller,
    )

    # 测试用例（模拟真实分布）
    test_cases = [
        # 简单问题（应该 80%）
        ("什么是 Python？", "simple"),
        ("如何安装 pip？", "simple"),
        ("解释一下变量", "simple"),
        ("什么是函数？", "simple"),
        ("Python 的优点", "simple"),
        ("如何定义类？", "simple"),
        ("什么是列表？", "simple"),
        ("如何使用循环？", "simple"),
        ("print 函数的作用", "simple"),
        ("什么是字符串？", "simple"),
        ("如何导入模块？", "simple"),
        ("什么是字典？", "simple"),
        ("如何处理异常？", "simple"),
        ("什么是装饰器？", "simple"),
        ("如何读取文件？", "simple"),
        ("什么是生成器？", "simple"),

        # 标准问题（应该 15%）
        ("帮我写一个快速排序算法，并解释原理", "standard"),
        ("分析这段代码的性能问题并给出优化建议", "standard"),
        ("实现一个 LRU 缓存，要求线程安全", "standard"),

        # 复杂问题（应该 5%）
        ("设计一个分布式用户认证系统，包括注册、登录、权限管理、会话管理和审计日志", "complex"),
    ]

    path_counts = {"simple": 0, "standard": 0, "complex": 0}
    total_cost = 0.0
    correct_predictions = 0

    logger.info(f"\n开始测试 {len(test_cases)} 个用例...")

    for i, (user_input, expected) in enumerate(test_cases, 1):
        logger.info(f"\n[{i}/{len(test_cases)}] 测试: {user_input[:50]}...")

        try:
            result = await decision_tree.decide(
                user_input=user_input,
                kb_ids=None,
                context=None,
            )

            path_counts[result.path.name] += 1
            total_cost += result.estimated_cost

            if result.path.name == expected:
                correct_predictions += 1
                logger.info(f"  ✅ 正确: {result.path.name} (置信度: {result.confidence:.2%})")
            else:
                logger.warning(f"  ❌ 错误: 预测 {result.path.name}, 期望 {expected}")

            logger.info(f"  理由: {result.reasoning}")

        except Exception as e:
            logger.error(f"  ❌ 决策失败: {e}")

    total = len(test_cases)
    logger.info(f"\n" + "=" * 80)
    logger.info("路径分布统计:")
    logger.info("=" * 80)
    logger.info(f"  Simple: {path_counts['simple']}/{total} ({path_counts['simple']/total:.1%}) - 目标 80%")
    logger.info(f"  Standard: {path_counts['standard']}/{total} ({path_counts['standard']/total:.1%}) - 目标 15%")
    logger.info(f"  Complex: {path_counts['complex']}/{total} ({path_counts['complex']/total:.1%}) - 目标 5%")
    logger.info(f"\n准确率: {correct_predictions}/{total} ({correct_predictions/total:.1%})")
    logger.info(f"总预估成本: ${total_cost:.2f}")
    logger.info(f"平均成本: ${total_cost/total:.4f}/任务")


async def test_orchestrator_real():
    """测试 3: 真实 AgentOrchestrator 集成"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 3: 真实 AgentOrchestrator 集成")
    logger.info("=" * 80)

    from app.common.ai.llm_provider import llm_registry
    from app.common.ai.llm_adapter import LLMProviderAdapter
    from app.modules.agent_orchestration import AgentOrchestrator

    # 初始化
    langchain_model = llm_registry.default
    llm_provider = LLMProviderAdapter(langchain_model)

    orchestrator = AgentOrchestrator(
        llm_provider=llm_provider,
        max_cost=10.0,
    )

    # 测试简单任务
    logger.info("\n测试简单任务...")
    result = await orchestrator.execute(
        user_input="什么是 Python？",
        kb_ids=None,
    )

    logger.info(f"\n✅ 简单任务完成:")
    logger.info(f"  执行路径: {result['execution_summary']['execution_path']}")
    logger.info(f"  执行时间: {result['execution_summary']['execution_time']:.2f}s")
    logger.info(f"  总成本: ${result['cost_report']['total_cost']:.4f}")
    logger.info(f"  最终答案: {result['final_answer'][:200]}...")


async def test_cost_optimization():
    """测试 4: 成本优化效果"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 4: 成本优化效果")
    logger.info("=" * 80)

    from app.common.ai.llm_provider import llm_registry
    from app.common.ai.llm_adapter import LLMProviderAdapter
    from app.modules.agent_orchestration.smart_decision_tree import SmartDecisionTree
    from app.modules.agent_orchestration import CostController

    # 初始化
    langchain_model = llm_registry.default
    llm_provider = LLMProviderAdapter(langchain_model)

    # 测试用例
    test_cases = [
        "什么是 Python？",
        "如何安装 pip？",
        "帮我写一个快速排序算法",
        "设计一个分布式系统",
    ]

    # 场景 1: 使用智能决策树
    logger.info("\n场景 1: 使用智能决策树")
    cost_controller_smart = CostController(budget_limit=100.0)
    decision_tree = SmartDecisionTree(
        llm_provider=llm_provider,
        cost_controller=cost_controller_smart,
    )

    smart_cost = 0.0
    for user_input in test_cases:
        result = await decision_tree.decide(user_input, None, None)
        smart_cost += result.estimated_cost
        logger.info(f"  {user_input[:30]}... -> {result.path.name} (${result.estimated_cost:.4f})")

    logger.info(f"\n智能决策总成本: ${smart_cost:.4f}")

    # 场景 2: 固定使用 Complex 路径
    logger.info("\n场景 2: 固定使用 Complex 路径")
    fixed_cost = len(test_cases) * 2.0  # Complex 路径成本
    logger.info(f"固定 Complex 总成本: ${fixed_cost:.4f}")

    # 对比
    savings = (fixed_cost - smart_cost) / fixed_cost * 100
    logger.info(f"\n成本节省: {savings:.1f}%")


async def main():
    """运行所有测试"""
    try:
        # 测试 1: 基本功能
        await test_real_llm_decision_tree()

        # 测试 2: 路径分布
        await test_path_distribution_real()

        # 测试 3: 集成测试
        await test_orchestrator_real()

        # 测试 4: 成本优化
        await test_cost_optimization()

        logger.info("\n" + "=" * 80)
        logger.info("✅ 真实 LLM 测试完成")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
