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
from app.modules.agent_orchestration.schemas import AgentMessage

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
    ) -> AgentMessage:
        """
        执行任务

        Args:
            task: 任务信息，包含 id、type、description、dependencies
            context: 执行上下文，包含知识、前置任务结果等

        Returns:
            AgentMessage 统一消息，包含 task_id、agent_type、status、result、error、metadata
        """
        pass

    def _build_result(
        self,
        task_id: str,
        status: str,
        result: Any = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentMessage:
        """构建标准化的执行结果"""
        return AgentMessage(
            task_id=task_id,
            agent_type=self.agent_type,
            status=status,
            result=result,
            error=error,
            metadata=metadata or {},
        )

    async def call_tool(
        self,
        context: Optional[Dict[str, Any]],
        tool_name: str,
        **kwargs,
    ) -> Any:
        """通过 context 中的 tool_registry 调用注册工具"""
        registry = (context or {}).get("tool_registry")
        if registry is None:
            raise RuntimeError(f"tool_registry 未注入上下文，无法调用工具: {tool_name}")
        return await registry.execute_tool(tool_name, **kwargs)


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

            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )

            answer = response.content or ""

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

            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )

            code = response.content or ""

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

            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )

            processed_data = response.content or ""

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

            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )

            design = response.content or ""

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


class DownloadExecutionAgent(ExecutionAgent):
    """下载执行 Agent - 专门用于智能下载功能"""

    def __init__(self, llm_provider: LLMProvider, mcp_service):
        super().__init__("download_execution", llm_provider)
        self.mcp_service = mcp_service

    async def execute(
        self,
        task: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行下载任务

        Args:
            task: 下载任务，包含 type、url、query 等
            context: 上下文信息

        Returns:
            执行结果，包含下载的内容和元数据
        """
        task_id = task.get("id", "unknown")
        task_type = task.get("type", "")
        description = task.get("description", "")

        logger.info(f"📥 执行下载任务: {description}")

        try:
            # 根据任务类型执行不同的下载操作
            if task_type == "fetch_url":
                result = await self._fetch_url(task)
            elif task_type == "search_web":
                result = await self._search_web(task)
            elif task_type == "fetch_blog":
                result = await self._fetch_blog(task)
            else:
                raise ValueError(f"未知的任务类型: {task_type}")

            return self._build_result(
                task_id=task_id,
                status="success",
                result=result,
                metadata={
                    "task_type": task_type,
                    "content_size": len(result.get("content", "")),
                },
            )

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"下载任务失败: {e}")
            logger.error(f"详细错误:\n{error_detail}")
            return self._build_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )

    async def _fetch_url(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """直接抓取URL"""
        url = task.get("url")
        if not url:
            raise ValueError("缺少 URL 参数")

        logger.info(f"  抓取URL: {url}")

        result = await self.mcp_service.fetch_url(url)
        raw_content = result.get("content", "")

        # 内容清洗和结构化
        logger.info(f"  开始清洗内容，原始长度: {len(raw_content)}")
        cleaned_content = await self._clean_content(
            raw_content=raw_content,
            task_description=task.get("description", ""),
            source_type="url"
        )
        logger.info(f"  清洗完成，清洗后长度: {len(cleaned_content)}")

        return {
            "content": cleaned_content,
            "metadata": {
                "url": url,
                "source_type": "url",
                "description": task.get("description", ""),
                "raw_length": len(raw_content),
                "cleaned_length": len(cleaned_content),
            },
        }

    async def _search_web(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """搜索网页并抓取结果"""
        query = task.get("query")
        num_results = task.get("num_results", 3)

        if not query:
            raise ValueError("缺少 query 参数")

        logger.info(f"  搜索: {query} (前{num_results}个结果)")

        try:
            result = await self.mcp_service.search_web(query, num_results)
            raw_content = result.get("content", "")

            # 添加详细日志
            logger.info(f"  搜索返回结果: content长度={len(raw_content)}, results数量={len(result.get('results', []))}")

            # 内容清洗和结构化
            logger.info(f"  开始清洗搜索内容")
            cleaned_content = await self._clean_content(
                raw_content=raw_content,
                task_description=task.get("description", ""),
                source_type="search"
            )
            logger.info(f"  清洗完成，清洗后长度: {len(cleaned_content)}")

            return {
                "content": cleaned_content,
                "results": result.get("results", []),
                "metadata": {
                    "query": query,
                    "num_results": num_results,
                    "source_type": "search",
                    "description": task.get("description", ""),
                    "raw_length": len(raw_content),
                    "cleaned_length": len(cleaned_content),
                },
            }
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"  搜索异常: {e}")
            logger.error(f"  详细错误:\n{error_detail}")
            raise

    async def _fetch_blog(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """抓取博客文章"""
        url = task.get("url")
        if not url:
            raise ValueError("缺少 URL 参数")

        logger.info(f"  抓取博客: {url}")

        result = await self.mcp_service.fetch_blog(url)

        return {
            "content": result.get("content", ""),
            "title": result.get("title", ""),
            "author": result.get("author", ""),
            "metadata": {
                "url": url,
                "platform": result.get("metadata", {}).get("platform", ""),
                "source_type": "blog",
                "description": task.get("description", ""),
            },
        }

    async def _clean_content(self, raw_content: str, task_description: str, source_type: str) -> str:
        """
        清洗和结构化内容

        Args:
            raw_content: 原始内容
            task_description: 任务描述
            source_type: 来源类型（url/search/blog）

        Returns:
            清洗后的 Markdown 格式内容
        """
        if not raw_content or len(raw_content.strip()) < 100:
            logger.warning(f"  内容过短或为空，跳过清洗")
            return raw_content

        # 限制输入长度，避免 token 超限
        content_to_clean = raw_content[:4000]

        prompt = f"""请清洗和结构化以下网页内容，提取核心知识：

任务描述：{task_description}
来源类型：{source_type}

原始内容：
{content_to_clean}

要求：
1. 移除导航、广告、页脚、版权声明等无关内容
2. 提取核心知识点、概念定义、使用方法
3. 保留所有代码示例（使用 Markdown 代码块格式）
4. 使用清晰的 Markdown 格式（# 标题、- 列表、```代码块```）
5. 保留关键术语的英文原文（如 async/await）
6. 控制在 1500 字以内

输出清洗后的 Markdown 文档："""

        try:
            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke([HumanMessage(content=prompt)])

            cleaned = response.content or ""

            # 如果清洗后内容过短，返回原始内容
            if len(cleaned.strip()) < 50:
                logger.warning(f"  清洗后内容过短，使用原始内容")
                return raw_content

            return cleaned

        except Exception as e:
            logger.error(f"  内容清洗失败: {e}，返回原始内容")
            return raw_content

    async def integrate_contents(
        self,
        execution_results: List[Dict[str, Any]],
        user_input: str,
    ) -> Dict[str, Any]:
        """
        整合多个搜索结果为一篇综合文档

        Args:
            execution_results: 执行结果列表
            user_input: 用户原始需求

        Returns:
            整合后的文档，包含：
            - integrated_content: 整合后的内容
            - title: 文档标题
            - summary: 文档摘要
            - sources: 来源列表
        """
        logger.info(f"🔄 开始整合 {len(execution_results)} 个搜索结果")
        logger.info(f"📋 execution_results 类型: {type(execution_results)}")
        logger.info(f"📋 execution_results 内容: {execution_results}")

        # 提取所有成功的内容
        contents = []
        sources = []

        for i, result in enumerate(execution_results):
            if result is None:
                logger.warning(f"  结果{i+1}: None (跳过)")
                continue

            if not isinstance(result, dict):
                logger.warning(f"  结果{i+1}: 不是字典类型 (type={type(result)}), 跳过")
                continue

            logger.info(f"  结果{i+1}: status={result.get('status')}, has_result={bool(result.get('result'))}")

            if result.get("status") != "success":
                continue

            task_result = result.get("result", {})
            if not isinstance(task_result, dict):
                logger.warning(f"  结果{i+1}: task_result不是字典类型, 跳过")
                continue

            content = task_result.get("content", "")
            metadata = task_result.get("metadata", {})

            logger.info(f"    content_length={len(content)}, metadata={metadata}")

            if content and len(content.strip()) > 50:  # 降低过滤阈值从100到50
                contents.append({
                    "content": content,
                    "source": metadata.get("url") or metadata.get("query", ""),
                    "description": metadata.get("description", ""),
                })
                sources.append(metadata.get("url") or metadata.get("query", ""))

        if not contents:
            logger.error(f"❌ 没有有效内容可整合。执行结果数: {len(execution_results)}")
            for i, result in enumerate(execution_results):
                if result is None:
                    logger.error(f"  结果{i+1}: None")
                elif not isinstance(result, dict):
                    logger.error(f"  结果{i+1}: 不是字典类型 (type={type(result)})")
                else:
                    result_data = result.get('result', {})
                    content_len = len(result_data.get('content', '')) if isinstance(result_data, dict) else 0
                    logger.error(f"  结果{i+1}: status={result.get('status')}, content_length={content_len}")
            raise ValueError("没有有效的内容可以整合，请检查搜索引擎配置或网络连接")

        logger.info(f"  有效内容数: {len(contents)}")

        # 为每个源生成独立摘要
        source_summaries = []
        for i, item in enumerate(contents):
            try:
                summary_prompt = f"用50字以内概括以下内容的核心要点：\n\n{item['content'][:1000]}"
                summary_resp = await self.llm_provider.ainvoke([HumanMessage(content=summary_prompt)])
                source_summaries.append({
                    "source": item["source"],
                    "description": item["description"],
                    "summary": (summary_resp.content or "")[:200] if summary_resp else "",
                })
            except Exception as e:
                logger.warning("源 %d 摘要生成失败: %s", i + 1, e)
                source_summaries.append({
                    "source": item["source"],
                    "description": item["description"],
                    "summary": item["content"][:200],
                })

        from langchain_core.messages import HumanMessage

        # S-P3: 分层合成策略 — 超过3源时先分组摘要，再合并
        if len(contents) <= 3:
            # 少量来源：直接整合
            content_blocks = []
            for i, item in enumerate(contents, 1):
                content_blocks.append(
                    f"## 来源 {i}: {item['description']}\n"
                    f"URL: {item['source']}\n\n"
                    f"{item['content'][:2000]}\n"
                )
            combined_content = "\n\n---\n\n".join(content_blocks)

            prompt = f"""用户需求："{user_input}"

请将以下资料整合为一篇简洁的文档（3000字以内）：

{combined_content}

要求：
1. 提取核心知识点和关键概念
2. 保留所有代码示例（使用 Markdown 代码块）
3. 使用清晰的 Markdown 格式（标题、列表、代码块）
4. 保持结构清晰，便于阅读
5. 如果有多个来源，综合不同视角的信息

输出整合文档："""

            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )
        else:
            # S-P3: 超过3源 → 分组摘要 → 合并整合
            logger.info(f"  内容数 {len(contents)} > 3，启用分层合成策略")
            group_size = 3
            groups = [contents[i:i + group_size] for i in range(0, len(contents), group_size)]
            logger.info(f"  分为 {len(groups)} 组，每组最多 {group_size} 个来源")

            group_summaries = []
            for g_idx, group in enumerate(groups):
                group_blocks = []
                for i, item in enumerate(group, 1):
                    group_blocks.append(
                        f"## 来源 {i}: {item['description']}\n"
                        f"URL: {item['source']}\n\n"
                        f"{item['content'][:2000]}\n"
                    )
                group_combined = "\n\n---\n\n".join(group_blocks)

                group_prompt = f"""用户需求："{user_input}"

请将以下 {len(group)} 个来源的资料整合为一段摘要（500字以内），保留关键知识点和代码示例：

{group_combined}

要求：
1. 提取核心知识点
2. 保留重要代码示例（Markdown 代码块）
3. 保留来源引用
4. 输出纯 Markdown 文本，不要输出标题"""

                logger.info(f"    第 {g_idx + 1}/{len(groups)} 组摘要生成中...")
                group_resp = await self.llm_provider.ainvoke(
                    [HumanMessage(content=group_prompt)]
                )
                group_text = (group_resp.content or "") if group_resp else ""
                if group_text.strip():
                    group_summaries.append(group_text.strip())
                    logger.info(f"    第 {g_idx + 1} 组摘要完成: {len(group_text)} 字符")
                else:
                    logger.warning(f"    第 {g_idx + 1} 组摘要为空，跳过")

            if not group_summaries:
                raise ValueError("分层合成失败：所有分组摘要均为空")

            # 合并所有分组摘要，进行最终整合
            merged_content = "\n\n---\n\n".join(
                f"## 分组 {i + 1} 摘要\n\n{s}" for i, s in enumerate(group_summaries)
            )

            final_prompt = f"""用户需求："{user_input}"

请将以下多组摘要整合为一篇简洁的文档（3000字以内）：

{merged_content}

要求：
1. 综合各组信息，提取核心知识点和关键概念
2. 保留所有代码示例（使用 Markdown 代码块）
3. 使用清晰的 Markdown 格式（标题、列表、代码块）
4. 保持结构清晰，便于阅读
5. 去除重复信息，合并相关主题

输出整合文档："""

            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=final_prompt)]
            )

        if not response:
            logger.error("❌ LLM返回空响应")
            raise ValueError("LLM整合失败：返回空响应")

        integrated_content = response.content or ""
        if not integrated_content:
            logger.error("❌ LLM返回的content为空")
            raise ValueError("LLM整合失败：返回内容为空")

        # 生成标题和摘要
        title_prompt = f"""基于以下内容，生成一个简洁的标题（10字以内）和摘要（50字以内）：

用户需求：{user_input}

内容：
{integrated_content[:500]}

请以JSON格式输出：
{{"title": "标题", "summary": "摘要"}}"""

        title_response = await self.llm_provider.ainvoke(
            [HumanMessage(content=title_prompt)]
        )

        # 解析标题和摘要
        import json
        try:
            if not title_response:
                logger.warning("标题生成返回空响应，使用默认值")
                title = user_input[:20]
                summary = integrated_content[:100]
            else:
                title_data = json.loads(title_response.content or "{}")
                title = title_data.get("title", user_input[:20])
                summary = title_data.get("summary", "")
        except Exception as e:
            logger.warning(f"解析标题失败: {e}，使用默认值")
            title = user_input[:20]
            summary = integrated_content[:100]

        logger.info(f"✅ 内容整合完成，标题: {title}")

        return {
            "integrated_content": integrated_content,
            "title": title,
            "summary": summary,
            "sources": sources,
            "source_count": len(contents),
            "total_length": len(integrated_content),
            "source_summaries": source_summaries,
        }


class GitHubExecutionAgent(ExecutionAgent):
    """GitHub执行 Agent - 专门处理GitHub相关任务"""

    def __init__(self, llm_provider: LLMProvider, github_service):
        super().__init__("github_execution", llm_provider)
        self.github_service = github_service

    async def execute(
        self,
        task: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行GitHub任务

        Args:
            task: GitHub任务，包含 type、repo、query 等
            context: 上下文信息

        Returns:
            执行结果
        """
        task_id = task.get("id", "unknown")
        task_type = task.get("type", "")
        description = task.get("description", "")

        logger.info(f"🐙 执行GitHub任务: {description}")

        try:
            # 根据任务类型执行不同的操作
            if task_type == "search_github":
                result = await self._search_github(task)
            elif task_type == "fetch_github_repo":
                result = await self._fetch_github_repo(task)
            elif task_type == "fetch_github_file":
                result = await self._fetch_github_file(task)
            else:
                raise ValueError(f"未知的GitHub任务类型: {task_type}")

            return self._build_result(
                task_id=task_id,
                status="success",
                result=result,
                metadata={
                    "task_type": task_type,
                },
            )

        except Exception as e:
            logger.error(f"GitHub任务失败: {e}")
            return self._build_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )

    async def _search_github(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        搜索GitHub仓库

        Args:
            task: 包含 query、language、num_results 等参数

        Returns:
            搜索结果，包含仓库列表
        """
        query = task.get("query")
        language = task.get("language", "")
        sort = task.get("sort", "stars")
        num_results = task.get("num_results", 5)

        if not query:
            raise ValueError("缺少 query 参数")

        logger.info(f"  搜索GitHub: {query}")

        repos = await self.github_service.search_repositories(
            query=query,
            language=language,
            sort=sort,
            per_page=num_results,
        )

        # 生成内容摘要
        content_parts = []
        for i, repo in enumerate(repos, 1):
            content_parts.append(
                f"## {i}. {repo['full_name']} (⭐{repo['stars']})\n\n"
                f"{repo['description']}\n\n"
                f"语言: {repo['language']}\n"
                f"链接: {repo['url']}"
            )

        content = "\n\n---\n\n".join(content_parts)

        return {
            "content": content,
            "repos": repos,
            "metadata": {
                "query": query,
                "num_results": len(repos),
                "source_type": "github_search",
            },
        }

    async def _fetch_github_repo(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        抓取GitHub仓库的文档

        Args:
            task: 包含 repo 参数（格式：owner/repo）

        Returns:
            仓库文档集合
        """
        repo = task.get("repo")
        if not repo:
            raise ValueError("缺少 repo 参数")

        logger.info(f"  抓取仓库: {repo}")

        result = await self.github_service.fetch_repo_docs(
            repo=repo,
            include_readme=True,
            max_files=20,
        )

        # 合并所有文档内容
        content_parts = []
        for doc in result["documents"]:
            content_parts.append(
                f"# {doc['path']}\n\n{doc['content']}"
            )

        content = "\n\n---\n\n".join(content_parts)

        return {
            "content": content,
            "repo": repo,
            "documents": result["documents"],
            "total_docs": result["total_docs"],
            "metadata": {
                "repo": repo,
                "source_type": "github_repo",
            },
        }

    async def _fetch_github_file(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        抓取GitHub单个文件

        Args:
            task: 包含 repo、file_path 参数

        Returns:
            文件内容
        """
        repo = task.get("repo")
        file_path = task.get("file_path")

        if not repo or not file_path:
            raise ValueError("缺少 repo 或 file_path 参数")

        logger.info(f"  抓取文件: {repo}/{file_path}")

        content = await self.github_service.get_file_content(repo, file_path)

        if not content:
            raise ValueError(f"无法获取文件内容: {file_path}")

        return {
            "content": content,
            "metadata": {
                "repo": repo,
                "file_path": file_path,
                "source_type": "github_file",
            },
        }


# Agent 工厂
class ExecutionAgentFactory:
    """执行 Agent 工厂"""

    @staticmethod
    def create_agent(
        agent_type: str,
        llm_provider: LLMProvider,
        knowledge_service=None,
        mcp_service=None,
        github_service=None,
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
        elif agent_type == "download_execution":
            if not mcp_service:
                raise ValueError("DownloadExecutionAgent 需要 mcp_service")
            return DownloadExecutionAgent(llm_provider, mcp_service)
        elif agent_type == "github_execution":
            if not github_service:
                raise ValueError("GitHubExecutionAgent 需要 github_service")
            return GitHubExecutionAgent(llm_provider, github_service)
        else:
            raise ValueError(f"未知的 Agent 类型: {agent_type}")
