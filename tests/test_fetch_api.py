import requests
import json

url = "http://localhost:8001/api/knowledgebase/fetch"
payload = {
    "url": "https://docs.python.org/zh-cn/3/library/asyncio.html",
    "name": "Python asyncio 文档",
    "description": "Python 异步编程官方文档",
    "max_length": 50000
}

print("发送请求...")
print(f"URL: {url}")
print(f"Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
print()

try:
    response = requests.post(url, json=payload, timeout=120)
    print(f"状态码: {response.status_code}")
    print(f"响应头: {dict(response.headers)}")
    print(f"响应内容: {response.text}")

    if response.status_code == 200:
        data = response.json()
        print(f"\n成功! 知识库 ID: {data.get('data', {}).get('id')}")
    else:
        print(f"\n失败: {response.text}")
except Exception as e:
    print(f"错误: {e}")
