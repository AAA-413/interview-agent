# Phase 4（知识库管理模块）联调问题记录

> 文档日期：2026-04-17
> 适用范围：知识库上传、异步索引、RAG 问答、测试与本地联调

---

## 一、这次实现的目标

本轮工作目标是把 Phase 4 从“路由占位”推进到“具备可运行骨架”的状态，核心包括：

1. 补齐知识库 ORM、DTO、持久化服务
2. 完成文档上传 -> 异步索引 -> 状态推进闭环
3. 完成 RAG 非流式问答与 SSE 流式输出
4. 补最小化后端测试样例
5. 更新计划、进度与 README

---

## 二、实现过程中遇到的问题

### 2.1 临时验证脚本直接把 `db=None` 传给 RAG 服务

#### 现象

执行 `tmp_verify_kb_rag.py` 时，报错：

```text
AttributeError: 'NoneType' object has no attribute 'flush'
```

#### 根因

`KnowledgeBaseRagService.ask()` 在正常 API 调用路径下依赖 `AsyncSession`，内部会在完成问答后调用 `db.flush()`。

但临时验证脚本为了快速 mock 持久化层，直接传入了 `db=None`，导致在完成 chat 状态更新后调用 `flush()` 时出错。

#### 修复方式

把临时脚本里的 `db` 改成一个带异步 `flush()` 方法的 fake 对象：

```python
fake_db = SimpleNamespace(flush=_noop)
```

#### 经验

- 对 service 层做脱离数据库的临时验证时，不能只 mock repository，也要补齐 service 直接依赖的 session 能力。
- 这种错误不是业务实现 bug，而是测试桩不完整。

---

### 2.2 当前虚拟环境中缺少 `pytest`（已解决）

#### 现象

最初尝试执行：

```bash
.venv\Scripts\python.exe -m pytest -q
```

返回：

```text
No module named pytest
```

随后尝试执行：

```bash
.venv\Scripts\python.exe -m pip install -e .[dev]
```

又报 editable 安装失败，提示 Hatch 无法自动判断 wheel 应该打包哪些目录。

#### 根因

- `pyproject.toml` 已声明 `dev` 依赖包含 `pytest`，但当前 `.venv` 还没有安装开发依赖
- 项目使用 `hatchling` 构建，但 `pyproject.toml` 缺少 `tool.hatch.build.targets.wheel.packages`，导致 editable 安装阶段失败

#### 修复方式

1. 在 `pyproject.toml` 中补充：

```toml
[tool.hatch.build.targets.wheel]
packages = ["app"]
```

2. 然后执行：

```bash
.venv\Scripts\python.exe -m pip install -e .[dev]
```

3. 验证安装结果：

```bash
.venv\Scripts\python.exe -m pytest --version
```

返回：

```text
pytest 9.0.3
```

4. 正式执行知识库测试：

```bash
.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q
```

最终结果：

```text
4 passed
```

#### 经验

- `pyproject.toml` 里“声明了 dev 依赖”不等于本地虚拟环境里“已经可用”
- 如果项目采用 Hatch editable 安装，必须确保 wheel 打包目录可被明确识别
- 测试环境问题应尽早解决，否则“测试文件已写好”也无法真正形成回归保障

---

### 2.3 现有 async 测试在 pytest 下直接失败（已解决）

#### 现象

安装完 pytest 后执行：

```bash
.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q
```

返回 3 个失败，核心报错为：

```text
async def functions are not natively supported.
```

#### 根因

`pytest-asyncio` 虽然已经安装，但 `tests/test_knowledge_base_services.py` 里的 3 个异步测试函数没有声明 `@pytest.mark.asyncio`，pytest 不会自动把它们放进 asyncio 事件循环里执行。

#### 修复方式

给以下测试补上 `@pytest.mark.asyncio`：

- `test_vector_service_split_text_creates_chunks`
- `test_rag_service_returns_ranked_references`
- `test_index_task_handler_marks_failed_when_source_text_empty`

保留原有同步包装测试 `test_async_knowledge_base_suite()`，这样既兼容原先的手动 `asyncio.run(...)` 验证方式，也支持标准 pytest 执行。

#### 结果

再次执行：

```bash
.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q
```

返回：

```text
4 passed
```

#### 经验

- “安装了 pytest-asyncio” 只是前提，异步用例还需要按 pytest 规范声明运行方式
- 对 async 项目来说，尽量让测试既能被 pytest 直接收集，也能在必要时单独脚本化验证

---

### 2.4 Windows 控制台输出中文出现乱码

#### 现象

运行 `tmp_verify_kb_rag.py` 时，脚本逻辑能跑通，但终端打印中文出现乱码。

#### 根因

不是 RAG 服务返回错误，而是当前 Windows 终端编码和脚本输出编码不一致。

#### 处理方式

本轮没有改业务代码，因为问题只影响临时脚本展示，不影响 API 返回。若后续要改善本地脚本体验，可在 PowerShell / cmd 中切换 UTF-8 编码，或把验证结果写入文件再查看。

#### 经验

- 先区分“输出乱码”和“业务逻辑错误”。
- 对 API 项目来说，更应该看 HTTP 响应或结构化对象，而不是只看终端展示文本。

---

## 三、本轮已完成的后端骨架

### 3.1 数据模型

新增：

- `KnowledgeBaseEntity`
- `KnowledgeChunkEntity`
- `RagChatEntity`

支持：

- 文件元信息
- 原始文本
- 索引状态（`PENDING / PROCESSING / COMPLETED / FAILED`）
- chunk 数量统计
- 问答历史

### 3.2 异步索引链路

新增：

- `KnowledgeBaseIndexStreamProducer`
- `KnowledgeBaseIndexTaskHandler`
- `knowledge_base:index:stream`

并在 `app/main.py` 生命周期里注册知识库 worker。

### 3.3 RAG 服务

新增：

- 非流式问答接口：`POST /api/knowledgebase/{kb_id}/chat`
- SSE 流式接口：`POST /api/knowledgebase/{kb_id}/chat/stream`
- 历史问答接口：`GET /api/knowledgebase/{kb_id}/chats`

### 3.4 测试与临时验证

新增：

- `tests/test_knowledge_base_services.py`
- `tmp_verify_kb_rag.py`

---

## 四、后续建议

1. 在已打通 `pytest` 环境的基础上，继续补 API 级测试（上传、详情、重建索引、删除、问答）
2. 前端已补齐列表页、详情页、上传页与问答面板，并完成基础类型检查
3. 完成真实前后端联调后，再把 README 中“知识库管理模块”从介绍性描述更新为具体使用说明
4. 如果后续引入 pgvector 真正落库，再把当前 `embedding_json` 过渡为向量列

---

## 五、本轮新增前端联调实现记录

### 5.1 补齐知识库前端页面与导航

#### 实现内容

新增前端文件：

- `frontend/src/types/knowledgeBase.ts`
- `frontend/src/api/knowledgeBase.ts`
- `frontend/src/pages/KnowledgeBaseListPage.tsx`
- `frontend/src/pages/KnowledgeBaseUploadPage.tsx`
- `frontend/src/pages/KnowledgeBaseDetailPage.tsx`

并修改：

- `frontend/src/App.tsx`
- `frontend/src/components/Layout.tsx`

#### 结果

前端已支持：

- 知识库列表查看
- 文档上传创建知识库
- 详情页查看索引状态、片段预览、最近问答
- 普通问答
- SSE 流式问答
- 索引处理中自动轮询

### 5.2 SSE 流式返回在前端需要手动解析事件块

#### 现象

后端流式接口使用 `text/event-stream`，但前端项目当前并不是 GET + EventSource 模式，而是 `POST` 请求携带问答参数。

#### 根因

浏览器原生 `EventSource` 不支持带请求体的 POST；而当前接口定义为 `POST /api/knowledgebase/{kb_id}/chat/stream`。

#### 处理方式

在 `frontend/src/api/knowledgeBase.ts` 中改为使用 `fetch()` + `ReadableStreamDefaultReader` 手动读取响应流，并按 SSE 事件块解析：

- `meta`
- `chunk`
- `references`
- `done`

#### 经验

- 如果后端坚持使用 POST + SSE，前端通常需要自己解析流。
- 这种方式适合当前联调阶段；如果后续想更标准化，也可以考虑改成 GET + query 参数 + EventSource。

### 5.3 前端类型检查已通过

#### 验证命令

```bash
D:\develop\nodejs\node.exe D:\work\xiaofuge\111\python\frontend\node_modules\typescript\bin\tsc -p D:\work\xiaofuge\111\python\frontend\tsconfig.json
```

#### 结果

命令成功执行，无 TypeScript 编译错误。
