"""
ExecutionAgent - 任务执行 Agent 基类

职责：
1. 执行具体的子任务
2. 调用工具和服务
3. 收集执行结果
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.common.ai.llm_provider_protocol import LLMProvider

logger = logging.getLogger(__name__)


class ExecutionAgent(ABC):
    """任务执行 Agent 基类"""

    def __init__(
        self,
        agent_type: str,
        llm_provider: LLMProvider,
    ):
        self.agent_type = agent_type
        self.llm_provider = llm_provider

    @abstractmethod
    async def execute(
        self,
        task: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行任务

        Args:
            task: 任务信息，包含 id、type、description、dependencies
            context: 执行上下文，包含知识、前置任务结果等

        Returns:
            执行结果字典，包含：
            - task_id: 任务ID
            - status: 执行状态（success/failed）
            - result: 执行结果
            - error: 错误信息（如果失败）
            - metadata: 元数据（耗时、token等）
        """
        pass

    def _build_result(
        self,
        task_id: str,
        status: str,
        result: Any = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建标准化的执行结果"""
        return {
            "task_id": task_id,
            "agent_type": self.agent_type,
            "status": status,
            "result": result,
            "error": error,
            "metadata": metadata or {},
        }


class KnowledgeSearchAgent(ExecutionAgent):
    """知识检索 Agent"""

    def __init__(
        self,
        llm_provider: LLMProvider,
        knowledge_service,
    ):
        super().__init__("knowledge_search", llm_provider)
        self.knowledge_service = knowledge_service

    async def execute(
        self,
        task: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行知识检索任务"""
        task_id = task.get("id")
        description = task.get("description", "")

        logger.info(f"📚 执行知识检索: {description}")

        try:
            # 从上下文获取知识库ID和查询
            kb_ids = context.get("kb_ids", []) if context else []
            query = context.get("user_input", description) if context else description

            if not kb_ids:
                return self._build_result(
                    task_id=task_id,
                    status="failed",
                    error="未指定知识库ID",
                )

            # 检索知识
            results = await self.knowledge_service.search(
                query=query,
                kb_ids=kb_ids,
                top_k=5,
            )

            # 使用 LLM 整合知识
            knowledge_text = "\n\n".join([
                f"[来源 {i+1}] {r.get('content', '')}"
                for i, r in enumerate(results)
            ])

            prompt = f"""基于以下知识片段，回答问题：{query}

知识片段：
{knowledge_text}

要求：
1. 基于提供的知识片段回答
2. 如果知识不足，明确说明
3. 保持简洁准确
"""

            response = await self.llm_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            answer = response.get("content", "")

            return self._build_result(
                task_id=task_id,
                status="success",
                result={
                    "answer": answer,
                    "knowledge_chunks": results,
                    "sources": [r.get("source", "") for r in results],
                },
                metadata={
                    "chunks_count": len(results),
                    "tokens": response.get("usage", {}).get("total_tokens", 0),
                },
            )

        except Exception as e:
            logger.error(f"知识检索失败: {e}")
            return self._build_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )


class CodeAnalysisAgent(ExecutionAgent):
    """代码分析 Agent"""

    def __init__(self, llm_provider: LLMProvider):
        super().__init__("code_analysis", llm_provider)

    async def execute(
        self,
        task: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行代码分析任务"""
        task_id = task.get("id")
        description = task.get("description", "")

        logger.info(f"💻 执行代码分析: {description}")

        try:
            # 从上下文获取用户输入和前置任务结果
            user_input = context.get("user_input", "") if context else ""
            previous_results = context.get("previous_results", []) if context else []

            # 整合前置任务的知识
            knowledge_context = ""
            for prev in previous_results:
                if prev.get("status") == "success":
                    result = prev.get("result", {})
                    if isinstance(result, dict) and "answer" in result:
                        knowledge_context += f"\n{result['answer']}\n"

            prompt = f"""请完成以下代码相关任务：

任务描述：{description}
用户需求：{user_input}

参考信息：
{knowledge_context if knowledge_context else "无"}

要求：
1. 提供完整的代码实现
2. 添加必要的注释
3. 考虑错误处理
4. 遵循最佳实践
"""

            response = await self.llm_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )

            code = response.get("content", "")

            return self._build_result(
                task_id=task_id,
                status="success",
                result={
                    "code": code,
                    "language": self._detect_language(code),
                },
                metadata={
                    "tokens": response.get("usage", {}).get("total_tokens", 0),
                },
            )

        except Exception as e:
            logger.error(f"代码分析失败: {e}")
            return self._build_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )

    def _detect_language(self, code: str) -> str:
        """检测代码语言"""
        if "```python" in code:
            return "python"
        elif "```javascript" in code or "```js" in code:
            return "javascript"
        elif "```java" in code:
            return "java"
        elif "```typescript" in code or "```ts" in code:
            return "typescript"
        else:
            return "unknown"


class DataProcessingAgent(ExecutionAgent):
    """数据处理 Agent"""

    def __init__(self, llm_provider: LLMProvider):
        super().__init__("data_processing", llm_provider)

    async def execute(
        self,
        task: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行数据处理任务"""
        task_id = task.get("id")
        description = task.get("description", "")

        logger.info(f"📊 执行数据处理: {description}")

        try:
            # 从上下文获取数据
            user_input = context.get("user_input", "") if context else ""
            previous_results = context.get("previous_results", []) if context else []

            # 整合前置任务的数据
            data_context = ""
            for prev in previous_results:
                if prev.get("status") == "success":
                    result = prev.get("result", {})
                    if isinstance(result, dict):
                        data_context += f"\n{result}\n"

            prompt = f"""请完成以下数据处理任务：

任务描述：{description}
用户需求：{user_input}

输入数据：
{data_context if data_context else "无"}

要求：
1. 分析和处理数据
2. 提取关键信息
3. 生成结构化结果
"""

            response = await self.llm_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            processed_data = response.get("content", "")

            return self._build_result(
                task_id=task_id,
                status="success",
                result={
                    "processed_data": processed_data,
                },
                metadata={
                    "tokens": response.get("usage", {}).get("total_tokens", 0),
                },
            )

        except Exception as e:
            logger.error(f"数据处理失败: {e}")
            return self._build_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )


class DesignAgent(ExecutionAgent):
    """设计 Agent"""

    def __init__(self, llm_provider: LLMProvider):
        super().__init__("design", llm_provider)

    async def execute(
        self,
        task: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行设计任务"""
        task_id = task.get("id")
        description = task.get("description", "")

        logger.info(f"🎨 执行设计任务: {description}")

        try:
            # 从上下文获取信息
            user_input = context.get("user_input", "") if context else ""
            previous_results = context.get("previous_results", []) if context else []

            # 整合前置任务的信息
            reference_context = ""
            for prev in previous_results:
                if prev.get("status") == "success":
                    result = prev.get("result", {})
                    if isinstance(result, dict) and "answer" in result:
                        reference_context += f"\n{result['answer']}\n"

            prompt = f"""请完成以下设计任务：

任务描述：{description}
用户需求：{user_input}

参考信息：
{reference_context if reference_context else "无"}

要求：
1. 提供清晰的设计方案
2. 说明设计理由
3. 考虑可扩展性和可维护性
4. 包含关键技术选型
"""

            response = await self.llm_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
            )

            design = response.get("content", "")

            return self._build_result(
                task_id=task_id,
                status="success",
                result={
                    "design": design,
                },
                metadata={
                    "tokens": response.get("usage", {}).get("total_tokens", 0),
                },
            )

        except Exception as e:
            logger.error(f"设计任务失败: {e}")
            return self._build_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )


# Agent 工厂
class ExecutionAgentFactory:
    """执行 Agent 工厂"""

    @staticmethod
    def create_agent(
        agent_type: str,
        llm_provider: LLMProvider,
        knowledge_service=None,
    ) -> ExecutionAgent:
        """创建执行 Agent"""
        if agent_type == "knowledge_search":
            if not knowledge_service:
                raise ValueError("KnowledgeSearchAgent 需要 knowledge_service")
            return KnowledgeSearchAgent(llm_provider, knowledge_service)
        elif agent_type == "code_analysis":
            return CodeAnalysisAgent(llm_provider)
        elif agent_type == "data_processing":
            return DataProcessingAgent(llm_provider)
        elif agent_type == "design":
            return DesignAgent(llm_provider)
        else:
            raise ValueError(f"未知的 Agent 类型: {agent_type}")
