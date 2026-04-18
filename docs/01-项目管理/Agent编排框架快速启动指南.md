# Agent 编排框架快速启动指南

## 🚀 快速开始

### 1. 运行数据库迁移

```bash
# 连接到 PostgreSQL
psql -U postgres -d ai_interview

# 执行迁移脚本
\i migrations/003_agent_orchestration.sql
```

或者使用 Python 脚本：

```bash
python -c "
from sqlalchemy import text
from app.database import engine
import asyncio

async def migrate():
    async with engine.begin() as conn:
        with open('migrations/003_agent_orchestration.sql', 'r', encoding='utf-8') as f:
            sql = f.read()
            await conn.execute(text(sql))
    print('✅ 数据库迁移完成')

asyncio.run(migrate())
"
```

### 2. 启动后端服务

```bash
# 确保在项目根目录
cd D:\work\xiaofuge\111\python

# 启动服务
uvicorn app.main:app --reload --port 8001
```

### 3. 测试 API

#### 测试 1：简单问答

```bash
curl -X POST http://localhost:8001/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "什么是 Python？",
    "kb_ids": [1],
    "max_step": 5,
    "model": "qwen-plus"
  }'
```

预期响应：
```json
{
  "session_id": "uuid-here",
  "answer": "Python 是一种高级编程语言...",
  "execution_path": "simple",
  "total_steps": 1,
  "quality_score": null,
  "total_tokens": 150,
  "total_cost": 0.0012,
  "execution_time_ms": 1500
}
```

#### 测试 2：复杂任务

```bash
curl -X POST http://localhost:8001/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "帮我设计一个用户认证系统，包括注册、登录、权限管理",
    "kb_ids": [1, 2],
    "max_step": 10,
    "model": "qwen-plus",
    "budget_limit": 1.0
  }'
```

预期响应：
```json
{
  "session_id": "uuid-here",
  "answer": "用户认证系统设计方案：\n\n1. 注册模块...",
  "execution_path": "complex",
  "total_steps": 8,
  "quality_score": 8.5,
  "total_tokens": 5000,
  "total_cost": 0.12,
  "execution_time_ms": 15000
}
```

#### 测试 3：查询执行记录

```bash
# 获取单个执行记录
curl http://localhost:8001/api/agent/executions/{session_id}

# 列出所有执行记录
curl http://localhost:8001/api/agent/executions?limit=10&offset=0
```

### 4. 运行单元测试

```bash
# 运行所有测试
python -m pytest tests/test_agent_orchestration.py -v

# 运行特定测试
python -m pytest tests/test_agent_orchestration.py::TestCostController -v

# 查看测试覆盖率
python -m pytest tests/test_agent_orchestration.py --cov=app.modules.agent_orchestration
```

## 📊 查看执行记录

### 使用 SQL 查询

```sql
-- 查看最近的执行记录
SELECT 
    session_id,
    user_input,
    execution_path,
    total_steps,
    total_tokens,
    total_cost,
    status,
    created_at
FROM agent_executions
ORDER BY created_at DESC
LIMIT 10;

-- 查看执行步骤
SELECT 
    e.session_id,
    s.step_number,
    s.agent_name,
    s.tokens_used,
    s.execution_time_ms,
    s.status
FROM agent_execution_steps s
JOIN agent_executions e ON s.execution_id = e.id
WHERE e.session_id = 'your-session-id'
ORDER BY s.step_number;

-- 查看成本统计
SELECT 
    agent_name,
    model,
    SUM(total_tokens) as total_tokens,
    SUM(estimated_cost) as total_cost,
    COUNT(*) as execution_count
FROM agent_cost_logs
GROUP BY agent_name, model
ORDER BY total_cost DESC;
```

## 🔧 配置说明

### 环境变量

在 `.env` 文件中配置：

```env
# 数据库配置
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/ai_interview

# LLM 配置
DASHSCOPE_API_KEY=your-api-key
DEFAULT_MODEL=qwen-plus

# Agent 配置
AGENT_MAX_STEP=10
AGENT_BUDGET_LIMIT=1.0
AGENT_DEFAULT_TEMPERATURE=0.7
```

### 自定义配置

在代码中自定义：

```python
from app.modules.agent_orchestration import (
    AgentFactory,
    CostController,
    DecisionTree,
)

# 自定义成本控制
cost_controller = CostController(budget_limit=5.0)

# 自定义决策树
decision_tree = DecisionTree(
    knowledge_service=knowledge_service,
    complexity_threshold=0.5,
)

# 自定义工厂
factory = AgentFactory(
    llm_provider=llm_provider,
    knowledge_service=knowledge_service,
    cost_controller=cost_controller,
    tool_registry=tool_registry,
)
```

## 📝 常见问题

### Q1: 数据库迁移失败？

**A:** 检查 PostgreSQL 版本和权限：
```bash
# 检查版本
psql --version

# 检查权限
psql -U postgres -c "SELECT current_user, current_database();"
```

### Q2: API 返回 500 错误？

**A:** 检查日志和数据库连接：
```bash
# 查看日志
tail -f logs/app.log

# 测试数据库连接
python -c "
from app.database import engine
import asyncio

async def test():
    async with engine.connect() as conn:
        result = await conn.execute('SELECT 1')
        print('✅ 数据库连接正常')

asyncio.run(test())
"
```

### Q3: 测试失败？

**A:** 确保安装了测试依赖：
```bash
pip install pytest pytest-asyncio
```

### Q4: 成本计算不准确？

**A:** 检查模型价格配置：
```python
# 在 cost_controller.py 中查看 PRICING 字典
# 根据实际价格调整
```

## 🎯 下一步

1. **前端集成** - 创建 Agent 聊天界面
2. **WebSocket 支持** - 实现实时流式输出
3. **监控面板** - 可视化执行记录和成本统计
4. **性能优化** - 并行执行、缓存机制
5. **更多工具** - 扩展工具注册系统

## 📚 相关文档

- [Agent编排框架实现总结.md](./Agent编排框架实现总结.md)
- [Agent编排框架完整实现总结.md](./Agent编排框架完整实现总结.md)
- [智能Agent编排架构设计.md](../02-架构设计/智能Agent编排架构设计.md)
- [README.md](../../app/modules/agent_orchestration/README.md)

## 🆘 获取帮助

如果遇到问题：
1. 查看日志文件
2. 检查数据库连接
3. 运行单元测试
4. 查看相关文档

祝使用愉快！🎉
