"""
核心 Agent 简单测试（不依赖完整环境）
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
                    "type": "knowledge_search",
                    "description": "检索相关知识",
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

# 使用示例
arr = [3, 6, 8, 10, 1, 2, 1]
sorted_arr = quick_sort(arr)
print(sorted_arr)  # [1, 1, 2, 3, 6, 8, 10]
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


async def test_planning_agent():
    """测试 PlanningAgent"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 1: PlanningAgent")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.agents import PlanningAgent

    llm_provider = MockLLMProvider()
    planning_agent = PlanningAgent(llm_provider=llm_provider)

    plan = await planning_agent.plan(
        user_input="什么是 Python？",
        kb_ids=None,
    )

    logger.info(f"\n✅ 规划完成:")
    logger.info(f"  意图: {plan['intent']}")
    logger.info(f"  复杂度: {plan['complexity']}")
    logger.info(f"  执行策略: {plan['strategy']}")
    logger.info(f"  子任务数量: {len(plan['subtasks'])}")


async def test_execution_agent():
    """测试 ExecutionAgent"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 2: ExecutionAgent")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.agents import ExecutionAgentFactory

    llm_provider = MockLLMProvider()

    # 测试代码分析 Agent
    code_agent = ExecutionAgentFactory.create_agent(
        agent_type="code_analysis",
        llm_provider=llm_provider,
    )

    task = {
        "id": "task_1",
        "type": "code_analysis",
        "description": "实现一个快速排序算法",
    }

    context = {
        "user_input": "帮我写一个快速排序算法",
        "kb_ids": [],
        "previous_results": [],
    }

    result = await code_agent.execute(task, context)

    logger.info(f"\n✅ 执行完成:")
    logger.info(f"  任务状态: {result['status']}")
    logger.info(f"  代码语言: {result['result'].get('language')}")
    logger.info(f"  代码片段:\n{result['result'].get('code', '')[:200]}...")


async def test_quality_agent():
    """测试 QualityAgent"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 3: QualityAgent")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.agents import QualityAgent

    llm_provider = MockLLMProvider()
    quality_agent = QualityAgent(llm_provider=llm_provider)

    # 模拟执行结果
    execution_results = [
        {
            "task_id": "task_1",
            "status": "success",
            "result": {
                "answer": "Python 是一种高级编程语言，由 Guido van Rossum 于 1991 年创建。"
            },
        }
    ]

    plan = {
        "intent": "question",
        "complexity": "simple",
    }

    quality_check = await quality_agent.check(
        user_input="什么是 Python？",
        execution_results=execution_results,
        plan=plan,
    )

    logger.info(f"\n✅ 质检完成:")
    logger.info(f"  质检通过: {quality_check['passed']}")
    logger.info(f"  总分: {quality_check['score']:.1f}")
    logger.info(f"  各维度评分: {quality_check['dimensions']}")


async def test_summary_agent():
    """测试 SummaryAgent"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 4: SummaryAgent")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.agents import SummaryAgent

    llm_provider = MockLLMProvider()
    summary_agent = SummaryAgent(llm_provider=llm_provider)

    # 模拟执行结果
    execution_results = [
        {
            "task_id": "task_1",
            "agent_type": "knowledge_search",
            "status": "success",
            "result": {
                "answer": "Python 是一种高级编程语言。",
                "sources": ["Python 官方文档"],
            },
        }
    ]

    plan = {
        "intent": "question",
        "complexity": "simple",
        "strategy": "sequential",
    }

    summary = await summary_agent.summarize(
        user_input="什么是 Python？",
        execution_results=execution_results,
        plan=plan,
    )

    logger.info(f"\n✅ 总结完成:")
    logger.info(f"  最终答案: {summary['final_answer'][:100]}...")
    logger.info(f"  来源数量: {len(summary['sources'])}")
    logger.info(f"  执行摘要: {summary['execution_summary']}")


async def test_orchestrator():
    """测试 AgentOrchestrator"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 5: AgentOrchestrator（完整流程）")
    logger.info("=" * 80)

    from app.modules.agent_orchestration import AgentOrchestrator

    llm_provider = MockLLMProvider()
    orchestrator = AgentOrchestrator(llm_provider=llm_provider)

    result = await orchestrator.execute(
        user_input="什么是 Python？",
        kb_ids=None,
    )

    logger.info(f"\n✅ 编排完成:")
    logger.info(f"  最终答案: {result['final_answer'][:100]}...")
    logger.info(f"  执行时间: {result['execution_summary']['execution_time']:.2f}s")
    logger.info(f"  任务数量: {result['execution_summary']['total_tasks']}")
    logger.info(f"  成功任务: {result['execution_summary']['success_tasks']}")


async def main():
    """运行所有测试"""
    try:
        # 测试 1: PlanningAgent
        await test_planning_agent()

        # 测试 2: ExecutionAgent
        await test_execution_agent()

        # 测试 3: QualityAgent
        await test_quality_agent()

        # 测试 4: SummaryAgent
        await test_summary_agent()

        # 测试 5: AgentOrchestrator
        await test_orchestrator()

        logger.info("\n" + "=" * 80)
        logger.info("✅ 所有测试完成")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
