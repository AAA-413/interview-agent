"""
PlanningAgent - 任务规划 Agent

职责：
1. 理解用户意图
2. 检索相关知识
3. 分解任务为子任务
4. 生成执行计划
"""

import logging
from typing import Any, Dict, List, Optional

from app.common.ai.llm_provider_protocol import LLMProvider

logger = logging.getLogger(__name__)


class PlanningAgent:
    """任务规划 Agent"""

    def __init__(
        self,
        llm_provider: LLMProvider,
        knowledge_service: Optional[Any] = None,  # 改为 Any 避免导入错误
    ):
        self.llm_provider = llm_provider
        self.knowledge_service = knowledge_service

    async def plan(
        self,
        user_input: str,
        kb_ids: Optional[List[int]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        生成任务执行计划

        Args:
            user_input: 用户输入
            kb_ids: 知识库ID列表
            context: 额外上下文信息

        Returns:
            任务计划字典，包含：
            - intent: 用户意图
            - complexity: 任务复杂度
            - subtasks: 子任务列表
            - knowledge: 相关知识
            - strategy: 执行策略
        """
        logger.info(f"🎯 开始任务规划: {user_input[:50]}...")

        # 1. 理解用户意图
        intent = await self._classify_intent(user_input)
        logger.info(f"  意图识别: {intent}")

        # 2. 检索相关知识
        knowledge = []
        if self.knowledge_service and kb_ids:
            knowledge = await self._retrieve_knowledge(user_input, kb_ids)
            logger.info(f"  知识检索: {len(knowledge)} 个相关片段")

        # 3. 评估任务复杂度
        complexity = await self._estimate_complexity(user_input, knowledge)
        logger.info(f"  复杂度评估: {complexity}")

        # 4. 分解子任务
        subtasks = await self._decompose_tasks(user_input, intent, knowledge, complexity)
        logger.info(f"  子任务分解: {len(subtasks)} 个子任务")

        # 5. 确定执行策略
        strategy = self._determine_strategy(complexity, subtasks)
        logger.info(f"  执行策略: {strategy}")

        plan = {
            "intent": intent,
            "complexity": complexity,
            "subtasks": subtasks,
            "knowledge": knowledge,
            "strategy": strategy,
            "requires_quality_check": complexity in ["medium", "complex"],
        }

        return plan

    async def _classify_intent(self, user_input: str) -> str:
        """
        识别用户意图

        Returns:
            意图类型：question/code_generation/analysis/debug/design/other
        """
        # 关键词匹配
        keywords = {
            "question": ["什么", "为什么", "如何", "怎么", "是什么", "解释", "介绍"],
            "code_generation": ["写", "实现", "生成", "创建", "开发", "编写代码"],
            "analysis": ["分析", "评估", "比较", "优缺点", "性能"],
            "debug": ["调试", "错误", "bug", "修复", "问题"],
            "design": ["设计", "架构", "方案", "规划"],
        }

        user_input_lower = user_input.lower()
        for intent, words in keywords.items():
            if any(word in user_input_lower for word in words):
                return intent

        # 使用 LLM 进行更精确的意图识别
        try:
            prompt = f"""请识别以下用户输入的意图类型，只返回一个类别：
question（问答）、code_generation（代码生成）、analysis（分析）、debug（调试）、design（设计）、other（其他）

用户输入：{user_input}

只返回类别名称，不要其他内容。"""

            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )

            intent = response.content.strip().lower()
            if intent in ["question", "code_generation", "analysis", "debug", "design"]:
                return intent

        except Exception as e:
            logger.warning(f"LLM 意图识别失败: {e}")

        return "other"

    async def _retrieve_knowledge(
        self,
        query: str,
        kb_ids: List[int],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        检索相关知识

        Returns:
            知识片段列表，每个包含：content、score、source
        """
        if not self.knowledge_service:
            return []

        try:
            results = await self.knowledge_service.search(
                query=query,
                kb_ids=kb_ids,
                top_k=top_k,
            )

            knowledge = []
            for result in results:
                knowledge.append({
                    "content": result.get("content", ""),
                    "score": result.get("score", 0.0),
                    "source": result.get("source", ""),
                    "kb_id": result.get("kb_id"),
                })

            return knowledge

        except Exception as e:
            logger.error(f"知识检索失败: {e}")
            return []

    async def _estimate_complexity(
        self,
        user_input: str,
        knowledge: List[Dict[str, Any]],
    ) -> str:
        """
        评估任务复杂度

        Returns:
            复杂度：simple/medium/complex
        """
        # 基于规则的初步评估
        input_length = len(user_input)
        knowledge_coverage = len(knowledge) / 5.0  # 假设 top_k=5

        # 简单任务特征
        if input_length < 50 and knowledge_coverage > 0.6:
            return "simple"

        # 复杂任务特征
        complex_indicators = ["设计", "架构", "系统", "完整", "详细", "多个", "所有"]
        if any(indicator in user_input for indicator in complex_indicators):
            return "complex"

        if input_length > 200:
            return "complex"

        # 默认中等复杂度
        return "medium"

    async def _decompose_tasks(
        self,
        user_input: str,
        intent: str,
        knowledge: List[Dict[str, Any]],
        complexity: str,
    ) -> List[Dict[str, Any]]:
        """
        分解子任务

        Returns:
            子任务列表，每个包含：
            - id: 子任务ID
            - type: 任务类型
            - description: 任务描述
            - dependencies: 依赖的子任务ID列表
        """
        # 简单任务不需要分解
        if complexity == "simple":
            return [{
                "id": "task_1",
                "type": "knowledge_search",
                "description": "检索知识并生成答案",
                "dependencies": [],
            }]

        # 使用 LLM 分解任务
        try:
            knowledge_context = "\n".join([
                f"- {k['content'][:100]}..." for k in knowledge[:3]
            ]) if knowledge else "无相关知识"

            prompt = f"""请将以下用户任务分解为具体的子任务。

用户任务：{user_input}
任务意图：{intent}
相关知识：
{knowledge_context}

请按照以下格式返回子任务列表（JSON格式）：
[
  {{
    "id": "task_1",
    "type": "knowledge_search | code_analysis | data_processing | design",
    "description": "子任务描述",
    "dependencies": []
  }},
  ...
]

要求：
1. 每个子任务应该是独立、可执行的
2. 子任务之间可以有依赖关系
3. 子任务数量控制在 2-5 个
4. type 只能是：knowledge_search、code_analysis、data_processing、design 之一

只返回 JSON 数组，不要其他内容。"""

            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )

            content = response.content

            # 提取 JSON
            import json
            import re

            # 尝试提取 JSON 数组
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                subtasks = json.loads(json_match.group())

                # 验证格式
                if isinstance(subtasks, list) and len(subtasks) > 0:
                    return subtasks

        except Exception as e:
            logger.warning(f"LLM 任务分解失败: {e}")

        # 降级方案：根据意图生成默认子任务
        return self._generate_default_subtasks(intent)

    def _generate_default_subtasks(self, intent: str) -> List[Dict[str, Any]]:
        """生成默认子任务"""
        # 如果没有知识库服务，不生成 knowledge_search 任务
        has_kb = self.knowledge_service is not None

        if intent == "code_generation":
            if has_kb:
                return [
                    {
                        "id": "task_1",
                        "type": "knowledge_search",
                        "description": "检索相关代码示例和最佳实践",
                        "dependencies": [],
                    },
                    {
                        "id": "task_2",
                        "type": "code_analysis",
                        "description": "生成代码实现",
                        "dependencies": ["task_1"],
                    },
                ]
            else:
                return [
                    {
                        "id": "task_1",
                        "type": "code_analysis",
                        "description": "生成代码实现",
                        "dependencies": [],
                    },
                ]
        elif intent == "design":
            if has_kb:
                return [
                    {
                        "id": "task_1",
                        "type": "knowledge_search",
                        "description": "检索相关设计模式和架构方案",
                        "dependencies": [],
                    },
                    {
                        "id": "task_2",
                        "type": "design",
                        "description": "设计系统架构",
                        "dependencies": ["task_1"],
                    },
                ]
            else:
                return [
                    {
                        "id": "task_1",
                        "type": "design",
                        "description": "设计系统架构",
                        "dependencies": [],
                    },
                ]
        else:
            if has_kb:
                return [
                    {
                        "id": "task_1",
                        "type": "knowledge_search",
                        "description": "检索相关信息",
                        "dependencies": [],
                    },
                    {
                        "id": "task_2",
                        "type": "data_processing",
                        "description": "处理和整合信息",
                        "dependencies": ["task_1"],
                    },
                ]
            else:
                return [
                    {
                        "id": "task_1",
                        "type": "data_processing",
                        "description": "处理和整合信息",
                        "dependencies": [],
                    },
                ]

    def _determine_strategy(
        self,
        complexity: str,
        subtasks: List[Dict[str, Any]],
    ) -> str:
        """
        确定执行策略

        Returns:
            策略：sequential（顺序）/parallel（并行）/hybrid（混合）
        """
        # 简单任务：顺序执行
        if complexity == "simple" or len(subtasks) <= 1:
            return "sequential"

        # 检查是否有依赖关系
        has_dependencies = any(task.get("dependencies") for task in subtasks)

        if has_dependencies:
            return "hybrid"  # 有依赖的并行执行
        else:
            return "parallel"  # 完全并行执行

    async def plan_download(
        self,
        user_input: str,
        max_downloads: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        生成智能下载计划

        Args:
            user_input: 用户需求描述（如："我想学习FastAPI"）
            max_downloads: 最大下载数量
            context: 额外上下文

        Returns:
            下载计划，包含：
            - intent: 意图分析（topic、resource_types、keywords）
            - tasks: 下载任务列表
            - estimated_time: 估算时间
            - estimated_size: 估算大小
        """
        logger.info(f"📋 生成下载计划: {user_input}")

        # 1. 分析用户意图
        intent = await self._analyze_download_intent(user_input)
        logger.info(f"  意图分析: {intent}")

        # 2. 生成下载任务
        tasks = await self._generate_download_tasks(intent, max_downloads)
        logger.info(f"  生成任务: {len(tasks)} 个")

        # 3. 估算时间和大小
        estimated_time = f"{len(tasks) * 30}秒"
        estimated_size = f"{len(tasks) * 500}KB"

        return {
            "intent": intent,
            "tasks": tasks,
            "estimated_time": estimated_time,
            "estimated_size": estimated_size,
        }

    async def _analyze_download_intent(self, user_input: str) -> Dict[str, Any]:
        """
        分析下载意图

        Returns:
            {
                "topic": "主题",
                "resource_types": ["official", "blog", "tutorial"],
                "keywords": ["关键词1", "关键词2"],
                "target_resources": ["资源1", "资源2"]
            }
        """
        try:
            prompt = f"""请分析用户的下载需求，提取关键信息。

用户输入：{user_input}

请以 JSON 格式返回分析结果：
{{
  "topic": "主题（如：FastAPI、Python、机器学习）",
  "resource_types": ["资源类型列表，可选：official（官方文档）、blog（博客文章）、tutorial（教程）、github（GitHub项目）、arxiv（学术论文）"],
  "keywords": ["关键词列表，用于搜索"],
  "target_resources": ["具体目标资源列表"],
  "repo_name": "如果识别到具体 GitHub 仓库名，填写完整仓库名（如 owner/repo 或 repo-name），否则为 null"
}}

要求：
1. topic 应该是简洁的主题名称
2. 识别 GitHub 仓库名的规则：
   - "owner/repo" 格式（如 "anthropics/learn-claude-code"）→ 明确是 GitHub 仓库
   - 连字符命名且包含 learn/starter/boilerplate/template/example 等词（如 "learn-claude-code"、"fastapi-starter"）→ 很可能是 GitHub 仓库
   - 用户明确提到 "github"、"仓库"、"repo"、"项目" → GitHub 类型
   - 以上情况 resource_types 必须包含 "github"，repo_name 填写仓库名
3. 区分"下载特定项目"和"学习某主题"：
   - "下载/获取/拉取/clone xxx" → github 类型
   - "学习 xxx 使用方法/教程" → tutorial/official 类型
4. resource_types 至少包含1个类型
5. keywords 提取3-5个关键词
6. target_resources 列出可能的具体资源

只返回 JSON，不要其他内容。"""

            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )

            content = response.content or "{}"

            # 提取 JSON
            import json
            import re

            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                intent = json.loads(json_match.group())
                return intent

        except Exception as e:
            logger.warning(f"LLM 意图分析失败: {e}")

        # 降级方案：基于关键词的简单分析
        return self._simple_intent_analysis(user_input)

    def _simple_intent_analysis(self, user_input: str) -> Dict[str, Any]:
        """简单的意图分析（降级方案）"""
        # 提取主题（简单实现：取第一个名词）
        words = user_input.split()
        topic = words[0] if words else "未知主题"

        # 检测资源类型
        resource_types = []
        if "官方" in user_input or "文档" in user_input:
            resource_types.append("official")
        if "博客" in user_input or "文章" in user_input:
            resource_types.append("blog")
        if "教程" in user_input:
            resource_types.append("tutorial")
        if "github" in user_input.lower():
            resource_types.append("github")

        if not resource_types:
            resource_types = ["official", "blog"]  # 默认

        # 提取关键词
        keywords = [w for w in words if len(w) > 1][:5]

        return {
            "topic": topic,
            "resource_types": resource_types,
            "keywords": keywords,
            "target_resources": [],
        }

    async def _generate_download_tasks(
        self,
        intent: Dict[str, Any],
        max_downloads: int,
    ) -> List[Dict[str, Any]]:
        """
        生成下载任务列表

        Returns:
            任务列表，每个任务包含：
            - id: 任务ID
            - type: 任务类型（fetch_url/search_web/fetch_blog）
            - description: 描述
            - url: URL（如果有）
            - query: 搜索关键词（如果是搜索任务）
            - num_results: 结果数量
        """
        try:
            topic = intent.get("topic", "")
            resource_types = intent.get("resource_types", [])
            keywords = intent.get("keywords", [])
            repo_name = intent.get("repo_name")

            # 如果识别到具体仓库名，构造仓库信息提示
            repo_hint = ""
            if repo_name:
                repo_hint = f"\n具体仓库：{repo_name}（用户指定了此仓库，必须用 fetch_github_repo 直接抓取）"

            prompt = f"""请为以下主题生成下载任务列表。

主题：{topic}
资源类型：{', '.join(resource_types)}
关键词：{', '.join(keywords)}
最大任务数：{max_downloads}{repo_hint}

请以 JSON 数组格式返回任务列表：

可用的任务类型：
1. fetch_url — 直接抓取URL，需要 url 字段
2. search_web — 搜索后抓取，需要 query 和 num_results 字段
3. fetch_blog — 抓取博客，需要 url 字段
4. search_github — 搜索 GitHub 仓库，需要 query 和 num_results 字段，可选 dynamic（true=自动抓取结果中的仓库文档）和 max_repos_to_fetch
5. fetch_github_repo — 直接抓取指定 GitHub 仓库的文档和源码，需要 repo 字段（格式：owner/repo）

示例：
[
  {{
    "id": "task_1",
    "type": "fetch_github_repo",
    "description": "抓取 learn-claude-code 仓库的文档和源码",
    "repo": "anthropics/learn-claude-code"
  }},
  {{
    "id": "task_2",
    "type": "search_web",
    "description": "搜索 FastAPI 入门教程",
    "query": "FastAPI 入门教程",
    "num_results": 3
  }},
  {{
    "id": "task_3",
    "type": "search_github",
    "description": "搜索 GitHub 上的 FastAPI 示例项目",
    "query": "FastAPI example",
    "num_results": 3,
    "dynamic": true,
    "max_repos_to_fetch": 2
  }}
]

要求：
1. 当 resource_types 包含 "github" 时，必须生成至少一个 GitHub 任务（search_github 或 fetch_github_repo）
2. 当用户指定了具体仓库名（repo_name 不为空）时，必须用 fetch_github_repo 直接抓取该仓库
3. 优先生成 official 类型的资源
4. 任务数量不超过 {max_downloads} 个
5. 每个任务都要有清晰的 description

只返回 JSON 数组，不要其他内容。"""

            from langchain_core.messages import HumanMessage
            response = await self.llm_provider.ainvoke(
                [HumanMessage(content=prompt)]
            )

            content = response.content

            # 提取 JSON
            import json
            import re

            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                tasks = json.loads(json_match.group())

                # 验证和限制数量
                if isinstance(tasks, list) and len(tasks) > 0:
                    # 验证和补全必需字段
                    validated_tasks = []
                    for task in tasks[:max_downloads]:
                        task_type = task.get("type", "")

                        # search_web 必须有 query 字段
                        if task_type == "search_web" and "query" not in task:
                            # 从 description 提取关键词作为 query
                            task["query"] = task.get("description", topic)
                            if "num_results" not in task:
                                task["num_results"] = 3

                        # fetch_url/fetch_blog 必须有 url 字段
                        if task_type in ["fetch_url", "fetch_blog"] and "url" not in task:
                            logger.warning(f"任务 {task.get('id')} 缺少 url 字段，跳过")
                            continue

                        validated_tasks.append(task)

                    if validated_tasks:
                        return validated_tasks

        except Exception as e:
            logger.warning(f"LLM 任务生成失败: {e}")

        # 降级方案：生成默认任务
        return self._generate_default_download_tasks(intent, max_downloads)

    def _generate_default_download_tasks(
        self,
        intent: Dict[str, Any],
        max_downloads: int,
    ) -> List[Dict[str, Any]]:
        """生成默认下载任务（降级方案）"""
        topic = intent.get("topic", "")
        resource_types = intent.get("resource_types", [])
        keywords = intent.get("keywords", [])

        tasks = []
        task_id = 1

        # 生成GitHub搜索任务
        if "github" in resource_types and task_id <= max_downloads:
            tasks.append({
                "id": f"task_{task_id}",
                "type": "search_github",
                "description": f"搜索 {topic} 相关的GitHub项目",
                "query": f"{topic} {' '.join(keywords[:2])}",
                "language": self._detect_language(topic),
                "num_results": 3,
                "dynamic": True,  # 标记为动态任务
                "max_repos_to_fetch": 2,  # 最多抓取2个仓库
            })
            task_id += 1

        # 生成搜索任务
        if "official" in resource_types and task_id <= max_downloads:
            tasks.append({
                "id": f"task_{task_id}",
                "type": "search_web",
                "description": f"搜索 {topic} 官方文档",
                "query": f"{topic} 官方文档",
                "num_results": 2,
            })
            task_id += 1

        if "blog" in resource_types and task_id <= max_downloads:
            tasks.append({
                "id": f"task_{task_id}",
                "type": "search_web",
                "description": f"搜索 {topic} 博客文章",
                "query": f"{topic} 教程 博客",
                "num_results": 3,
            })
            task_id += 1

        if "tutorial" in resource_types and task_id <= max_downloads:
            tasks.append({
                "id": f"task_{task_id}",
                "type": "search_web",
                "description": f"搜索 {topic} 入门教程",
                "query": f"{topic} 入门教程",
                "num_results": 2,
            })
            task_id += 1

        # 如果没有生成任何任务，至少生成一个通用搜索
        if not tasks:
            tasks.append({
                "id": "task_1",
                "type": "search_web",
                "description": f"搜索 {topic} 相关资料",
                "query": topic,
                "num_results": 5,
            })

        return tasks[:max_downloads]

    def _detect_language(self, topic: str) -> str:
        """检测编程语言"""
        topic_lower = topic.lower()

        language_keywords = {
            "python": ["python", "django", "flask", "fastapi", "pytorch", "tensorflow"],
            "javascript": ["javascript", "js", "react", "vue", "angular", "node", "nodejs"],
            "typescript": ["typescript", "ts"],
            "java": ["java", "spring", "springboot"],
            "go": ["go", "golang"],
            "rust": ["rust"],
            "cpp": ["c++", "cpp"],
            "csharp": ["c#", "csharp", ".net"],
            "ruby": ["ruby", "rails"],
            "php": ["php", "laravel"],
        }

        for lang, keywords in language_keywords.items():
            if any(keyword in topic_lower for keyword in keywords):
                return lang

        return ""  # 未检测到特定语言
