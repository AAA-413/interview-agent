import requests
import json

url = "http://localhost:8001/api/knowledgebase/fetch"
payload = {
    "url": "http://httpbin.org/html",
    "name": "测试文档",
    "description": "简单的测试页面",
    "max_length": 50000
}

print("测试 URL 抓取 API...")
print(f"目标 URL: {payload['url']}\n")

try:
    response = requests.post(url, json=payload, timeout=60)
    print(f"状态码: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        if data.get('code') == 0:
            kb = data['data']
            print(f"✓ 成功创建知识库!")
            print(f"  ID: {kb['id']}")
            print(f"  名称: {kb['name']}")
            print(f"  文件大小: {kb['file_size']} 字节")
            print(f"  索引状态: {kb['index_status']}")
        else:
            print(f"✗ 业务错误: {data.get('message')}")
    else:
        print(f"✗ HTTP 错误: {response.text}")
except Exception as e:
    print(f"✗ 异常: {e}")
