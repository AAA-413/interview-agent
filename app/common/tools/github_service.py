"""
GitHub API 服务 - 封装GitHub API调用
"""

import base64
import itertools
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class GitHubService:
    """GitHub API服务（支持 token 池轮换）"""

    def __init__(self, tokens: Optional[List[str]] = None):
        """
        初始化GitHub服务

        Args:
            tokens: GitHub Personal Access Token 列表（轮换使用，提高 API 限额）
        """
        self.tokens = tokens or []
        self._token_cycle = itertools.cycle(self.tokens) if self.tokens else None
        self.base_url = "https://api.github.com"
        self.timeout = 30

    async def search_repositories(
        self,
        query: str,
        language: str = "",
        sort: str = "stars",
        per_page: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        搜索GitHub仓库

        Args:
            query: 搜索关键词
            language: 编程语言筛选（可选）
            sort: 排序方式（stars, forks, updated）
            per_page: 每页结果数量

        Returns:
            仓库列表，每个包含：
            - name: 仓库名
            - full_name: 完整名称（owner/repo）
            - description: 描述
            - stars: star数
            - url: 仓库URL
            - language: 主要语言
        """
        logger.info(f"🔍 搜索GitHub仓库: {query}")

        # 构建搜索查询
        search_query = query
        if language:
            search_query += f" language:{language}"

        # 调用GitHub API
        url = f"{self.base_url}/search/repositories"
        params = {
            "q": search_query,
            "sort": sort,
            "per_page": per_page,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params, headers=self._get_headers())
                response.raise_for_status()
                data = response.json()

                repos = []
                for item in data.get("items", []):
                    repos.append(
                        {
                            "name": item["name"],
                            "full_name": item["full_name"],
                            "description": item.get("description", ""),
                            "stars": item["stargazers_count"],
                            "url": item["html_url"],
                            "language": item.get("language", ""),
                            "updated_at": item["updated_at"],
                        }
                    )

                logger.info(f"  找到 {len(repos)} 个仓库")
                return repos

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.error("GitHub API 限额已用完，请提供 Personal Access Token")
            logger.error(f"GitHub API 错误: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"搜索GitHub仓库失败: {e}")
            return []

    async def get_readme(self, repo: str) -> Optional[Dict[str, Any]]:
        """
        获取仓库的README

        Args:
            repo: 仓库名称（格式：owner/repo）

        Returns:
            README内容，包含：
            - path: 文件路径
            - content: 文件内容（Markdown）
        """
        logger.info(f"📄 获取README: {repo}")

        url = f"{self.base_url}/repos/{repo}/readme"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())
                response.raise_for_status()
                data = response.json()

                # 解码Base64内容
                content = base64.b64decode(data["content"]).decode("utf-8")

                return {
                    "path": data["name"],
                    "content": content,
                }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"  README不存在: {repo}")
            else:
                logger.error(f"获取README失败: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"获取README失败: {e}")
            return None

    async def list_docs_files(
        self, repo: str, path: str = "docs", max_depth: int = 3, file_extensions: Optional[List[str]] = None
    ) -> List[str]:
        """
        列出文档文件（递归）

        Args:
            repo: 仓库名称（格式：owner/repo）
            path: 文档目录路径
            max_depth: 最大递归深度
            file_extensions: 文件扩展名列表，默认 [".md"]

        Returns:
            文档文件路径列表
        """
        if file_extensions is None:
            file_extensions = [".md"]

        logger.info(f"📂 列出文档文件: {repo}/{path}")

        if max_depth <= 0:
            return []

        url = f"{self.base_url}/repos/{repo}/contents/{path}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())

                if response.status_code == 404:
                    logger.info(f"  目录不存在: {path}")
                    return []

                response.raise_for_status()
                data = response.json()

                files = []
                for item in data:
                    if item["type"] == "file" and any(item["name"].endswith(ext) for ext in file_extensions):
                        files.append(item["path"])
                    elif item["type"] == "dir":
                        # 递归获取子目录
                        sub_files = await self.list_docs_files(repo, item["path"], max_depth - 1, file_extensions)
                        files.extend(sub_files)

                logger.info(f"  找到 {len(files)} 个文档文件")
                return files

        except Exception as e:
            logger.error(f"列出文档文件失败: {e}")
            return []

    async def get_file_content(self, repo: str, file_path: str) -> Optional[str]:
        """
        获取文件内容

        Args:
            repo: 仓库名称（格式：owner/repo）
            file_path: 文件路径

        Returns:
            文件内容（文本）
        """
        logger.info(f"📄 获取文件: {repo}/{file_path}")

        url = f"{self.base_url}/repos/{repo}/contents/{file_path}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())
                response.raise_for_status()
                data = response.json()

                # 解码Base64内容
                content = base64.b64decode(data["content"]).decode("utf-8")

                return content

        except httpx.HTTPStatusError as e:
            logger.error(f"获取文件失败: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"获取文件失败: {e}")
            return None

    async def fetch_repo_docs(self, repo: str, include_readme: bool = True, max_files: int = 30) -> Dict[str, Any]:
        """
        抓取仓库的所有文档（含项目结构和关键配置文件）

        Args:
            repo: 仓库名称（格式：owner/repo）
            include_readme: 是否包含README
            max_files: 最大文件数量

        Returns:
            文档集合，包含：
            - repo: 仓库名称
            - documents: 文档列表
            - total_docs: 文档总数
        """
        logger.info(f"📦 抓取仓库文档: {repo}")

        documents = []

        # 1. 抓取项目结构（目录树）
        tree = await self._get_repo_tree(repo, path="", max_depth=2)
        if tree:
            documents.append(
                {
                    "path": "PROJECT_STRUCTURE",
                    "content": f"# {repo} 项目结构\n\n```\n{tree}\n```",
                    "type": "structure",
                }
            )

        # 2. 抓取关键配置/入口文件
        key_files = [
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "requirements.txt",
            "package.json",
            "Makefile",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            ".env.example",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "CHANGELOG.rst",
            "Cargo.toml",
            "go.mod",
        ]
        for filename in key_files:
            if len(documents) >= max_files:
                break
            content = await self.get_file_content(repo, filename)
            if content:
                documents.append(
                    {
                        "path": filename,
                        "content": content,
                        "type": "config",
                    }
                )

        # 3. 抓取README
        if include_readme and len(documents) < max_files:
            readme = await self.get_readme(repo)
            if readme:
                documents.append(
                    {
                        "path": readme["path"],
                        "content": readme["content"],
                        "type": "readme",
                    }
                )

        # 4. 检查文档目录（扩展列表 + 支持更多文件类型）
        doc_dirs = ["docs", "documentation", "doc", "wiki", "examples", "notebooks", "tutorials", "guides"]
        docs_files = []
        for doc_dir in doc_dirs:
            other_files = await self.list_docs_files(repo, doc_dir)
            docs_files.extend(other_files)

        # 也搜索 .rst 和 .txt 文档（仅在 docs 目录下）
        for doc_dir in ["docs", "documentation", "doc"]:
            rst_files = await self.list_docs_files(repo, doc_dir, file_extensions=[".rst", ".txt"])
            docs_files.extend(rst_files)

        # 去重
        docs_files = list(set(docs_files))

        # 5. 抓取文档内容（限制数量）
        for file_path in docs_files[: max_files - len(documents)]:
            content = await self.get_file_content(repo, file_path)
            if content:
                documents.append(
                    {
                        "path": file_path,
                        "content": content,
                        "type": "doc",
                    }
                )

        logger.info(f"  共抓取 {len(documents)} 个文档")

        return {
            "repo": repo,
            "documents": documents,
            "total_docs": len(documents),
        }

    async def _get_repo_tree(self, repo: str, path: str = "", max_depth: int = 2, current_depth: int = 0) -> str:
        """
        获取仓库目录树（树形文本）

        Args:
            repo: 仓库名称
            path: 当前路径
            max_depth: 最大递归深度
            current_depth: 当前深度

        Returns:
            树形文本
        """
        if current_depth >= max_depth:
            return ""

        url = f"{self.base_url}/repos/{repo}/contents/{path}" if path else f"{self.base_url}/repos/{repo}/contents"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())
                if response.status_code != 200:
                    return ""
                data = response.json()

                if not isinstance(data, list):
                    return ""

                lines = []
                # 排序：目录在前，文件在后
                sorted_items = sorted(data, key=lambda x: (x["type"] != "dir", x["name"].lower()))

                for item in sorted_items:
                    name = item["name"]
                    # 跳过隐藏文件和常见的大目录
                    if name.startswith(".") or name in (
                        "node_modules",
                        "__pycache__",
                        ".git",
                        "venv",
                        ".venv",
                        "dist",
                        "build",
                    ):
                        continue

                    indent = "│   " * current_depth
                    if item["type"] == "dir":
                        lines.append(f"{indent}├── {name}/")
                        # 递归获取子目录
                        sub_tree = await self._get_repo_tree(repo, item["path"], max_depth, current_depth + 1)
                        if sub_tree:
                            lines.append(sub_tree)
                    else:
                        lines.append(f"{indent}├── {name}")

                return "\n".join(lines)

        except Exception as e:
            logger.error(f"获取目录树失败: {e}")
            return ""

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头（轮换 token）"""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Interview-Platform",
        }
        if self._token_cycle:
            token = next(self._token_cycle)
            headers["Authorization"] = f"token {token}"
        return headers


# 全局实例（从配置加载 token 池）
def _create_github_service() -> GitHubService:
    from app.config import settings

    tokens = settings.github.token_list
    if tokens:
        logger.info("GitHub token 池已加载: %d 个 token", len(tokens))
    else:
        logger.info("GitHub 未配置 token，使用未认证模式（60 次/小时限额）")
    return GitHubService(tokens=tokens)


github_service = _create_github_service()
