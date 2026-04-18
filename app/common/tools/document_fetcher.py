"""
文档抓取工具 - 从 URL 抓取内容并转换为 Markdown
"""
import httpx
from readabilipy import simple_json_from_html_string
from markdownify import markdownify as md
from typing import Optional
import logging

from app.common.exception import BusinessException
from app.common.error_code import ErrorCode

logger = logging.getLogger(__name__)


class DocumentFetcher:
    """文档抓取器"""

    def __init__(self, timeout: int = 30, max_length: Optional[int] = None):
        self.timeout = timeout
        self.max_length = max_length

    async def fetch(self, url: str, raw: bool = False) -> dict:
        """
        抓取 URL 内容并转换为 Markdown

        Args:
            url: 目标 URL
            raw: 是否返回原始 HTML（不转换为 Markdown）

        Returns:
            {
                "url": str,
                "title": str,
                "content": str,  # Markdown 或 HTML
                "success": bool,
                "error": Optional[str]
            }

        Raises:
            BusinessException: 抓取失败时抛出
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()

                html_content = response.text

                # 使用 readabilipy 提取主要内容
                article = simple_json_from_html_string(html_content, use_readability=True)

                if not article or not article.get("content"):
                    raise BusinessException(
                        ErrorCode.KNOWLEDGE_BASE_FETCH_FAILED,
                        "无法提取页面内容，请检查 URL 是否为有效的文档页面"
                    )

                title = article.get("title", "")
                content_html = article.get("content", "")

                # 转换为 Markdown
                if raw:
                    content = content_html
                else:
                    content = md(content_html, heading_style="ATX", bullets="-")

                # 限制长度
                if self.max_length and len(content) > self.max_length:
                    content = content[:self.max_length] + "\n\n[内容已截断...]"

                logger.info(f"成功抓取文档: {url}, 标题: {title}, 长度: {len(content)}")

                return {
                    "url": url,
                    "title": title,
                    "content": content,
                    "success": True,
                    "error": None
                }

        except httpx.HTTPStatusError as e:
            error_msg = f"无法访问该页面（HTTP {e.response.status_code}），请检查 URL 是否正确"
            logger.error(f"HTTP 错误: {e.response.status_code} - {url}")
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_FETCH_FAILED, error_msg)
        except httpx.TimeoutException:
            error_msg = f"页面加载超时（{self.timeout}秒），请稍后重试或检查网络连接"
            logger.error(f"请求超时 - URL: {url}")
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_FETCH_FAILED, error_msg)
        except BusinessException:
            raise  # 直接抛出业务异常
        except Exception as e:
            error_msg = f"文档抓取失败: {str(e)}"
            logger.error(f"{error_msg} - URL: {url}")
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_FETCH_FAILED, error_msg)


# 全局实例
document_fetcher = DocumentFetcher(timeout=30, max_length=50000)
