# 项目结构说明

## 目录结构

```
python/
├── app/                          # 应用主目录
│   ├── common/                   # 公共模块
│   │   ├── ai/                   # AI相关（LLM、提示词）
│   │   ├── tools/                # 工具类
│   │   ├── error_code.py         # 错误码定义
│   │   ├── exception.py          # 异常类
│   │   └── result.py             # 统一返回结果
│   ├── infrastructure/           # 基础设施层
│   │   ├── redis/                # Redis服务
│   │   ├── file/                 # 文件服务
│   │   └── export/               # 导出服务
│   ├── models/                   # 数据模型
│   │   └── base.py               # 基础模型
│   ├── modules/                  # 业务模块
│   │   ├── auth/                 # 用户认证
│   │   ├── resume/               # 简历管理
│   │   ├── interview/            # 面试管理
│   │   ├── interview_schedule/   # 面试排期
│   │   ├── knowledge_base/       # 知识库（RAG）
│   │   ├── voice_interview/      # 语音面试
│   │   └── agent_orchestration/  # Agent编排系统
│   ├── database.py               # 数据库配置
│   └── main.py                   # 应用入口
├── frontend/                     # 前端项目
├── docs/                         # 文档目录
│   ├── 01-项目管理/              # 项目管理文档
│   ├── 02-架构设计/              # 架构设计文档
│   ├── 03-技术方案/              # 技术方案文档
│   ├── 04-问题排查/              # 问题排查记录
│   └── 05-优化记录/              # 优化实施记录
├── migrations/                   # 数据库迁移脚本
├── scripts/                      # 工具脚本
│   ├── check_users.py            # 检查用户
│   ├── run_user_migration.py     # 用户迁移
│   ├── update_admin_password.py  # 更新管理员密码
│   └── verify_optimizations.py   # 验证优化
├── tests/                        # 测试文件
│   ├── test_agent_orchestration.py
│   ├── test_core_agents.py
│   ├── test_knowledge_builder.py
│   ├── test_pgvector.py
│   ├── test_rag_full.py
│   └── ...
├── alembic/                      # Alembic迁移工具
├── .venv/                        # Python虚拟环境
├── start.bat                     # 启动脚本
├── stop.bat                      # 停止脚本
├── pyproject.toml                # 项目配置
└── README.md                     # 项目说明

```

## 核心模块说明

### 1. Agent编排系统 (app/modules/agent_orchestration/)
- **智能决策树**：根据任务复杂度选择执行路径（简单/标准/复杂）
- **责任链模式**：多Agent协作（Planning → Execution → Quality → Summary）
- **工具注册系统**：统一管理可用工具
- **成本控制器**：监控和限制API调用成本
- **持久化服务**：保存执行历史和上下文

### 2. 知识库系统 (app/modules/knowledge_base/)
- **向量存储**：使用pgvector进行向量检索
- **RAG服务**：检索增强生成
- **文档抓取**：支持URL和文件上传
- **Rerank服务**：结果重排序优化

### 3. 用户认证 (app/modules/auth/)
- **JWT认证**：基于Token的身份验证
- **OAuth2**：标准OAuth2流程
- **密码加密**：bcrypt哈希加密

## 启动方式

### 方式1：使用启动脚本（推荐）
```bash
# 启动所有服务
start.bat

# 停止所有服务
stop.bat
```

### 方式2：手动启动
```bash
# 后端
cd D:/work/xiaofuge/111/python
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 前端
cd D:/work/xiaofuge/111/python/frontend
npm run dev
```

## 访问地址
- 前端：http://localhost:5173
- 后端API：http://localhost:8001
- API文档：http://localhost:8001/docs

## 测试账号
- 用户名：admin
- 密码：admin123

## 文件整理说明
- **tests/**：所有测试文件（test_*.py, tmp_*.py）
- **scripts/**：工具脚本（数据库迁移、密码管理等）
- **docs/**：按类型分类的文档（项目管理、架构设计、技术方案等）
