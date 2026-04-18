"""
核心 Agent 集成测试
"""

import asyncio
import logging

from app.common.ai.llm_provider import llm_registry
from app.modules.agent_orchestration.orchestrator import AgentOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SimpleLLMProvider:
    """简单的 LLM Provider 包装类"""

    def __init__(self, chat_model):
        self.chat_model = chat_model

    async def chat(self, messages, temperature=0.7, **kwargs):
        """调用 LLM"""
        from langchain_core.messages import HumanMessage, SystemMessage

        # 转换消息格式
        lc_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        # 调用模型
        response = await self.chat_model.ainvoke(lc_messages, temperature=temperature)

        # 返回标准格式
        return {
            "content": response.content,
            "usage": {
                "total_tokens": getattr(response.response_metadata.get("token_usage", {}), "total_tokens", 0)
            }
        }


def get_llm_provider():
    """获取 LLM Provider"""
    chat_model = llm_registry.default
    return SimpleLLMProvider(chat_model)


async def test_simple_question():
    """测试简单问答"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 1: 简单问答")
    logger.info("=" * 80)

    llm_provider = get_llm_provider()
    orchestrator = AgentOrchestrator(llm_provider=llm_provider)

    result = await orchestrator.execute(
        user_input="什么是 Python？",
        kb_ids=None,
    )

    logger.info(f"\n最终答案:\n{result['final_answer']}")
    logger.info(f"\n执行摘要: {result['execution_summary']}")


async def test_code_generation():
    """测试代码生成"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 2: 代码生成")
    logger.info("=" * 80)

    llm_provider = get_llm_provider()
    orchestrator = AgentOrchestrator(llm_provider=llm_provider)

    result = await orchestrator.execute(
        user_input="帮我写一个 Python 快速排序算法",
        kb_ids=None,
    )

    logger.info(f"\n最终答案:\n{result['final_answer'][:500]}...")
    logger.info(f"\n执行摘要: {result['execution_summary']}")
    logger.info(f"\n质检结果: {result.get('quality_check', {}).get('score')}")


async def test_complex_task():
    """测试复杂任务"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 3: 复杂任务")
    logger.info("=" * 80)

    llm_provider = get_llm_provider()
    orchestrator = AgentOrchestrator(llm_provider=llm_provider)

    result = await orchestrator.execute(
        user_input="设计一个用户认证系统，包括注册、登录、权限管理和会话管理",
        kb_ids=None,
    )

    logger.info(f"\n最终答案:\n{result['final_answer'][:500]}...")
    logger.info(f"\n执行摘要: {result['execution_summary']}")
    logger.info(f"\n任务计划: {result['plan']['complexity']}, {len(result['plan']['subtasks'])} 个子任务")
    logger.info(f"\n质检结果: {result.get('quality_check', {}).get('score')}")


async def test_planning_agent():
    """测试 PlanningAgent"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 4: PlanningAgent")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.agents import PlanningAgent

    llm_provider = get_llm_provider()
    planning_agent = PlanningAgent(llm_provider=llm_provider)

    plan = await planning_agent.plan(
        user_input="帮我实现一个完整的 RESTful API，包括用户管理、数据验证和错误处理",
        kb_ids=None,
    )

    logger.info(f"\n意图: {plan['intent']}")
    logger.info(f"复杂度: {plan['complexity']}")
    logger.info(f"执行策略: {plan['strategy']}")
    logger.info(f"子任务数量: {len(plan['subtasks'])}")
    logger.info(f"\n子任务列表:")
    for task in plan['subtasks']:
        logger.info(f"  - {task['id']}: {task['description']} (类型: {task['type']})")


async def test_execution_agents():
    """测试 ExecutionAgent"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 5: ExecutionAgent")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.agents import ExecutionAgentFactory

    llm_provider = get_llm_provider()

    # 测试代码分析 Agent
    code_agent = ExecutionAgentFactory.create_agent(
        agent_type="code_analysis",
        llm_provider=llm_provider,
    )

    task = {
        "id": "task_1",
        "type": "code_analysis",
        "description": "实现一个二分查找算法",
    }

    context = {
        "user_input": "帮我写一个二分查找算法",
        "kb_ids": [],
        "previous_results": [],
    }

    result = await code_agent.execute(task, context)

    logger.info(f"\n任务状态: {result['status']}")
    logger.info(f"代码语言: {result['result'].get('language')}")
    logger.info(f"代码片段:\n{result['result'].get('code', '')[:300]}...")


async def test_quality_agent():
    """测试 QualityAgent"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 6: QualityAgent")
    logger.info("=" * 80)

    from app.modules.agent_orchestration.agents import QualityAgent

    llm_provider = get_llm_provider()
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

    logger.info(f"\n质检通过: {quality_check['passed']}")
    logger.info(f"总分: {quality_check['score']:.1f}")
    logger.info(f"各维度评分: {quality_check['dimensions']}")
    logger.info(f"问题: {quality_check['issues']}")
    logger.info(f"建议: {quality_check['suggestions']}")


async def main():
    """运行所有测试"""
    try:
        # 测试 1: 简单问答
        await test_simple_question()

        # 测试 2: 代码生成
        await test_code_generation()

        # 测试 3: 复杂任务
        # await test_complex_task()  # 耗时较长，可选

        # 测试 4: PlanningAgent
        await test_planning_agent()

        # 测试 5: ExecutionAgent
        await test_execution_agents()

        # 测试 6: QualityAgent
        await test_quality_agent()

        logger.info("\n" + "=" * 80)
        logger.info("✅ 所有测试完成")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
