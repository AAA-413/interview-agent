"""
Agent 责任链
"""

import logging
from typing import Optional

from .base_agent import BaseAgent, DynamicContext, Result

logger = logging.getLogger(__name__)


class AgentChain:
    """责任链：串联多个 Agent 协同工作"""

    def __init__(self):
        self.root: Optional[BaseAgent] = None

    def set_root(self, agent: BaseAgent):
        """设置根节点"""
        self.root = agent
        logger.info(f"✅ 设置根节点: {agent.name}")

    async def execute(self, context: DynamicContext) -> Result:
        """
        从根节点开始执行责任链

        Args:
            context: 动态上下文

        Returns:
            执行结果
        """
        if not self.root:
            raise ValueError("责任链未设置根节点")

        logger.info("🚀 开始执行责任链")
        current_agent = self.root

        while current_agent:
            logger.info(f"\n{'='*60}")
            logger.info(f"📍 当前节点: {current_agent.name} (步骤 {context.step + 1}/{context.max_step})")
            logger.info(f"{'='*60}")

            try:
                # 执行当前节点
                result = await current_agent.apply(context)

                # 更新动态上下文
                context.step += 1
                context.add_execution_result(result)

                logger.info(f"✅ {current_agent.name} 执行完成")

                # 检查终止条件
                if context.is_completed:
                    logger.info("🎉 任务已完成，提前终止")
                    break

                if context.step >= context.max_step:
                    logger.warning(f"⚠️ 达到最大步数 {context.max_step}，强制终止")
                    break

                # 获取下一个节点
                next_agent = await current_agent.get_next(context)

                if next_agent:
                    logger.info(f"➡️ 下一个节点: {next_agent.name}")
                else:
                    logger.info("🏁 到达责任链终点")

                current_agent = next_agent

            except Exception as e:
                logger.error(f"❌ {current_agent.name} 执行失败: {e}", exc_info=True)
                context.set_value("error", str(e))
                break

        logger.info(f"\n{'='*60}")
        logger.info(f"🏁 责任链执行完成")
        logger.info(f"总步数: {context.step}, 重试次数: {context.retry_count}")
        logger.info(f"{'='*60}\n")

        return context.get_final_result()
