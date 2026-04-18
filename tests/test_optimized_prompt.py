"""
测试优化后的提示词 - 验证 Few-shot Learning 效果
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_optimized_prompt():
    """测试优化后的提示词"""
    logger.info("\n" + "=" * 80)
    logger.info("测试优化后的提示词（Few-shot Learning）")
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

    # 测试关键案例（之前的错误案例）
    test_cases = [
        ("什么是 Python？", "simple"),
        ("如何安装 pip？", "simple"),
        ("帮我写一个快速排序算法，并解释原理", "standard"),  # 之前错误的案例
        ("分析这段代码的性能问题并给出优化建议", "standard"),
        ("实现一个 LRU 缓存，要求线程安全", "standard"),
        ("设计一个分布式用户认证系统，包括注册、登录、权限管理", "complex"),
    ]

    correct = 0
    total = len(test_cases)

    for i, (user_input, expected) in enumerate(test_cases, 1):
        logger.info(f"\n[{i}/{total}] 测试: {user_input}")

        result = await decision_tree.decide(
            user_input=user_input,
            kb_ids=None,
            context=None,
        )

        if result.path.name == expected:
            correct += 1
            logger.info(f"  ✅ 正确: {result.path.name} (置信度: {result.confidence:.2%})")
        else:
            logger.warning(f"  ❌ 错误: 预测 {result.path.name}, 期望 {expected}")

        logger.info(f"  理由: {result.reasoning}")

    logger.info(f"\n" + "=" * 80)
    logger.info(f"准确率: {correct}/{total} ({correct/total:.1%})")
    logger.info("=" * 80)

    if correct == total:
        logger.info("✅ 所有测试通过！Few-shot Learning 生效")
    else:
        logger.warning(f"⚠️ {total - correct} 个测试失败，需要进一步优化")


async def main():
    try:
        await test_optimized_prompt()
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
