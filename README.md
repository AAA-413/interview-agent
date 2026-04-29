
# 智能 AI 面试官平台

基于大语言模型的简历分析和模拟面试系统
前端页面展示
<img width="1517" height="927" alt="回答分析" src="https://github.com/user-attachments/assets/feccdaaa-9a57-4199-824e-6111e413af12" />
<img width="1896" height="1003" alt="知识库管理" src="https://github.com/user-attachments/assets/42611b51-78d2-4f00-82b6-ce42cb023610" />
<img width="1835" height="761" alt="模拟面试" src="https://github.com/user-attachments/assets/f6d69b6e-8903-4645-8c64-b0326663d78d" />
<img width="1884" height="825" alt="面试记录" src="https://github.com/user-attachments/assets/296c9ee4-f0d9-4981-bb4e-160b547e0eb0" />
<img width="1804" height="878" alt="简历管理" src="https://github.com/user-attachments/assets/580a696b-a31d-4fd4-9e53-b3764d3fa7ad" />

---

## 快速启动

### 后端启动

```bash
# 1. 清理 Python 字节码缓存
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 2. 启动后端服务（禁用字节码缓存）
.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

### 前端启动

```bash
# 启动前端服务
cd frontend && npm run dev
```

### 服务地址

- 后端 API：http://localhost:8002
- 前端页面：http://localhost:5173
- API 文档：http://localhost:8002/docs

**详细启动流程请参考：** [服务启动指南](docs/01-项目管理/服务启动指南.md)

---

## 功能模块

### 简历管理模块

- **多格式解析**：支持 PDF、DOCX、DOC、TXT 等多种简历格式。
- **异步处理流**：基于 Redis Stream 实现异步简历分析，支持实时查看处理进度（待分析/分析中/已完成/失败）。
- **稳定性保障**：内置分析失败自动重试机制（最多 3 次）与基于内容哈希的重复检测。
- **分析报告导出**：支持将 AI 分析结果一键导出为结构化的 PDF 简历分析报告。

### 模拟面试模块

- **Skill 驱动出题**：内置 10+ 面试方向（Java 后端、阿里/字节/腾讯专项、前端、Python、算法、系统设计、测开、AI Agent 等），每个方向由 `SKILL.md` 定义考察范围、难度分布和参考知识库。
- **历史题目去重**：出题时自动排除已有会话中问过的题目，避免重复考察。
- **面试阶段时长联动**：总时长滑块拖动后，各阶段（自我介绍、技术考察、项目深挖、反问环节）按时比自动分配。
- **智能追问流**：支持配置多轮智能追问（默认 1 条），模拟多轮问答场景。
- **统一评估架构**：文字面试和语音面试共用同一套评估引擎（分批评估 + 结构化输出 + 二次汇总 + 降级兜底），评估结果可对比。
- **报告一键导出**：支持异步生成并导出详细的 PDF 模拟面试评估报告。
- **面试中心入口**：面试中心页整合文字面试和语音面试入口，支持继续面试和重新面试。


### 知识库管理模块

- **文档上传入库**：支持上传 PDF、DOCX、TXT、Markdown 等文档，自动抽取文本并保存文件元信息。
- **异步索引状态流转**：上传后先返回 `PENDING`，后台通过 Redis Stream worker 完成分块和索引，状态推进到 `PROCESSING / COMPLETED / FAILED`。
- **RAG 问答接口**：提供普通问答接口与 SSE 流式问答接口，并保留历史问答列表。
- **前端联调已完成**：提供知识库列表页、上传页、详情页、命中片段展示、历史问答展示与索引状态自动轮询。
- **轻量向量化实现**：当前版本先使用稳定的文本分块 + 本地 embedding 占位实现，便于本地联调；后续可平滑切换到 pgvector 真正落库。
- **可观测排障记录**：实现过程中的问题与修复记录见 `docs/knowledge-base-phase4-debugging.md`。

### 开发依赖与测试

- 开发依赖统一声明在 `pyproject.toml` 的 `dev` 组中，包含 `pytest`、`pytest-asyncio`、`ruff`、`mypy` 等工具。
- 推荐在项目根目录执行以下命令安装：

```bash
.venv\Scripts\python.exe -m pip install -e .[dev]
```

- 当前知识库最小化测试文件：`tests/test_knowledge_base_services.py`
- 运行知识库测试：

```bash
.venv\Scripts\python.exe -m pytest tests/test_knowledge_base_services.py -q
```

- 本地验证结果（2026-04-17）：知识库测试 `4 passed`
- 若 Windows 控制台出现中文乱码，优先以 pytest 退出码和结构化结果为准，不要仅凭终端中文显示判断失败。



