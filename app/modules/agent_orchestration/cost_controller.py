"""
成本控制器：追踪 Token 使用和预算管理
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Token 使用统计"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "TokenUsage"):
        """累加 Token 使用"""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens


@dataclass
class CostRecord:
    """成本记录"""

    timestamp: datetime
    agent_name: str
    model: str
    usage: TokenUsage
    estimated_cost: float


class CostController:
    """成本控制器"""

    # 价格表（美元/1M tokens）
    PRICING = {
        "gpt-4": {"prompt": 30.0, "completion": 60.0},
        "gpt-4-turbo": {"prompt": 10.0, "completion": 30.0},
        "gpt-3.5-turbo": {"prompt": 0.5, "completion": 1.5},
        "qwen-max": {"prompt": 0.04, "completion": 0.12},  # 阿里云百炼
        "qwen-plus": {"prompt": 0.008, "completion": 0.024},
    }

    def __init__(self, budget_limit: Optional[float] = None):
        """
        Args:
            budget_limit: 预算上限（美元），None 表示无限制
        """
        self.budget_limit = budget_limit
        self.total_usage = TokenUsage()
        self.total_cost = 0.0
        self.records: list[CostRecord] = []
        self.agent_usage: Dict[str, TokenUsage] = {}

    def track(self, agent_name: str, model: str, usage: TokenUsage):
        """
        追踪 Token 使用

        Args:
            agent_name: Agent 名称
            model: 模型名称
            usage: Token 使用量
        """
        # 累加总使用量
        self.total_usage.add(usage)

        # 累加 Agent 使用量
        if agent_name not in self.agent_usage:
            self.agent_usage[agent_name] = TokenUsage()
        self.agent_usage[agent_name].add(usage)

        # 计算成本
        cost = self._calculate_cost(model, usage)
        self.total_cost += cost

        # 记录
        record = CostRecord(
            timestamp=datetime.now(),
            agent_name=agent_name,
            model=model,
            usage=usage,
            estimated_cost=cost,
        )
        self.records.append(record)

        logger.info(
            f"💰 {agent_name} 使用 {usage.total_tokens} tokens, 成本: ${cost:.4f}, 累计: ${self.total_cost:.4f}"
        )

        # 检查预算
        if self.budget_limit and self.total_cost > self.budget_limit:
            logger.warning(f"⚠️ 超出预算限制: ${self.total_cost:.4f} > ${self.budget_limit:.4f}")

    def _calculate_cost(self, model: str, usage: TokenUsage) -> float:
        """
        计算成本

        Args:
            model: 模型名称
            usage: Token 使用量

        Returns:
            成本（美元）
        """
        # 查找价格
        pricing = None
        for key in self.PRICING:
            if key in model.lower():
                pricing = self.PRICING[key]
                break

        if not pricing:
            logger.warning(f"未知模型价格: {model}, 使用默认价格")
            pricing = self.PRICING["gpt-3.5-turbo"]

        # 计算成本
        prompt_cost = (usage.prompt_tokens / 1_000_000) * pricing["prompt"]
        completion_cost = (usage.completion_tokens / 1_000_000) * pricing["completion"]

        return prompt_cost + completion_cost

    def check_budget(self) -> bool:
        """
        检查是否超出预算

        Returns:
            True 表示在预算内，False 表示超出预算
        """
        if not self.budget_limit:
            return True

        return self.total_cost <= self.budget_limit

    def get_summary(self) -> Dict:
        """
        获取成本摘要

        Returns:
            成本摘要字典
        """
        return {
            "total_tokens": self.total_usage.total_tokens,
            "prompt_tokens": self.total_usage.prompt_tokens,
            "completion_tokens": self.total_usage.completion_tokens,
            "total_cost": round(self.total_cost, 4),
            "budget_limit": self.budget_limit,
            "budget_remaining": (round(self.budget_limit - self.total_cost, 4) if self.budget_limit else None),
            "agent_breakdown": {
                name: {
                    "total_tokens": usage.total_tokens,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                }
                for name, usage in self.agent_usage.items()
            },
        }

    def reset(self):
        """重置统计"""
        self.total_usage = TokenUsage()
        self.total_cost = 0.0
        self.records.clear()
        self.agent_usage.clear()
        logger.info("🔄 成本统计已重置")
