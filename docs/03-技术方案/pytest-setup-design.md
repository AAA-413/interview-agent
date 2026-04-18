# pytest 环境落地与知识库测试设计方案

> 文档日期：2026-04-17  
> 用途：记录本轮 pytest 安装、测试打通、文档同步的设计思路与执行结果，便于下次新会话快速恢复上下文

---

## 一、这次工作的目标

本轮工作的目标不是继续扩展 Phase 4 功能，而是把“已有知识库测试文件”推进到“可在当前 `.venv` 中真实执行”的状态，并把执行方法写进项目文档。

核心目标包括：

1. 安装并验证 `pytest`
2. 复用现有 `pyproject.toml` 的 `dev` 依赖口径
3. 跑通 `tests/test_knowledge_base_services.py`
4. 将安装方法、执行命令、测试结果同步到 README / PROGRESS / 排障文档
5. 形成一份可供后续会话直接复用的设计说明

---

## 二、为什么这样设计

### 2.1 优先复用现有依赖定义，而不是临时手装

项目的 `pyproject.toml` 已经声明：

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.28.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
]
```

因此本轮没有采用“只手工安装 `pytest pytest-asyncio`”作为主路径，而是优先走：

```bash
.venv\Scripts\python.exe -m pip install -e .[dev]
```

这样做的原因：

- 避免依赖口径分裂
- 保证 README、环境、开发流程一致
- 后续 `ruff`、`mypy` 也能一起进入 `.venv`
- 方便后面继续做更完整的测试体系建设

---

### 2.2 先解决“环境不可用”，再解决“测试不可执行”

这次不是业务逻辑优先出问题，而是存在两层阻塞：

#### 第一层：pytest 没装上

执行：

```bash
.venv\Scripts\python.exe -m pytest -q
```

直接报：

```text
No module named pytest
```

#### 第二层：即使装上 pytest，异步测试也不能直接执行

`tests/test_knowledge_base_services.py` 中存在多个：

```python
async def test_xxx():
```

但没有 `@pytest.mark.asyncio`，导致 pytest 无法把这些测试放到事件循环里运行。

所以设计顺序必须是：

1. 先把 `pytest` 和 `pytest-asyncio` 真正装进 `.venv`
2. 再把现有异步测试调整为 pytest 可直接收集执行的形式
3. 最后再写文档和沉淀方案

---

### 2.3 保持最小改动面

本轮没有顺手去扩展业务代码，也没有直接新增一整套 API 测试，而是只做了让“现有测试真正可跑”的最小必要改动：

- 修正 editable 安装配置
- 修正异步测试标记
- 更新文档

这样可以避免把“测试环境修复”扩展成大范围重构。

---

## 三、这次实际遇到的问题与解决方案

### 3.1 `pip install -e .[dev]` 初次失败

#### 现象

执行：

```bash
.venv\Scripts\python.exe -m pip install -e .[dev]
```

报错核心是：

```text
ValueError: Unable to determine which files to ship inside the wheel
```

#### 根因

项目使用：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

但没有声明 wheel 打包目录，Hatch 无法判断 editable 安装时该把哪个目录作为包。

#### 修复

在 `pyproject.toml` 中补充：

```toml
[tool.hatch.build.targets.wheel]
packages = ["app"]
```

这样 editable 安装即可成功。

---

### 3.2 异步测试在 pytest 下直接失败

#### 现象

安装完成后执行：

```bash
.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q
```

出现 3 个失败，报错核心为：

```text
async def functions are not natively supported.
```

#### 根因

虽然 `pytest-asyncio` 已安装，但测试函数没有声明 `@pytest.mark.asyncio`。

#### 修复

给这 3 个测试补上：

- `test_vector_service_split_text_creates_chunks`
- `test_rag_service_returns_ranked_references`
- `test_index_task_handler_marks_failed_when_source_text_empty`

都加上：

```python
@pytest.mark.asyncio
```

保留同步包装测试 `test_async_knowledge_base_suite()`，兼容原来的 `asyncio.run(...)` 验证方式。

---

## 四、本轮最终改动

### 4.1 代码与配置改动

#### `pyproject.toml`
新增：

```toml
[tool.hatch.build.targets.wheel]
packages = ["app"]
```

#### `tests/test_knowledge_base_services.py`
新增：

```python
import pytest
```

并为 3 个异步测试加上：

```python
@pytest.mark.asyncio
```

---

### 4.2 文档改动

#### `README.md`
新增“开发依赖与测试”小节，说明：

- 如何安装 dev 依赖
- 如何执行知识库测试
- 当前验证结果 `4 passed`
- Windows 控制台乱码时如何判断

#### `PROGRESS.md`
新增：

- `2.4 测试环境（pytest）`
- pytest 版本验证命令
- 知识库测试执行结果
- 两个已解决问题：editable 安装失败、async 测试未声明 asyncio 标记

#### `docs/knowledge-base-phase4-debugging.md`
更新：

- 原来“缺少 pytest”的问题已闭环
- 新增 Hatch editable 安装失败的根因与修复
- 新增 async 测试在 pytest 下失败的根因与修复
- 写明最终结果：`pytest 9.0.3`，`4 passed`

---

## 五、最终验证结果

### 5.1 安装验证

```bash
.venv\Scripts\python.exe -m pytest --version
```

结果：

```text
pytest 9.0.3
```

### 5.2 测试验证

```bash
.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q
```

结果：

```text
4 passed
```

---

## 六、下次新会话如何快速恢复

如果下次要继续推进知识库测试、联调或后续 Phase 5/6，可优先阅读以下文件：

1. `PROGRESS.md`
   - 看当前整体进度、启动方式、已解决问题、下一步行动
2. `docs/knowledge-base-phase4-debugging.md`
   - 看 Phase 4 联调与测试过程中踩过的坑
3. `docs/pytest-setup-design.md`
   - 看这次 pytest 环境落地的设计思路与最终结果
4. `README.md`
   - 看开发依赖与测试入口命令
5. `如何启动.md`
   - 看 Windows 下最直接的启动命令清单

---

## 七、推荐的后续动作

1. 继续补 API 级知识库测试：
   - 上传
   - 列表
   - 详情
   - reindex
   - 普通问答
   - SSE 流式问答
2. 如后续异步测试继续增多，可考虑统一引入 `pytest.ini` 或 `pyproject.toml` 中的 pytest 配置
3. 如果要让新会话恢复更快，可继续把“真实联调命令 + 常见报错”收敛到 `如何启动.md`

---

## 八、最短执行命令清单

### 安装开发依赖

```bash
cd d:\work\xiaofuge\111\python
.venv\Scripts\python.exe -m pip install -e .[dev]
```

### 查看 pytest 版本

```bash
.venv\Scripts\python.exe -m pytest --version
```

### 运行知识库测试

```bash
.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q
```

### 启动后端

```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 启动前端

```bash
cd frontend
D:\develop\nodejs\node.exe node_modules\vite\bin\vite.js
```
