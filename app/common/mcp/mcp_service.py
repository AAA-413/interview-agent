"""
MCP 服务接口 - 封装各种资源获取能力
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MCPService:
    """
    MCP (Model Context Protocol) 服务

    提供统一的资源获取接口：
    - 网页抓取
    - 网页搜索
    - GitHub 仓库
    - arXiv 论文
    - 等等...
    """

    def __init__(self, document_fetcher=None):
        """
        Args:
            document_fetcher: 文档抓取器（已有的 DocumentFetcher）
        """
        self.document_fetcher = document_fetcher
        if not self.document_fetcher:
            # 使用全局实例
            from app.common.tools.document_fetcher import document_fetcher as global_fetcher

            self.document_fetcher = global_fetcher

    async def fetch_url(self, url: str, max_length: int = 10000) -> Dict[str, Any]:
        """
        抓取网页内容

        Args:
            url: 网页 URL
            max_length: 最大长度

        Returns:
            {
                "content": "网页内容",
                "file_path": "临时文件路径",
                "metadata": {...}
            }
        """
        logger.info(f"📥 抓取网页: {url}")

        if self.document_fetcher:
            # 使用已有的 DocumentFetcher
            result = await self.document_fetcher.fetch(url, raw=False)

            content = result.get("content", "")
            if max_length and len(content) > max_length:
                content = content[:max_length] + "\n\n[内容已截断...]"

            return {
                "content": content,
                "title": result.get("title", ""),
                "file_path": None,
                "metadata": {
                    "url": url,
                    "source": "web",
                    "max_length": max_length,
                    "title": result.get("title", ""),
                },
            }
        else:
            raise NotImplementedError("DocumentFetcher 未配置")

    async def search_web(self, query: str, num_results: int = 5) -> Dict[str, Any]:
        """
        搜索网页

        Args:
            query: 搜索关键词
            num_results: 结果数量

        Returns:
            {
                "content": "搜索结果（合并）",
                "results": [{"title": "...", "url": "...", "snippet": "..."}],
                "metadata": {...}
            }
        """
        logger.info(f"🔍 搜索网页: {query}")

        try:
            # 使用真实搜索服务
            import os

            from app.common.tools.search_service import search_service

            # 从环境变量读取搜索引擎配置
            engine = os.getenv("SEARCH_ENGINE", "tavily")

            result = await search_service.search(
                query=query,
                num_results=num_results,
                engine=engine,
            )

            return result

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            # 降级到模拟搜索
            return await self._mock_search(query, num_results)

    async def _mock_search(self, query: str, num_results: int) -> Dict[str, Any]:
        """模拟搜索（降级方案）"""
        logger.warning("⚠️ 使用模拟搜索结果")

        mock_results = [
            {
                "title": f"{query} - 官方文档",
                "url": f"https://example.com/{query.replace(' ', '-')}/docs",
                "snippet": f"这是关于 {query} 的官方文档，包含详细的使用说明和API参考...",
            },
            {
                "title": f"{query} 入门教程",
                "url": f"https://example.com/tutorial/{query.replace(' ', '-')}",
                "snippet": f"本教程将带你快速入门 {query}，从基础概念到实战应用...",
            },
            {
                "title": f"{query} 最佳实践",
                "url": f"https://example.com/best-practices/{query.replace(' ', '-')}",
                "snippet": f"总结了 {query} 开发中的最佳实践和常见陷阱...",
            },
        ][:num_results]

        # 合并搜索结果内容
        content_parts = []
        for i, result in enumerate(mock_results, 1):
            content_parts.append(f"## 结果 {i}: {result['title']}\n\n{result['snippet']}\n\n来源: {result['url']}")

        content = "\n\n---\n\n".join(content_parts)

        return {
            "content": content,
            "results": mock_results,
            "metadata": {
                "query": query,
                "num_results": num_results,
                "source": "mock",
                "is_mock": True,
            },
        }

    async def fetch_github(self, repo: str, path: str = "", branch: str = "main") -> Dict[str, Any]:
        """
        获取 GitHub 仓库内容

        Args:
            repo: 仓库名（如：fastapi/fastapi）
            path: 文件路径（可选）
            branch: 分支名

        Returns:
            {
                "content": "文件内容或README",
                "file_path": "文件路径",
                "metadata": {...}
            }
        """
        logger.info(f"📦 获取 GitHub: {repo}/{path}")

        # TODO: 使用 GitHub API
        # 这里先返回模拟数据
        return {
            "content": f"GitHub 内容：{repo}/{path}（待实现）",
            "file_path": None,
            "metadata": {
                "repo": repo,
                "path": path,
                "branch": branch,
                "source": "github",
            },
        }

    async def fetch_arxiv(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        搜索 arXiv 论文

        Args:
            query: 搜索关键词
            max_results: 最大结果数

        Returns:
            {
                "content": "论文摘要（合并）",
                "papers": [{"title": "...", "abstract": "...", "url": "..."}],
                "metadata": {...}
            }
        """
        logger.info(f"📄 搜索 arXiv: {query}")

        # TODO: 使用 arXiv API
        # 这里先返回模拟数据
        return {
            "content": f"arXiv 论文：{query}（待实现）",
            "papers": [],
            "metadata": {
                "query": query,
                "max_results": max_results,
                "source": "arxiv",
            },
        }

    async def fetch_blog(self, url: str, max_length: int = 20000) -> Dict[str, Any]:
        """
        抓取博客文章（支持知名博客网站）

        支持的网站：
        - CSDN (blog.csdn.net)
        - 掘金 (juejin.cn)
        - 知乎 (zhuanlan.zhihu.com)
        - 简书 (jianshu.com)
        - Medium (medium.com)
        - 博客园 (cnblogs.com)
        - SegmentFault (segmentfault.com)

        Args:
            url: 博客文章 URL
            max_length: 最大长度

        Returns:
            {
                "content": "文章内容（Markdown格式）",
                "title": "文章标题",
                "author": "作者",
                "metadata": {...}
            }
        """
        logger.info(f"📝 抓取博客: {url}")

        # 检测博客平台
        blog_platform = self._detect_blog_platform(url)
        logger.info(f"  检测到平台: {blog_platform}")

        # 使用 DocumentFetcher 抓取（已支持通用网页）
        if self.document_fetcher:
            result = await self.document_fetcher.fetch(url, raw=False)

            content = result.get("content", "")
            if max_length and len(content) > max_length:
                content = content[:max_length] + "\n\n[内容已截断...]"

            # 提取标题和作者（简单实现）
            title = result.get("title", self._extract_title(content, blog_platform))
            author = self._extract_author(content, blog_platform)

            return {
                "content": content,
                "title": title,
                "author": author,
                "metadata": {
                    "url": url,
                    "platform": blog_platform,
                    "source": "blog",
                    "max_length": max_length,
                },
            }
        else:
            raise NotImplementedError("DocumentFetcher 未配置")

    def _detect_blog_platform(self, url: str) -> str:
        """检测博客平台"""
        url_lower = url.lower()

        if "csdn.net" in url_lower:
            return "CSDN"
        elif "juejin.cn" in url_lower:
            return "掘金"
        elif "zhihu.com" in url_lower:
            return "知乎"
        elif "jianshu.com" in url_lower:
            return "简书"
        elif "medium.com" in url_lower:
            return "Medium"
        elif "cnblogs.com" in url_lower:
            return "博客园"
        elif "segmentfault.com" in url_lower:
            return "SegmentFault"
        else:
            return "通用博客"

    def _extract_title(self, content: str, platform: str) -> str:
        """从内容中提取标题（简单实现）"""
        lines = content.split("\n")
        for line in lines[:10]:  # 只检查前10行
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return "未知标题"

    def _extract_author(self, content: str, platform: str) -> str:
        """从内容中提取作者（简单实现）"""
        # TODO: 根据不同平台的HTML结构提取作者
        return "未知作者"
