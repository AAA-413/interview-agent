"""测试 document_fetcher"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.common.tools.document_fetcher import document_fetcher

async def test():
    url = "https://docs.python.org/zh-cn/3/library/asyncio.html"
    print(f"测试抓取: {url}\n")

    try:
        result = await document_fetcher.fetch(url, raw=False)
        print(f"成功: {result['success']}")
        print(f"标题: {result['title']}")
        print(f"内容长度: {len(result['content'])}")
        print(f"前200字符:\n{result['content'][:200]}")
    except Exception as e:
        print(f"错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
