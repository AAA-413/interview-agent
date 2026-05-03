"""
智能知识库构建 Agent - 自动识别用户意图并调用 MCP 服务下载资料
"""

import logging
from typing import Any, Dict, List, Optional

from app.modules.agent_orchestration.base_agent import AgentResult

logger = logging.getLogger(__name__)


class KnowledgeBuilderAgent:
    """
    智能知识库构建 Agent

    功能：
    1. 识别用户意图（需要什么资料）
    2. 规划下载策略（从哪里获取）
    3. 调用 MCP 服务下载资料
    4. 自动添加到知识库
    """

    def __init__(
        self,
        llm_provider: Any,
        mcp_service: Any,
        knowledge_service: Any,
        **kwargs,
    ):
        self.name = "KnowledgeBuilderAgent"
        self.llm_provider = llm_provider
        self.mcp_service = mcp_service
        self.knowledge_service = knowledge_service

    async def execute(
        self,
        user_input: str,
        kb_id: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """
        执行智能知识库构建

        Args:
            user_input: 用户输入（如："帮我下载 Python 官方文档"）
            kb_id: 目标知识库 ID（可选，不提供则创建新知识库）
            context: 上下文信息

        Returns:
            AgentResult: 执行结果
        """
        logger.info(f"🤖 开始智能知识库构建: {user_input}")

        try:
            # Step 1: 意图识别
            intent = await self._analyze_intent(user_input)
            logger.info(f"  📋 意图识别: {intent['intent_type']}")
            logger.info(f"  🎯 目标资料: {intent['target_resources']}")

            # Step 2: 规划下载策略
            plan = await self._plan_download_strategy(intent)
            logger.info(f"  📝 下载策略: {len(plan['steps'])} 个步骤")

            # Step 3: 执行下载
            downloaded_files = await self._execute_download(plan)
            logger.info(f"  ✅ 下载完成: {len(downloaded_files)} 个文件")

            # Step 4: 添加到知识库
            kb_result = await self._add_to_knowledge_base(
                downloaded_files, kb_id, intent
            )
            logger.info(f"  📚 知识库更新: {kb_result['chunks_count']} 个片段")

            return AgentResult(
                success=True,
                data={
                    "intent": intent,
                    "plan": plan,
                    "downloaded_files": downloaded_files,
                    "knowledge_base": kb_result,
                },
                message=f"成功下载 {len(downloaded_files)} 个文件，添加 {kb_result['chunks_count']} 个知识片段",
            )

        except Exception as e:
            logger.error(f"❌ 智能知识库构建失败: {e}")
            return AgentResult(
                success=False,
                data={},
                message=f"构建失败: {str(e)}",
            )

    async def _analyze_intent(self, user_input: str) -> Dict[str, Any]:
        """
        意图识别 - 使用 LLM 分析用户想要什么资料

        Returns:
            {
                "intent_type": "download_docs|search_web|fetch_github|...",
                "target_resources": ["资源1", "资源2"],
                "keywords": ["关键词1", "关键词2"],
                "source_preference": "official|github|stackoverflow|...",
                "language": "zh|en"
            }
        """
        prompt = f"""你是一个智能知识库助手。请分析用户的意图，识别他们想要下载什么资料。

用户输入：
{user_input}

请按以下 JSON 格式回复：
{{
  "intent_type": "download_docs|search_web|fetch_github|fetch_arxiv|general_search",
  "target_resources": ["具体资源名称"],
  "keywords": ["关键搜索词"],
  "source_preference": "official|github|stackoverflow|arxiv|general",
  "language": "zh|en",
  "reasoning": "意图分析理由"
}}

示例：

输入："帮我下载 Python 官方文档"
输出：{{"intent_type": "download_docs", "target_resources": ["Python官方文档"], "keywords": ["Python", "documentation"], "source_preference": "official", "language": "zh", "reasoning": "用户明确要求下载Python官方文档"}}

输入："我想学习 FastAPI，帮我找些资料"
输出：{{"intent_type": "search_web", "target_resources": ["FastAPI教程", "FastAPI文档"], "keywords": ["FastAPI", "tutorial", "documentation"], "source_preference": "official", "language": "zh", "reasoning": "用户想学习FastAPI，需要教程和文档"}}

输入："找一些关于分布式系统的论文"
输出：{{"intent_type": "fetch_arxiv", "target_resources": ["分布式系统论文"], "keywords": ["distributed systems", "consensus", "raft"], "source_preference": "arxiv", "language": "en", "reasoning": "用户需要学术论文，应该从arXiv获取"}}

只返回 JSON，不要其他内容。"""

        response = await self.llm_provider.ainvoke(
            [{"role": "user", "content": prompt}]
        )

        # 解析 JSON
        import json
        import re

        content = response.content
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())

        # 默认返回
        return {
            "intent_type": "general_search",
            "target_resources": [user_input],
            "keywords": [user_input],
            "source_preference": "general",
            "language": "zh",
            "reasoning": "无法解析意图，使用通用搜索",
        }

    async def _plan_download_strategy(
        self, intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        规划下载策略 - 使用 LLM 生成下载计划

        Returns:
            {
                "steps": [
                    {
                        "step_id": 1,
                        "action": "fetch_url|search_web|clone_repo|...",
                        "params": {...},
                        "description": "步骤描述"
                    }
                ],
                "estimated_time": "预估时间",
                "estimated_size": "预估大小"
            }
        """
        prompt = f"""你是一个下载策略规划专家。请根据用户意图，规划具体的下载步骤。

用户意图：
{intent}

可用的 MCP 服务：
1. fetch_url(url) - 抓取网页内容
2. search_web(query, num_results) - 搜索网页
3. fetch_github(repo, path) - 获取 GitHub 仓库内容
4. fetch_arxiv(query, max_results) - 搜索 arXiv 论文

请按以下 JSON 格式回复：
{{
  "steps": [
    {{
      "step_id": 1,
      "action": "fetch_url|search_web|fetch_github|fetch_arxiv",
      "params": {{"url": "...", "query": "...", ...}},
      "description": "步骤描述"
    }}
  ],
  "estimated_time": "预估时间（如：2分钟）",
  "estimated_size": "预估大小（如：5MB）"
}}

示例：

意图：下载 Python 官方文档
输出：{{
  "steps": [
    {{"step_id": 1, "action": "fetch_url", "params": {{"url": "https://docs.python.org/zh-cn/3/"}}, "description": "抓取Python官方文档首页"}},
    {{"step_id": 2, "action": "fetch_url", "params": {{"url": "https://docs.python.org/zh-cn/3/tutorial/index.html"}}, "description": "抓取Python教程"}}
  ],
  "estimated_time": "3分钟",
  "estimated_size": "2MB"
}}

只返回 JSON，不要其他内容。"""

        response = await self.llm_provider.ainvoke(
            [{"role": "user", "content": prompt}]
        )

        # 解析 JSON
        import json
        import re

        content = response.content
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())

        # 默认返回
        return {
            "steps": [
                {
                    "step_id": 1,
                    "action": "search_web",
                    "params": {"query": intent["keywords"][0], "num_results": 5},
                    "description": f"搜索 {intent['keywords'][0]}",
                }
            ],
            "estimated_time": "1分钟",
            "estimated_size": "1MB",
        }

    async def _execute_download(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        执行下载 - 调用 MCP 服务

        Returns:
            [
                {
                    "file_path": "下载的文件路径",
                    "content": "文件内容",
                    "metadata": {...}
                }
            ]
        """
        downloaded_files = []

        for step in plan["steps"]:
            logger.info(f"  ⏳ 执行步骤 {step['step_id']}: {step['description']}")

            try:
                if step["action"] == "fetch_url":
                    result = await self.mcp_service.fetch_url(**step["params"])
                elif step["action"] == "search_web":
                    result = await self.mcp_service.search_web(**step["params"])
                elif step["action"] == "fetch_github":
                    result = await self.mcp_service.fetch_github(**step["params"])
                elif step["action"] == "fetch_arxiv":
                    result = await self.mcp_service.fetch_arxiv(**step["params"])
                else:
                    logger.warning(f"  ⚠️ 未知操作: {step['action']}")
                    continue

                downloaded_files.append(
                    {
                        "file_path": result.get("file_path"),
                        "content": result.get("content"),
                        "metadata": {
                            "step_id": step["step_id"],
                            "action": step["action"],
                            "params": step["params"],
                            "description": step["description"],
                        },
                    }
                )

                logger.info(f"    ✅ 下载成功")

            except Exception as e:
                logger.error(f"    ❌ 下载失败: {e}")

        return downloaded_files

    async def _add_to_knowledge_base(
        self,
        downloaded_files: List[Dict[str, Any]],
        kb_id: Optional[int],
        intent: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        添加到知识库

        Returns:
            {
                "kb_id": 知识库ID,
                "kb_name": 知识库名称,
                "chunks_count": 添加的片段数量
            }
        """
        # 如果没有指定知识库，创建新的
        if kb_id is None:
            kb_name = f"{intent['target_resources'][0]} - 自动构建"
            kb = await self.knowledge_service.create_knowledge_base(
                name=kb_name,
                description=f"自动构建的知识库：{intent['reasoning']}",
            )
            kb_id = kb.id
            logger.info(f"  📚 创建新知识库: {kb_name} (ID: {kb_id})")

        # 添加文件到知识库
        total_chunks = 0
        for file_data in downloaded_files:
            try:
                result = await self.knowledge_service.add_document(
                    kb_id=kb_id,
                    content=file_data["content"],
                    metadata=file_data["metadata"],
                )
                total_chunks += result["chunks_count"]
            except Exception as e:
                logger.error(f"  ❌ 添加文档失败: {e}")

        return {
            "kb_id": kb_id,
            "kb_name": intent["target_resources"][0],
            "chunks_count": total_chunks,
        }
