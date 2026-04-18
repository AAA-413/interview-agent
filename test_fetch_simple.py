"""测试简单的 HTTP 请求"""
import asyncio
import httpx

async def test_fetch():
    # 测试简单的 URL
    test_urls = [
        "https://www.baidu.com",
        "https://docs.python.org/zh-cn/3/library/asyncio.html",
        "http://httpbin.org/html"
    ]

    for url in test_urls:
        print(f"\n测试 URL: {url}")
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(url)
                print(f"状态码: {response.status_code}")
                print(f"内容长度: {len(response.text)}")
                print(f"前100字符: {response.text[:100]}")
        except Exception as e:
            print(f"错误: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_fetch())
