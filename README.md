# 智能 AI 面试官平台

基于大语言模型的简历分析和模拟面试系统。

前端页面展示
<img width="1517" height="927" alt="回答分析" src="https://github.com/user-attachments/assets/feccdaaa-9a57-4199-824e-6111e413af12" />
<img width="1896" height="1003" alt="知识库管理" src="https://github.com/user-attachments/assets/42611b51-78d2-4f00-82b6-ce42cb023610" />
<img width="1835" height="761" alt="模拟面试" src="https://github.com/user-attachments/assets/f6d69b6e-8903-4645-8c64-b0326663d78d" />
<img width="1884" height="825" alt="面试记录" src="https://github.com/user-attachments/assets/296c9ee4-f0d9-4981-bb4e-160b547e0eb0" />
<img width="1804" height="878" alt="简历管理" src="https://github.com/user-attachments/assets/580a696b-a31d-4fd4-9e53-b3764d3fa7ad" />

## 技术栈

- **后端**：FastAPI + SQLAlchemy + PostgreSQL + Redis + LangChain
- **前端**：React 18 + TypeScript + Ant Design
- **AI**：通义千问（qwen-plus）+ LangChain Structured Output
- **异步任务**：Redis Stream 消费者组模式
- **向量检索**：pgvector + Rerank 重排序

## 快速启动

### 后端

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际的 API Key 和数据库配置

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 服务地址

- 后端 API：http://localhost:8002
- 前端页面：http://localhost:5173
- API 文档：http://localhost:8002/docs

## 功能模块

### 简历管理

- 多格式解析（PDF、DOCX、DOC、TXT）
- Redis Stream 异步简历分析，实时状态追踪
- AI 评分报告（内容、结构、技能匹配、表达、项目五个维度）
- 分析报告 PDF 导出

### 模拟面试

- 10+ 面试方向（Java 后端、阿里/字节/腾讯专项、前端、Python、算法、系统设计、测开、AI Agent 等）
- 历史题目自动去重
- 支持多轮智能追问
- 分批评估 + 结构化输出 + 二次汇总的统一评估架构
- 面试评估报告 PDF 导出

### 知识库 RAG

- 文档上传入库（PDF、DOCX、TXT、Markdown）
- 异步索引：PENDING → PROCESSING → COMPLETED / FAILED
- pgvector 向量检索 + Rerank 重排序
- SSE 流式问答接口

### Agent 智能下载

- URL 解析 → 内容抓取 → 知识库构建的全自动流水线
- 多 Agent 编排（Planning → Execution → Quality → Summary）
- 搜索引擎集成（Tavily / Serper / Bing / Google）

## 项目结构

```
python/
├── app/
│   ├── common/              # 公共模块（异常、错误码、AI 适配器）
│   ├── infrastructure/      # 基础设施（Redis、文件存储）
│   ├── modules/
│   │   ├── auth/            # 用户认证（JWT）
│   │   ├── resume/          # 简历管理
│   │   ├── interview/       # 模拟面试
│   │   ├── knowledge_base/  # 知识库 RAG
│   │   └── agent_orchestration/  # Agent 编排
│   └── main.py              # 应用入口
├── frontend/                # React 前端
├── skills/                  # 面试方向定义（SKILL.md）
├── docs/                    # 技术文档
├── docker-compose.yml       # Docker 编排
└── requirements.txt         # Python 依赖
```

## Docker 部署

```bash
docker-compose up -d
```
