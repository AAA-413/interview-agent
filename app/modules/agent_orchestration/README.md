# Agent 编排框架使用指南

## 📚 概述

本框架实现了智能 Agent 编排系统，支持决策树路由、责任链执行、工具注册等核心功能。

## 🏗️ 架构组件

### 1. 核心类

```
app/modules/agent_orchestration/
├── base_agent.py          # BaseAgent 基类和 DynamicContext
├── agent_chain.py         # AgentChain 责任链执行器
├── decision_tree.py       # DecisionTree 决策树
├── agent_factory.py       # AgentFactory 工厂类
├── tool_registry.py       # AgentToolRegistry 工具注册
├── cost_controller.py     # CostController 成本控制
└── nodes/                 # 具体节点实现
    ├── root_node.py       # 根节点（任务分析）
    ├── simple_generator_node.py  # 简单生成节点
    └── step1_analyzer_node.py    # 步骤1分析节点
```

### 2. 执行流程

```
用户输入
    ↓
DecisionTree.evaluate()  # 决策树评估
    ↓
AgentFactory.create_chain()  # 创建责任链
    ↓
AgentChain.execute()  # 执行责任链
    ↓
返回结果
```

## 🚀 快速开始

### 示例 1：简单问答（Simple 路径）

```python
from app.modules.agent_orchestration import (
    DecisionTree,
    AgentFactory,
    AgentChain,
    DynamicContext,
    ExecutionPath,
)

# 1. 创建上下文
context = DynamicContext()
context.current_task = "什么是 Python？"
context.set_value("knowledge_coverage", 0.9)

# 2. 决策树评估
decision_tree = DecisionTree()
path = decision_tree.evaluate(
    task=context.current_task,
    knowledge_coverage=context.get_value("knowledge_coverage"),
)
print(f"执行路径: {path}")  # ExecutionPath.SIMPLE

# 3. 创建责任链
factory = AgentFactory(llm_provider, knowledge_service)
root_agent = factory.create_chain(path)

# 4. 执行责任链
chain = AgentChain()
result = await chain.execute(root_agent, context)
print(f"结果: {result}")
```

### 示例 2：标准流程（Standard 路径）

```python
# 1. 创建上下文
context = DynamicContext()
context.current_task = "帮我分析这段代码的性能问题"
context.set_value("knowledge_coverage", 0.6)
context.max_step = 3  # 最多3轮

# 2. 决策树评估
path = decision_tree.evaluate(
    task=context.current_task,
    knowledge_coverage=0.6,
)
print(f"执行路径: {path}")  # ExecutionPath.STANDARD

# 3. 创建责任链（4个节点）
root_agent = factory.create_chain(path)
# RootNode → Step1Analyzer → Step2Executor → Step4Summary

# 4. 执行责任链
result = await chain.execute(root_agent, context)
```

### 示例 3：复杂任务（Complex 路径）

```python
# 1. 创建上下文
context = DynamicContext()
context.current_task = "设计一个分布式缓存系统"
context.set_value("knowledge_coverage", 0.3)
context.max_step = 3

# 2. 决策树评估
path = decision_tree.evaluate(
    task=context.current_task,
    knowledge_coverage=0.3,
)
print(f"执行路径: {path}")  # ExecutionPath.COMPLEX

# 3. 创建责任链（5个节点）
root_agent = factory.create_chain(path)
# RootNode → Step1Analyzer → Step2Executor → Step3Quality → Step4Summary

# 4. 执行责任链（带质检和重试）
result = await chain.execute(root_agent, context)
```

## 🔧 工具注册

### 注册自定义工具

```python
from app.modules.agent_orchestration import AgentToolRegistry

# 1. 创建工具注册表
registry = AgentToolRegistry()


# 2. 定义工具函数
async def custom_search(query: str, top_k: int = 5) -> list:
    """自定义搜索工具"""
    # 实现搜索逻辑
    return results


# 3. 注册工具
registry.register_tool(
    name="custom_search",
    func=custom_search,
    schema={
        "name": "custom_search",
        "description": "自定义搜索工具",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询"},
                "top_k": {"type": "integer", "description": "返回结果数量"},
            },
            "required": ["query"],
        },
    },
)

# 4. 在 Agent 中使用
tool = registry.get_tool("custom_search")
result = await tool["func"](query="test", top_k=3)
```

### 内置工具

框架提供以下内置工具：

1. **knowledge_search**: 知识库检索
2. **task_create**: 创建任务
3. **task_update**: 更新任务状态
4. **code_execute**: 执行代码

## 💰 成本控制

```python
from app.modules.agent_orchestration import CostController

# 1. 创建成本控制器
cost_controller = CostController(max_cost=10.0)

# 2. 在执行前检查
if cost_controller.can_retry():
    # 执行任务
    result = await agent.execute(context)
    
    # 记录成本
    cost_controller.add_cost(
        input_tokens=1000,
        output_tokens=500,
        model="qwen-plus",
    )

# 3. 检查是否需要降级
if cost_controller.should_degrade():
    print("成本过高，建议降级")
    # 切换到更便宜的模型或简化流程
```

## 📊 执行历史

```python
# 查看执行历史
for step in context.execution_history:
    print(f"步骤 {step['step']}: {step['agent']} - {step['result'][:50]}...")

# 获取数据对象
user_data = context.get_value("user_profile")
search_results = context.get_value("search_results")
```

## 🔄 重试机制

```python
# 在 AgentChain 中自动处理重试
context.max_step = 3  # 最多3轮

# 执行过程中，如果质检失败会自动重试
# Step1 → Step2 → Step3(质检失败) → Step1(重新规划) → ...
```

## 🎯 最佳实践

### 1. 选择合适的执行路径

- **Simple**: 简单问答，知识库覆盖率 > 80%
- **Standard**: 需要规划和执行，覆盖率 50-80%
- **Complex**: 复杂任务，覆盖率 < 50%，需要质检

### 2. 合理设置最大步数

```python
# 简单任务
context.max_step = 1

# 标准任务
context.max_step = 2

# 复杂任务
context.max_step = 3
```

### 3. 使用上下文传递数据

```python
# 存储数据
context.set_value("user_profile", user_data)
context.set_value("search_results", results)

# 读取数据
user_data = context.get_value("user_profile")
```

### 4. 监控成本

```python
# 定期检查成本
if cost_controller.current_cost > 5.0:
    logger.warning(f"成本较高: {cost_controller.current_cost}")
```

## 🔌 集成到 FastAPI

```python
from fastapi import APIRouter, Depends
from app.modules.agent_orchestration import (
    DecisionTree,
    AgentFactory,
    AgentChain,
    DynamicContext,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat")
async def agent_chat(
    request: ChatRequest,
    llm_provider=Depends(get_llm_provider),
    knowledge_service=Depends(get_knowledge_service),
):
    # 1. 创建上下文
    context = DynamicContext()
    context.current_task = request.message
    context.set_value("knowledge_coverage", 0.7)

    # 2. 决策树评估
    decision_tree = DecisionTree()
    path = decision_tree.evaluate(
        task=context.current_task,
        knowledge_coverage=0.7,
    )

    # 3. 创建并执行责任链
    factory = AgentFactory(llm_provider, knowledge_service)
    root_agent = factory.create_chain(path)

    chain = AgentChain()
    result = await chain.execute(root_agent, context)

    return {"answer": result, "path": path.value}
```

## 📝 待实现功能

- [ ] 完善 Step2ExecutorNode（任务执行）
- [ ] 完善 Step3QualityNode（质量检查）
- [ ] 完善 Step4SummaryNode（结果总结）
- [ ] 添加数据库持久化（execution_log 表）
- [ ] 添加 WebSocket 支持（实时流式输出）
- [ ] 添加更多内置工具
- [ ] 添加单元测试

## 🔗 参考资料

- [智能Agent编排架构设计.md](../../../docs/02-架构设计/智能Agent编排架构设计.md)
- [Claude Code Agent 设计](../../../docs/claude_code_aengt/)
- [ai-agent-station-study](../../../docs/参考项目/ai-agent-station-study-main/)
