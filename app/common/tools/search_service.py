"""
搜索引擎服务 - 封装多个搜索引擎API
"""
import logging
import httpx
from typing import Any, Dict, List, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


class SearchService:
    """搜索引擎服务"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._setup_proxy()

    def _setup_proxy(self):
        """配置HTTP代理"""
        import os

        self.proxy = None
        http_proxy = os.getenv("HTTP_PROXY")
        https_proxy = os.getenv("HTTPS_PROXY")

        if https_proxy or http_proxy:
            self.proxy = https_proxy or http_proxy
            logger.info(f"🌐 已配置HTTP代理: {self.proxy}")

    async def search(
        self,
        query: str,
        num_results: int = 5,
        engine: str = "duckduckgo",
    ) -> Dict[str, Any]:
        """
        搜索网页

        Args:
            query: 搜索关键词
            num_results: 结果数量
            engine: 搜索引擎（duckduckgo, bing, google, serper, tavily）

        Returns:
            搜索结果，包含：
            - content: 搜索结果摘要（合并）
            - results: 结果列表
            - metadata: 元数据
        """
        import os

        # 从环境变量读取默认搜索引擎
        engine = os.getenv("SEARCH_ENGINE", engine)
        logger.info(f"🔍 搜索: {query} (引擎: {engine})")

        if engine == "duckduckgo":
            return await self._search_duckduckgo(query, num_results)
        elif engine == "bing":
            return await self._search_bing(query, num_results)
        elif engine == "google":
            return await self._search_google(query, num_results)
        elif engine == "serper":
            return await self._search_serper(query, num_results)
        elif engine == "tavily":
            return await self._search_tavily(query, num_results)
        else:
            raise ValueError(f"不支持的搜索引擎: {engine}")

    async def _search_duckduckgo(
        self, query: str, num_results: int
    ) -> Dict[str, Any]:
        """
        使用DuckDuckGo搜索（免费，无需API key）

        使用DuckDuckGo的HTML搜索接口
        """
        try:
            # 使用DuckDuckGo HTML搜索
            url = "https://html.duckduckgo.com/html/"
            params = {
                "q": query,
            }

            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, proxy=self.proxy) as client:
                response = await client.post(url, data=params)
                response.raise_for_status()

                # 解析HTML结果
                results = self._parse_duckduckgo_html(response.text, num_results)

                # 合并搜索结果内容
                content_parts = []
                for i, result in enumerate(results, 1):
                    content_parts.append(
                        f"## 结果 {i}: {result['title']}\n\n"
                        f"{result['snippet']}\n\n"
                        f"来源: {result['url']}"
                    )

                content = "\n\n---\n\n".join(content_parts)

                logger.info(f"  找到 {len(results)} 个结果")

                return {
                    "content": content,
                    "results": results,
                    "metadata": {
                        "query": query,
                        "num_results": len(results),
                        "source": "duckduckgo",
                        "is_mock": False,
                    },
                }

        except Exception as e:
            logger.error(f"DuckDuckGo搜索失败: {e}")
            # 降级到模拟搜索
            return await self._mock_search(query, num_results)

    def _parse_duckduckgo_html(self, html: str, num_results: int) -> List[Dict[str, Any]]:
        """解析DuckDuckGo HTML结果"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        results = []

        # 查找搜索结果
        result_divs = soup.find_all("div", class_="result")

        for div in result_divs[:num_results]:
            try:
                # 提取标题和链接
                title_tag = div.find("a", class_="result__a")
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")

                # 提取摘要
                snippet_tag = div.find("a", class_="result__snippet")
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                if title and url:
                    results.append({
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                    })

            except Exception as e:
                logger.warning(f"解析搜索结果失败: {e}")
                continue

        return results

    async def _search_bing(self, query: str, num_results: int) -> Dict[str, Any]:
        """
        使用Bing搜索（需要API key）

        需要在环境变量中设置 BING_SEARCH_API_KEY
        """
        import os

        api_key = os.getenv("BING_SEARCH_API_KEY")
        if not api_key:
            logger.warning("未配置 BING_SEARCH_API_KEY，降级到模拟搜索")
            return await self._mock_search(query, num_results)

        try:
            url = "https://api.bing.microsoft.com/v7.0/search"
            headers = {
                "Ocp-Apim-Subscription-Key": api_key,
            }
            params = {
                "q": query,
                "count": num_results,
            }

            async with httpx.AsyncClient(timeout=self.timeout, proxy=self.proxy) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("webPages", {}).get("value", []):
                    results.append({
                        "title": item.get("name", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", ""),
                    })

                # 合并搜索结果内容
                content_parts = []
                for i, result in enumerate(results, 1):
                    content_parts.append(
                        f"## 结果 {i}: {result['title']}\n\n"
                        f"{result['snippet']}\n\n"
                        f"来源: {result['url']}"
                    )

                content = "\n\n---\n\n".join(content_parts)

                return {
                    "content": content,
                    "results": results,
                    "metadata": {
                        "query": query,
                        "num_results": len(results),
                        "source": "bing",
                        "is_mock": False,
                    },
                }

        except Exception as e:
            logger.error(f"Bing搜索失败: {e}")
            return await self._mock_search(query, num_results)

    async def _search_google(self, query: str, num_results: int) -> Dict[str, Any]:
        """
        使用Google搜索（需要API key）

        需要在环境变量中设置 GOOGLE_SEARCH_API_KEY 和 GOOGLE_SEARCH_ENGINE_ID
        """
        import os

        api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID")

        if not api_key or not engine_id:
            logger.warning("未配置 Google 搜索API，降级到模拟搜索")
            return await self._mock_search(query, num_results)

        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": api_key,
                "cx": engine_id,
                "q": query,
                "num": num_results,
            }

            async with httpx.AsyncClient(timeout=self.timeout, proxy=self.proxy) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("items", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                # 合并搜索结果内容
                content_parts = []
                for i, result in enumerate(results, 1):
                    content_parts.append(
                        f"## 结果 {i}: {result['title']}\n\n"
                        f"{result['snippet']}\n\n"
                        f"来源: {result['url']}"
                    )

                content = "\n\n---\n\n".join(content_parts)

                return {
                    "content": content,
                    "results": results,
                    "metadata": {
                        "query": query,
                        "num_results": len(results),
                        "source": "google",
                        "is_mock": False,
                    },
                }

        except Exception as e:
            logger.error(f"Google搜索失败: {e}")
            return await self._mock_search(query, num_results)

    async def _search_serper(self, query: str, num_results: int) -> Dict[str, Any]:
        """
        使用Serper.dev搜索（需要API key，有免费额度）

        需要在环境变量中设置 SERPER_API_KEY
        免费额度：2500次/月
        注册地址：https://serper.dev
        """
        import os

        api_key = os.getenv("SERPER_API_KEY")
        if not api_key:
            logger.warning("未配置 SERPER_API_KEY，降级到模拟搜索")
            return await self._mock_search(query, num_results)

        try:
            url = "https://google.serper.dev/search"
            headers = {
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "q": query,
                "num": num_results,
            }

            async with httpx.AsyncClient(timeout=self.timeout, proxy=self.proxy) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("organic", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                # 合并搜索结果内容
                content_parts = []
                for i, result in enumerate(results, 1):
                    content_parts.append(
                        f"## 结果 {i}: {result['title']}\n\n"
                        f"{result['snippet']}\n\n"
                        f"来源: {result['url']}"
                    )

                content = "\n\n---\n\n".join(content_parts)

                logger.info(f"  找到 {len(results)} 个结果")

                return {
                    "content": content,
                    "results": results,
                    "metadata": {
                        "query": query,
                        "num_results": len(results),
                        "source": "serper",
                        "is_mock": False,
                    },
                }

        except Exception as e:
            logger.error(f"Serper搜索失败: {e}")
            return await self._mock_search(query, num_results)

    async def _search_tavily(self, query: str, num_results: int) -> Dict[str, Any]:
        """
        使用Tavily搜索（专为AI应用设计，有免费额度）

        需要在环境变量中设置 TAVILY_API_KEY
        免费额度：1000次/月
        注册地址：https://tavily.com
        """
        import os

        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            logger.warning("未配置 TAVILY_API_KEY，降级到模拟搜索")
            return await self._mock_search(query, num_results)

        try:
            url = "https://api.tavily.com/search"
            headers = {
                "Content-Type": "application/json",
            }
            payload = {
                "api_key": api_key,
                "query": query,
                "max_results": num_results,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": False,
            }

            async with httpx.AsyncClient(timeout=self.timeout, proxy=self.proxy) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", ""),
                    })

                # 合并搜索结果内容
                content_parts = []
                for i, result in enumerate(results, 1):
                    content_parts.append(
                        f"## 结果 {i}: {result['title']}\n\n"
                        f"{result['snippet']}\n\n"
                        f"来源: {result['url']}"
                    )

                content = "\n\n---\n\n".join(content_parts)

                logger.info(f"  找到 {len(results)} 个结果")

                return {
                    "content": content,
                    "results": results,
                    "metadata": {
                        "query": query,
                        "num_results": len(results),
                        "source": "tavily",
                        "is_mock": False,
                    },
                }

        except Exception as e:
            logger.error(f"Tavily搜索失败: {e}")
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
            content_parts.append(
                f"## 结果 {i}: {result['title']}\n\n"
                f"{result['snippet']}\n\n"
                f"来源: {result['url']}"
            )

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


# 全局实例
search_service = SearchService()
