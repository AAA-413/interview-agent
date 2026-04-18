import asyncio
import httpx

async def test_rag():
    url = "http://localhost:8001/api/knowledgebase/3/chat"
    payload = {
        "question": "什么是异步编程？",
        "stream": False,
        "top_k": 5
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload)
        print(f"状态码: {response.status_code}")
        print(f"响应内容:")
        result = response.json()

        if result.get("code") == 0:
            data = result.get("data", {})
            print(f"\n答案: {data.get('answer', 'N/A')}")
            print(f"\n检索到的文档片段数: {len(data.get('references', []))}")

            for i, ref in enumerate(data.get('references', []), 1):
                print(f"\n--- 片段 {i} ---")
                print(f"标题: {ref.get('title', 'N/A')}")
                print(f"相似度分数: {ref.get('score', 'N/A')}")
                print(f"内容预览: {ref.get('content_preview', 'N/A')[:100]}...")
        else:
            print(f"错误: {result.get('message')}")

if __name__ == "__main__":
    asyncio.run(test_rag())
