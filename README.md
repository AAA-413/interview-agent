# OfferPilot 智能 AI 面试官平台

基于大语言模型的简历分析、项目深挖、知识库增强和模拟面试系统。产品定位为面向求职者、高校就业中心、培训机构和企业内推场景的 AI 面试训练工作台，帮助用户把“上传简历 → 诊断差距 → 项目追问 → 模拟面试 → 报告复盘”跑成可持续交付的训练闭环。

## 市场化能力

- **清晰产品入口**：内置工作台首页，展示简历资产、面试记录、知识库状态和下一步训练建议。
- **自助获客链路**：登录页支持注册，注册后自动进入工作台，适合演示、试用和小规模种子用户。
- **可打包场景**：个人求职订阅、高校就业训练营、培训机构学员陪跑、企业内推面试预演。
- **交付闭环**：简历诊断、项目深挖、模拟面试、知识库 RAG 和 PDF 报告能力已经串联。
- **工程可信度**：JWT 多用户隔离、异步任务、Docker Compose、CI 质量检查、生产 Compose 和 Nginx 配置齐备。

前端页面展示
<img width="2469" height="1175" alt="1b737b71-292e-4c7a-bd91-372ac7305278" src="https://github.com/user-attachments/assets/9e721530-91e3-4c20-8c75-f45eb09c9093" />
<img width="1517" height="927" alt="回答分析" src="https://github.com/user-attachments/assets/feccdaaa-9a57-4199-824e-6111e413af12" />
<img width="1896" height="1003" alt="知识库管理" src="https://github.com/user-attachments/assets/42611b51-78d2-4f00-82b6-ce42cb023610" />
<img width="1835" height="761" alt="模拟面试" src="https://github.com/user-attachments/assets/f6d69b6e-8903-4645-8c64-b0326663d78d" />
<img width="1884" height="825" alt="面试记录" src="https://github.com/user-attachments/assets/296c9ee4-f0d9-4981-bb4e-160b547e0eb0" />
<img width="1804" height="878" alt="简历管理" src="https://github.com/user-attachments/assets/580a696b-a31d-4fd4-9e53-b3764d3fa7ad" />

## 技术栈

- **后端**：FastAPI + SQLAlchemy + PostgreSQL + Redis + LangChain
- **前端**：React 18 + TypeScript + Tailwind CSS v4 + AntV G6
- **AI**：DeepSeek（deepseek-chat）+ LangChain Structured Output
- **Embedding**：智谱 Embedding-3（2048 维截断至 1536）/ DashScope / 哈希降级
- **语音识别**：MediaRecorder 录音上传 + 本地 faster-whisper 转写（voice-lite）
- **异步任务**：Redis Stream 消费者组模式（xreadgroup + xack）
- **向量检索**：pgvector + Rerank 重排序（BGE Reranker）
- **知识图谱**：PostgreSQL 三元组表 + LLM 实体关系抽取 + GraphRAG 混合检索
- **部署**：Docker Compose + Nginx + gunicorn/uvicorn

## 快速启动

### 一键启动/停止（推荐）

```bash
# 启动 Docker 依赖、后端和前端
./start.sh

# 停止本项目后端、前端和 Docker 依赖
./stop.sh
```

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
- 前端页面：http://localhost:5176（`./start.sh` 默认端口；手动 `npm run dev` 会使用 Vite 默认端口 5173）
- 产品工作台：http://localhost:5176/dashboard
- API 文档：http://localhost:8002/docs

### 演示路径

1. 注册或登录账号，进入 OfferPilot 工作台。
2. 上传一份简历，等待异步解析完成。
3. 进入面试诊断，填写目标岗位、公司和 JD。
4. 根据诊断结果进入项目深挖或模拟面试。
5. 完成面试后查看复盘报告，并导出 PDF。

### 本地质量检查

```bash
./scripts/quality_check.sh
```

该脚本会依次执行 Python 编译检查、全量 Ruff 检查、Ruff 格式检查、pytest 基础测试和前端生产构建。

## 功能模块

### 简历管理

- 多格式解析（PDF、DOCX、DOC、TXT）
- Redis Stream 异步简历分析，实时状态追踪
- AI 评分报告（内容、结构、技能匹配、表达、项目五个维度）

### 模拟面试

- 10+ 面试方向（Java 后端、阿里/字节/腾讯专项、前端、Python、算法、系统设计、测开、AI Agent 等）
- 历史题目自动去重
- **实时追问**：根据候选人回答质量动态生成追问，每个主问题最多追问 2 次
- **知识题评估**：出题时生成参考答案和 key_points 评分锚点，评估时逐点对比
- **项目题评估**：四维评估（真实性、技术深度、深度、表达）
- **六档评分体系**：空白(0-19) → 知道名词(20-39) → 知道定义(40-59) → 理解原理(60-74) → 能用能说清(75-89) → 深度掌控(90-100)
- **语音输入**：录音上传到后端本地 faster-whisper 转写，转写文本可编辑后提交，不影响原有评分链路
- **知识库集成**：评估时从用户知识库检索相关知识点作为参考
- 简历结构化提取（项目列表、技术栈、经验等级）

### 知识库 RAG

- 文档上传入库（PDF、DOCX、TXT、Markdown）
- 异步索引：PENDING → PROCESSING → COMPLETED / FAILED
- pgvector 向量检索 + Rerank 重排序
- SSE 流式问答接口

### 知识图谱

- PostgreSQL 三元组表存储实体-关系-实体结构
- LLM 实体关系抽取（DeepSeek 自动从文档中提取技术/概念/工具/框架等实体及关系）
- 新文档入库自动构建图谱（索引流程集成抽取，失败不影响主流程）
- 前端 AntV G6 力导向图可视化，支持搜索高亮、类型筛选、实体详情侧栏
- GraphRAG 混合检索（向量检索 + 图谱三元组遍历双通道并行）

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
│   │   ├── knowledge_graph/ # 知识图谱（实体关系抽取 + GraphRAG）
│   │   └── agent_orchestration/  # Agent 编排
│   └── main.py              # 应用入口
├── frontend/                # React 前端
├── skills/                  # 面试方向定义（SKILL.md）
├── docs/                    # 技术文档
├── docker-compose.yml       # Docker 编排
└── requirements.txt         # Python 依赖
```

## 安全与优化

- **用户级数据隔离**：所有业务表 `user_id` 外键，查询带用户过滤（IDOR 修复）
- **JWT 认证链路**：全局中间件解析 token → `request.state` → `Depends` 注入
- **输入校验**：Pydantic Field 约束（范围、长度）
- **文件上传安全**：文件名清理 + PDF 魔术字节检测
- **SSE 真流式输出**：LangChain `astream()` token-by-token 推送
- **异步任务超时**：`asyncio.wait_for` 5 分钟兜底
- **LLM 监控**：装饰器模式记录 token 消耗和调用时长

## Docker 部署

```bash
# 开发环境
docker-compose up -d

# 生产环境
cp .env.prod.example .env.prod
# 编辑 .env.prod 填入真实密钥
docker-compose -f docker-compose.prod.yml up -d
```
