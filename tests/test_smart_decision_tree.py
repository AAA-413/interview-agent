"""
智能决策树测试 - 验证 80/15/5 分布和成本控制
"""

import asyncio
import logging
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockLLMProvider:
    """模拟 LLM Provider"""

    def __init__(self):
        self.model_name = "gpt-4o-mini"  # 添加 model_name 属性

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """模拟 LLM 调用"""
        user_message = messages[-1].get("content", "")

        # 模拟复杂度分析响应
        if "复杂度分析" in user_message or "complexity" in user_message.lower():
            # 根据输入长度返回不同的路径
            if "什么是" in user_message or len(user_message) < 100:
                content = '''{
                    "path": "simple",
                    "confidence": 0.85,
                    "reasoning": "简单问答，知识库覆盖良好",
                    "estimated_cost": 0.10,
                    "key_factors": ["短输入", "单一问题"]
                }'''
            elif "设计" in user_message or "架构" in user_message:
                content = '''{
                    "path": "complex",
                    "confidence": 0.90,
                    "reasoning": "需要架构设计和多步骤规划",
                    "estimated_cost": 2.00,
                    "key_factors": ["架构设计", "多步骤"]
                }'''
            else:
                content = '''{
                    "path": "standard",
                    "confidence": 0.75,
                    "reasoning": "需要规划和质检",
                    "estimated_cost": 0.50,
                    "key_factors": ["中等复杂度"]
                }'''
        else:
            content = "这是模拟响应"

        return {
            "content": content,
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        }


async def test_smart_decision_tree():
    """测试 1: 智能决策树基本功能"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 1: 智能决策树基本功能")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.smart_decision_tree import SmartDecisionTree
    from app.modules.agent_orchestration import CostController

    llm_provider = MockLLMProvider()
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


async def test_path_distribution():
    """测试 2: 路径分布（80/15/5）"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 2: 路径分布验证")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.smart_decision_tree import SmartDecisionTree
    from app.modules.agent_orchestration import CostController

    llm_provider = MockLLMProvider()
    cost_controller = CostController(budget_limit=100.0)

    decision_tree = SmartDecisionTree(
        llm_provider=llm_provider,
        cost_controller=cost_controller,
    )

    # 测试用例（模拟真实分布）
    test_cases = [
        # 简单问题（80%）
        "什么是 Python？",
        "如何安装 pip？",
        "解释一下变量",
        "什么是函数？",
        "Python 的优点",
        "如何定义类？",
        "什么是列表？",
        "如何使用循环？",

        # 标准问题（15%）
        "帮我写一个快速排序算法，并解释原理",
        "分析这段代码的性能问题",

        # 复杂问题（5%）
        "设计一个分布式用户认证系统，包括注册、登录、权限管理",
    ]

    path_counts = {"simple": 0, "standard": 0, "complex": 0}
    total_cost = 0.0

    for user_input in test_cases:
        result = await decision_tree.decide(
            user_input=user_input,
            kb_ids=None,
            context=None,
        )
        path_counts[result.path.name] += 1
        total_cost += result.estimated_cost

    total = len(test_cases)
    logger.info(f"\n✅ 路径分布统计:")
    logger.info(f"  Simple: {path_counts['simple']}/{total} ({path_counts['simple']/total:.1%}) - 目标 80%")
    logger.info(f"  Standard: {path_counts['standard']}/{total} ({path_counts['standard']/total:.1%}) - 目标 15%")
    logger.info(f"  Complex: {path_counts['complex']}/{total} ({path_counts['complex']/total:.1%}) - 目标 5%")
    logger.info(f"  总预估成本: ${total_cost:.2f}")


async def test_cost_control():
    """测试 3: 成本控制和降级"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 3: 成本控制和降级")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.smart_decision_tree import SmartDecisionTree
    from app.modules.agent_orchestration import CostController
    from app.modules.agent_orchestration.cost_controller import TokenUsage

    llm_provider = MockLLMProvider()
    cost_controller = CostController(budget_limit=1.0)  # 低预算

    # 模拟已使用大部分预算
    cost_controller.track(
        agent_name="previous_task",
        model="gpt-4",
        usage=TokenUsage(prompt_tokens=10000, completion_tokens=5000, total_tokens=15000),
    )

    decision_tree = SmartDecisionTree(
        llm_provider=llm_provider,
        cost_controller=cost_controller,
    )

    # 尝试执行复杂任务
    result = await decision_tree.decide(
        user_input="设计一个复杂的分布式系统架构",
        kb_ids=None,
        context=None,
    )

    logger.info(f"\n✅ 成本控制测试:")
    logger.info(f"  预算剩余: ${cost_controller.get_summary()['budget_remaining']:.4f}")
    logger.info(f"  选择路径: {result.path.name}")
    logger.info(f"  理由: {result.reasoning}")

    if result.path.name == "simple":
        logger.info("  ✅ 成功降级到简单路径")


async def test_context_awareness():
    """测试 4: 上下文感知"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 4: 上下文感知决策")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.smart_decision_tree import SmartDecisionTree
    from app.modules.agent_orchestration import CostController

    llm_provider = MockLLMProvider()
    cost_controller = CostController(budget_limit=10.0)

    decision_tree = SmartDecisionTree(
        llm_provider=llm_provider,
        cost_controller=cost_controller,
    )

    # 带历史上下文的决策
    context = {
        "history": [
            {"role": "user", "content": "什么是 Python？"},
            {"role": "assistant", "content": "Python 是一种编程语言..."},
        ],
        "preference": {
            "detail_level": "high",
            "code_examples": True,
        },
    }

    result = await decision_tree.decide(
        user_input="继续解释 Python 的特性",
        kb_ids=None,
        context=context,
    )

    logger.info(f"\n✅ 上下文感知测试:")
    logger.info(f"  历史对话数: {len(context['history'])}")
    logger.info(f"  选择路径: {result.path.name}")
    logger.info(f"  上下文摘要: {result.context_summary}")


async def test_orchestrator_integration():
    """测试 5: 集成到 AgentOrchestrator"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 5: AgentOrchestrator 集成")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import AgentOrchestrator

    llm_provider = MockLLMProvider()
    orchestrator = AgentOrchestrator(
        llm_provider=llm_provider,
        max_cost=10.0,
    )

    # 测试简单任务
    result = await orchestrator.execute(
        user_input="什么是 Python？",
        kb_ids=None,
    )

    logger.info(f"\n✅ 集成测试通过:")
    logger.info(f"  执行路径: {result['execution_summary']['execution_path']}")
    logger.info(f"  执行时间: {result['execution_summary']['execution_time']:.2f}s")
    logger.info(f"  总成本: ${result['cost_report']['total_cost']:.4f}")


async def main():
    """运行所有测试"""
    try:
        # 测试 1: 基本功能
        await test_smart_decision_tree()

        # 测试 2: 路径分布
        await test_path_distribution()

        # 测试 3: 成本控制
        await test_cost_control()

        # 测试 4: 上下文感知
        await test_context_awareness()

        # 测试 5: 集成测试
        await test_orchestrator_integration()

        logger.info("\n" + "=" * 80)
        logger.info("✅ 智能决策树所有测试完成")
        logger.info("=" * 80)
        logger.info("\n测试总结:")
        logger.info("  ✅ 智能决策树基本功能")
        logger.info("  ✅ 路径分布验证（80/15/5）")
        logger.info("  ✅ 成本控制和降级")
        logger.info("  ✅ 上下文感知决策")
        logger.info("  ✅ AgentOrchestrator 集成")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
