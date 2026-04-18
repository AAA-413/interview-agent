# LLM 流式调用卡住问题 — 分析与解决报告

> 文档日期：2026-04-17
> 影响模块：结构化输出（structured_output）、出题服务（question_service）、简历分析（resume_service）、JD 解析（skill_service）

---

## 一、问题发现

### 1.1 现象描述

在完成智能面试 Agent 平台 Phase 1-3 的开发后，进行端到端测试时发现：

- **创建面试会话**（`POST /api/interview/sessions`）：请求发出后无限挂起，无响应、无报错、无超时
- **简历分析**（`POST /api/resumes/{id}/analyze`）：同样无限挂起
- **JD 解析**（`POST /api/interview/skills/parse-jd`）：同样无限挂起
- **健康检查等非 LLM 接口**：正常响应

所有涉及 LLM 调用的接口全部卡住，而非 LLM 接口（如简历列表、技能列表）工作正常，初步判断问题出在 LLM 调用层。

### 1.2 影响范围

| 功能 | API 端点 | 状态 |
|------|---------|------|
| 创建面试会话 | `POST /api/interview/sessions` | ❌ 卡住 |
| 提交面试答案 | `POST /api/interview/sessions/{id}/answer` | ❌ 卡住 |
| 简历分析 | `POST /api/resumes/{id}/analyze` | ❌ 卡住 |
| JD 解析 | `POST /api/interview/skills/parse-jd` | ❌ 卡住 |
| 简历列表 | `GET /api/resumes` | ✅ 正常 |
| 技能列表 | `GET /api/interview/skills` | ✅ 正常 |
| 健康检查 | `GET /api/health` | ✅ 正常 |

---

## 二、排查思路

### 2.1 第一层：定位卡住位置

**方法**：在关键路径添加日志，逐步缩小范围。

```
请求入口 → 路由层 → 服务层 → LLM 调用层 → DashScope API
```

在 `structured_output.py` 的 `invoke()` 方法中添加日志后发现：

```python
# 卡住前的最后一条日志
logger.info("开始调用 LLM...")

# 以下代码永远不会执行到
async for chunk in chat_model.astream(messages):
    ...
```

**结论**：卡住位置在 `chat_model.astream()` 调用处。

### 2.2 第二层：验证 API 连通性

**方法**：绕过 LangChain，直接用 `httpx` 调用 DashScope API。

```python
import httpx, asyncio

async def test_direct():
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization": "Bearer sk-xxx"},
            json={"model": "qwen-plus", "messages": [{"role": "user", "content": "hello"}]},
        )
        print(resp.status_code, resp.text[:200])

asyncio.run(test_direct())
```

**结果**：直接调用 API 正常返回，说明 API Key、URL、网络都没有问题。

### 2.3 第三层：验证 LangChain 非流式调用

**方法**：用 `ainvoke()` 替代 `astream()` 测试。

```python
from langchain_openai import ChatOpenAI

chat = ChatOpenAI(base_url="...", api_key="...", model="qwen-plus")
response = await chat.ainvoke([("human", "hello")])
print(response.content)
```

**结果**：`ainvoke()` 正常返回！问题仅出现在 `astream()` 上。

### 2.4 第四层：分析 astream() 卡住的根因

**关键发现**：`astream()` 在以下条件下会卡住：

1. **Windows 操作系统**
2. **FastAPI 的 async 上下文中**
3. **astream() 跨越函数边界调用**

深入分析 LangChain 和 httpx 的源码后，发现调用链如下：

```
structured_output.invoke()
  → chat_model.astream(messages)     # 异步生成器
    → httpx.AsyncClient.stream()     # httpx 流式请求
      → httpcore.AsyncHTTPConnection # 底层连接
```

在 Windows 上，Python 的默认事件循环是 `ProactorEventLoop`。httpx 的流式响应依赖 `async for` 迭代，当异步生成器跨越函数边界时，事件循环的调度可能出现以下问题：

- **生成器挂起**：`astream()` 返回的异步生成器在 `async for` 迭代时，底层 httpx 连接的读取操作被事件循环挂起，无法恢复
- **事件循环死锁**：FastAPI 使用 `anyio` 作为异步运行时，与 httpx 的 `asyncio` 后端在某些边界情况下存在调度冲突
- **Windows 特有**：`ProactorEventLoop` 与 `SelectorEventLoop` 在 I/O 多路复用机制上存在差异，httpx 的流式读取在 `ProactorEventLoop` 下可能无法正确唤醒

### 2.5 第五层：验证 streaming=True 的影响

检查 `llm_provider.py` 中 `ChatOpenAI` 的初始化参数：

```python
# 原始代码
self._providers["dashscope"] = ChatOpenAI(
    ...
    streaming=True,  # ← 这个参数会影响底层行为
)
```

`streaming=True` 会让 `ChatOpenAI` 在调用 API 时使用 `stream=true` 参数，服务端返回 SSE（Server-Sent Events）格式的流式响应。即使使用 `ainvoke()`，底层仍然会以流式方式接收响应，然后在内存中拼接完整结果。

**问题**：`streaming=True` + `astream()` 的组合在 Windows + FastAPI 环境下会触发上述的异步调度问题。

---

## 三、解决方案

### 3.1 方案对比

| 方案 | 描述 | 优点 | 缺点 | 选择 |
|------|------|------|------|------|
| A | 修改事件循环策略为 `WindowsSelectorEventLoopPolicy` | 从根本上解决 httpx 兼容性 | 与 `asyncpg` 冲突，`asyncpg` 需要 `ProactorEventLoop` | ❌ |
| B | 使用 `anyio` 替代 `asyncio` 作为 httpx 后端 | 更好的跨平台兼容性 | 需要修改 LangChain 底层，改动过大 | ❌ |
| C | 使用 `ainvoke()` 替代 `astream()` | 改动最小，代码更简洁 | 丢失流式输出能力 | ✅ |
| D | 使用线程池隔离 `astream()` 调用 | 保留流式能力 | 增加复杂度，线程间通信开销 | ❌ |

### 3.2 最终方案：使用 ainvoke() 替代 astream()

**核心思路**：结构化输出场景需要完整响应才能解析 JSON，流式传输没有实际收益，因此使用非流式的 `ainvoke()` 是最合理的选择。

### 3.3 具体修改

#### 修改 1：`app/common/ai/structured_output.py`

```python
# ===== 修改前（会卡住）=====
async def invoke(self, chat_model, system_prompt, user_prompt, output_model, ...):
    ...
    for attempt in range(1, self.max_attempts + 1):
        try:
            messages = [("system", attempt_system), ("human", user_prompt)]
            # ❌ astream() 在 Windows + FastAPI 下会卡住
            chunks = []
            async for chunk in chat_model.astream(messages):
                if chunk.content:
                    chunks.append(chunk.content)
            content = "".join(chunks)
            return parser.parse(content)
        except Exception as e:
            ...

# ===== 修改后（正常工作）=====
async def invoke(self, chat_model, system_prompt, user_prompt, output_model, ...):
    ...
    for attempt in range(1, self.max_attempts + 1):
        try:
            messages = [("system", attempt_system), ("human", user_prompt)]
            # ✅ ainvoke() 一次性返回完整响应，无流式调度问题
            response = await chat_model.ainvoke(messages)
            content = response.content if response.content else ""
            return parser.parse(content)
        except Exception as e:
            ...
```

#### 修改 2：`app/common/ai/llm_provider.py`

```python
# ===== 修改前 =====
self._providers["dashscope"] = ChatOpenAI(
    base_url=ai.base_url,
    api_key=ai.bailian_api_key,
    model=ai.model,
    temperature=ai.temperature,
    max_tokens=4096,
    streaming=True,           # ❌ 强制流式模式
    request_timeout=180,
)

# ===== 修改后 =====
self._providers["dashscope"] = ChatOpenAI(
    base_url=ai.base_url,
    api_key=ai.bailian_api_key,
    model=ai.model,
    temperature=ai.temperature,
    max_tokens=4096,
    request_timeout=180,      # ✅ 移除 streaming=True，默认非流式
)
```

#### 修改 3：`app/modules/interview/skill_service.py`

```python
# ===== 修改前 =====
def parse_jd(self, jd_text: str) -> list[CategoryDTO]:
    ...
    # ❌ 在 async 上下文中使用 run_until_complete() 会报错
    dto = asyncio.get_event_loop().run_until_complete(
        structured_output_invoker.invoke(...)
    )

# ===== 修改后 =====
async def parse_jd(self, jd_text: str) -> list[CategoryDTO]:
    ...
    # ✅ 直接 await，不再需要 run_until_complete()
    dto = await structured_output_invoker.invoke(...)
```

同时需要更新调用方，将 `skill_service.parse_jd()` 的调用改为 `await skill_service.parse_jd()`。

---

## 四、验证结果

### 4.1 功能验证

| 功能 | 测试方法 | 结果 |
|------|---------|------|
| 结构化输出 | `structured_output_invoker.invoke()` | ✅ 正常返回 |
| 出题服务 | `POST /api/interview/sessions` | ✅ 生成 3-6 道面试题 |
| 简历分析 | `POST /api/resumes/{id}/analyze` | ✅ 生成评分和建议 |
| JD 解析 | `POST /api/interview/skills/parse-jd` | ✅ 提取面试方向 |

### 4.2 前后端联调验证

| 测试项 | API 路径 | 结果 |
|--------|---------|------|
| 健康检查 | `GET /api/health` | ✅ `{status: "UP"}` |
| 简历列表 | `GET /api/resumes` | ✅ 返回数据 |
| 简历详情 | `GET /api/resumes/{id}` | ✅ 返回详情 |
| 技能列表 | `GET /api/interview/skills` | ✅ 返回 10 个方向 |
| 面试会话列表 | `GET /api/interview/sessions` | ✅ 返回记录 |
| 面试会话详情 | `GET /api/interview/sessions/{id}` | ✅ 含题目数据 |

---

## 五、根因总结

```
                    ┌─────────────────────────────┐
                    │     Windows ProactorEventLoop │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  FastAPI (anyio async runtime)│
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  LangChain astream()         │
                    │  (async generator)           │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  httpx AsyncClient.stream()  │
                    │  (SSE 流式读取)              │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  ❌ 事件循环调度死锁          │
                    │  异步生成器无法恢复执行        │
                    └─────────────────────────────┘
```

**根因链条**：

1. **操作系统层**：Windows 使用 `ProactorEventLoop`，I/O 完成端口的回调机制与 `SelectorEventLoop` 不同
2. **运行时层**：FastAPI 使用 `anyio` 管理异步任务，与 `asyncio` 原生调度存在交互边界
3. **库层**：LangChain 的 `astream()` 返回异步生成器，跨越函数边界时上下文切换
4. **传输层**：httpx 的流式 SSE 读取依赖事件循环的及时唤醒，在上述条件下无法正确恢复

**为什么 `ainvoke()` 有效**：

- `ainvoke()` 内部虽然也可能使用流式传输，但它将整个流式读取封装在单个 `await` 中
- 不暴露异步生成器给调用方，避免了跨函数边界的上下文切换问题
- 事件循环只需处理一个完整的 `await`，不需要在多次 `async for` 迭代间切换

---

## 六、经验教训

### 6.1 在 Windows 上开发异步 Python 应用的注意事项

1. **避免跨函数边界的异步生成器**：在 Windows + FastAPI 环境下，`async for` 迭代外部异步生成器可能导致死锁
2. **优先使用 `ainvoke()` 而非 `astream()`**：除非需要真正的流式输出（如打字机效果），否则非流式调用更稳定
3. **注意事件循环策略**：`asyncpg` 需要 `ProactorEventLoop`，而 `httpx` 流式调用在 `SelectorEventLoop` 下更稳定，两者存在冲突

### 6.2 结构化输出不需要流式

- 结构化输出（JSON 解析）需要完整响应才能解析，流式传输的增量数据无法用于解析
- 流式传输在此场景下只有缺点（复杂度高、兼容性差），没有优点
- `ainvoke()` 是结构化输出的最佳选择

### 6.3 async 函数不要用 run_until_complete()

- 在 FastAPI 的 async 上下文中，事件循环已经在运行
- 调用 `asyncio.get_event_loop().run_until_complete()` 会抛出 "This event loop is already running" 错误
- 正确做法是将函数声明为 `async def`，直接使用 `await`

---

## 七、相关文件索引

| 文件 | 修改内容 |
|------|---------|
| [structured_output.py](file:///d:/work/xiaofuge/111/python/app/common/ai/structured_output.py) | `astream()` → `ainvoke()` |
| [llm_provider.py](file:///d:/work/xiaofuge/111/python/app/common/ai/llm_provider.py) | 移除 `streaming=True` |
| [skill_service.py](file:///d:/work/xiaofuge/111/python/app/modules/interview/skill_service.py) | `parse_jd()` 改为 `async def`，移除 `run_until_complete()` |
