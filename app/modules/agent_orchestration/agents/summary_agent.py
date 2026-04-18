"""
SummaryAgent - 结果总结 Agent

职责：
1. 整合所有执行结果
2. 生成最终答案
3. 添加引用来源
4. 生成执行摘要
"""

import logging
from typing import Any, Dict, List, Optional

from app.common.ai.llm_provider_protocol import LLMProvider

logger = logging.getLogger(__name__)


class SummaryAgent:
    """结果总结 Agent"""

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    async def summarize(
        self,
        user_input: str,
        execution_results: List[Dict[str, Any]],
        quality_check: Optional[Dict[str, Any]] = None,
        plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        总结执行结果

        Args:
            user_input: 用户输入
            execution_results: 执行结果列表
            quality_check: 质量检查结果
            plan: 任务计划

        Returns:
            总结结果，包含：
            - final_answer: 最终答案
            - sources: 引用来源
            - execution_summary: 执行摘要
            - quality_score: 质量评分
        """
        logger.info("📝 开始结果总结")

        # 1. 整合执行结果
        integrated_content = self._integrate_results(execution_results)

        # 2. 提取来源
        sources = self._extract_sources(execution_results)

        # 3. 生成最终答案
        final_answer = await self._generate_final_answer(
            user_input=user_input,
            content=integrated_content,
            quality_check=quality_check,
        )

        # 4. 生成执行摘要
        execution_summary = self._generate_execution_summary(
            execution_results=execution_results,
            plan=plan,
            quality_check=quality_check,
        )

        logger.info("  总结完成")

        return {
            "final_answer": final_answer,
            "sources": sources,
            "execution_summary": execution_summary,
            "quality_score": quality_check.get("score") if quality_check else None,
        }

    def _integrate_results(self, execution_results: List[Dict[str, Any]]) -> str:
        """整合执行结果"""
        sections = []

        for i, result in enumerate(execution_results, 1):
            task_id = result.get("task_id", f"task_{i}")
            agent_type = result.get("agent_type", "unknown")
            status = result.get("status", "unknown")

            if status == "success":
                task_result = result.get("result", {})

                # 根据 agent 类型提取内容
                if isinstance(task_result, dict):
                    if "answer" in task_result:
                        sections.append(f"## {task_id} ({agent_type})\n{task_result['answer']}")
                    elif "code" in task_result:
                        sections.append(f"## {task_id} ({agent_type})\n```\n{task_result['code']}\n```")
                    elif "design" in task_result:
                        sections.append(f"## {task_id} ({agent_type})\n{task_result['design']}")
                    elif "processed_data" in task_result:
                        sections.append(f"## {task_id} ({agent_type})\n{task_result['processed_data']}")
                elif isinstance(task_result, str):
                    sections.append(f"## {task_id} ({agent_type})\n{task_result}")

        return "\n\n".join(sections)

    def _extract_sources(self, execution_results: List[Dict[str, Any]]) -> List[str]:
        """提取引用来源"""
        sources = []

        for result in execution_results:
            if result.get("status") == "success":
                task_result = result.get("result", {})

                if isinstance(task_result, dict):
                    # 从知识检索结果中提取来源
                    if "sources" in task_result:
                        sources.extend(task_result["sources"])
                    elif "knowledge_chunks" in task_result:
                        for chunk in task_result["knowledge_chunks"]:
                            if "source" in chunk:
                                sources.append(chunk["source"])

        # 去重
        return list(set(filter(None, sources)))

    async def _generate_final_answer(
        self,
        user_input: str,
        content: str,
        quality_check: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成最终答案"""
        try:
            # 如果质检未通过，添加改进建议
            quality_context = ""
            if quality_check and not quality_check.get("passed", True):
                suggestions = quality_check.get("suggestions", [])
                if suggestions:
                    quality_context = f"\n\n改进建议：\n" + "\n".join(f"- {s}" for s in suggestions)

            prompt = f"""请基于以下执行结果，生成一个完整、准确、清晰的最终答案。

用户问题：{user_input}

执行结果：
{content[:3000]}  # 限制长度

{quality_context}

要求：
1. 整合所有相关信息
2. 保持逻辑清晰、结构合理
3. 直接回答用户问题
4. 如果有代码，保留代码块格式
5. 如果信息不足，明确说明
6. 使用 Markdown 格式

请生成最终答案："""

            response = await self.llm_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
            )

            final_answer = response.get("content", "")

            return final_answer

        except Exception as e:
            logger.error(f"生成最终答案失败: {e}")
            # 降级方案：直接返回整合的内容
            return content

    def _generate_execution_summary(
        self,
        execution_results: List[Dict[str, Any]],
        plan: Optional[Dict[str, Any]] = None,
        quality_check: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成执行摘要"""
        # 统计执行信息
        total_tasks = len(execution_results)
        success_tasks = sum(1 for r in execution_results if r.get("status") == "success")
        failed_tasks = total_tasks - success_tasks

        # 统计 token 使用
        total_tokens = 0
        for result in execution_results:
            metadata = result.get("metadata", {})
            total_tokens += metadata.get("tokens", 0)

        # 执行路径
        execution_path = plan.get("strategy", "unknown") if plan else "unknown"

        # 质量评分
        quality_score = quality_check.get("score") if quality_check else None
        quality_passed = quality_check.get("passed") if quality_check else None

        summary = {
            "total_tasks": total_tasks,
            "success_tasks": success_tasks,
            "failed_tasks": failed_tasks,
            "execution_path": execution_path,
            "total_tokens": total_tokens,
            "quality_score": quality_score,
            "quality_passed": quality_passed,
        }

        return summary
