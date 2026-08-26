# Phase 3 架构重构方案

## 当前架构分析

### Phase 1 实现（基础框架）

**保留的组件**：
1. ✅ **DecisionTree** - 决策树路径选择
   - 位置：`app/modules/agent_orchestration/decision_tree.py`
   - 作用：根据任务复杂度选择执行路径（Simple/Standard/Complex）
   - 状态：**保留** - 与 AgentOrchestrator 配合使用

2. ✅ **AgentChain** - 责任链执行器
   - 位置：`app/modules/agent_orchestration/agent_chain.py`
   - 作用：串联多个节点顺序执行
   - 状态：**保留** - 可用于复杂流程编排

3. ✅ **CostController** - 成本控制器
   - 位置：`app/modules/agent_orchestration/cost_controller.py`
   - 作用：Token 预算管理和自动降级
   - 状态：**保留** - 生产环境必需

4. ✅ **ToolRegistry** - 工具注册系统
   - 位置：`app/modules/agent_orchestration/tool_registry.py`
   - 作用：动态注册和调用工具
   - 状态：**保留** - 扩展性核心

5. ✅ **AgentFactory** - Agent 工厂
   - 位置：`app/modules/agent_orchestration/agent_factory.py`
   - 作用：创建不同类型的 Agent
   - 状态：**保留** - 但需要与 Phase 2 的 ExecutionAgentFactory 合并

6. ✅ **BaseAgent** - Agent 基类
   - 位置：`app/modules/agent_orchestration/base_agent.py`
   - 作用：定义 Agent 接口和上下文
   - 状态：**保留** - 基础抽象

**需要重构的组件**：
1. ❌ **节点系统（Nodes）** - 与 Phase 2 的 Agent 系统重复
   - `nodes/root_node.py`
   - `nodes/simple_generator_node.py`
   - `nodes/step1_analyzer_node.py`
   - `nodes/step2_executor_node.py`
   - `nodes/step3_quality_node.py`
   - `nodes/step4_summary_node.py`
   - 状态：**废弃** - 被 Phase 2 的 4 个核心 Agent 替代

### Phase 2 实现（核心 Agent）

**核心组件**（全部保留）：
1. ✅ **AgentOrchestrator** - 核心编排器
   - 位置：`app/modules/agent_orchestration/orchestrator.py`
   - 作用：协调 4 个核心 Agent 的执行
   - 状态：**保留并增强**

2. ✅ **PlanningAgent** - 规划 Agent
   - 位置：`app/modules/agent_orchestration/agents/planning_agent.py`
   - 作用：意图识别、任务分解、执行策略
   - 状态：**保留**

3. ✅ **ExecutionAgent** - 执行 Agent
   - 位置：`app/modules/agent_orchestration/agents/execution_agent.py`
   - 包含：5 个专门执行 Agent
   - 状态：**保留并扩展**

4. ✅ **QualityAgent** - 质检 Agent
   - 位置：`app/modules/agent_orchestration/agents/quality_agent.py`
   - 作用：四维度质量评估
   - 状态：**保留**

5. ✅ **SummaryAgent** - 总结 Agent
   - 位置：`app/modules/agent_orchestration/agents/summary_agent.py`
   - 作用：结果整合和总结
   - 状态：**保留**

---

## Phase 3 重构方案

### 目标
1. 统一 Phase 1 和 Phase 2 的架构
2. 废弃冗余的节点系统
3. 增强 AgentOrchestrator 的能力
4. 保留所有有价值的基础组件

### 重构步骤

#### Step 1: 废弃节点系统 ✅

**删除文件**：
```bash
# 删除所有节点文件
rm app/modules/agent_orchestration/nodes/root_node.py
rm app/modules/agent_orchestration/nodes/simple_generator_node.py
rm app/modules/agent_orchestration/nodes/step1_analyzer_node.py
rm app/modules/agent_orchestration/nodes/step2_executor_node.py
rm app/modules/agent_orchestration/nodes/step3_quality_node.py
rm app/modules/agent_orchestration/nodes/step4_summary_node.py
rm app/modules/agent_orchestration/nodes/__init__.py
rmdir app/modules/agent_orchestration/nodes
```

**原因**：
- 节点系统与 Phase 2 的 Agent 系统功能重复
- Phase 2 的 Agent 系统更加灵活和强大
- 节点系统的四阶段流程已被 AgentOrchestrator 实现

#### Step 2: 合并 AgentFactory ✅

**当前状态**：
- Phase 1: `AgentFactory` - 创建基础 Agent
- Phase 2: `ExecutionAgentFactory` - 创建执行 Agent

**重构方案**：
```python
# app/modules/agent_orchestration/agent_factory.py


class AgentFactory:
    """统一的 Agent 工厂"""

    @staticmethod
    def create_planning_agent(llm_provider, knowledge_service=None):
        """创建规划 Agent"""
        return PlanningAgent(llm_provider, knowledge_service)

    @staticmethod
    def create_execution_agent(agent_type, llm_provider, knowledge_service=None):
        """创建执行 Agent（委托给 ExecutionAgentFactory）"""
        return ExecutionAgentFactory.create_agent(
            agent_type=agent_type,
            llm_provider=llm_provider,
            knowledge_service=knowledge_service,
        )

    @staticmethod
    def create_quality_agent(llm_provider):
        """创建质检 Agent"""
        return QualityAgent(llm_provider)

    @staticmethod
    def create_summary_agent(llm_provider):
        """创建总结 Agent"""
        return SummaryAgent(llm_provider)

    @staticmethod
    def create_orchestrator(llm_provider, knowledge_service=None, max_retries=2):
        """创建编排器"""
        return AgentOrchestrator(
            llm_provider=llm_provider,
            knowledge_service=knowledge_service,
            max_retries=max_retries,
        )
```

#### Step 3: 增强 AgentOrchestrator ✅

**集成 Phase 1 组件**：

```python
# app/modules/agent_orchestration/orchestrator.py


class AgentOrchestrator:
    """核心编排器（增强版）"""

    def __init__(
        self,
        llm_provider: LLMProvider,
        knowledge_service: Optional[Any] = None,
        max_retries: int = 2,
        cost_controller: Optional[CostController] = None,  # 新增
        tool_registry: Optional[ToolRegistry] = None,  # 新增
    ):
        self.llm_provider = llm_provider
        self.knowledge_service = knowledge_service
        self.max_retries = max_retries

        # Phase 1 组件集成
        self.cost_controller = cost_controller or CostController(max_cost=100000)
        self.tool_registry = tool_registry or ToolRegistry()

        # Phase 2 核心 Agent
        self.planning_agent = PlanningAgent(llm_provider, knowledge_service)
        self.quality_agent = QualityAgent(llm_provider)
        self.summary_agent = SummaryAgent(llm_provider)

    async def execute(
        self,
        user_input: str,
        kb_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """执行任务（增强版）"""

        # 1. 成本检查
        if not self.cost_controller.can_execute(estimated_cost=5000):
            raise ValueError("Token 预算不足")

        # 2. 规划阶段
        plan = await self.planning_agent.plan(user_input, kb_ids)

        # 3. 成本预估
        estimated_tokens = plan.get("total_estimated_tokens", 5000)
        if not self.cost_controller.can_execute(estimated_tokens):
            # 自动降级
            plan = await self._degrade_plan(plan)

        # 4. 执行阶段
        execution_results = await self._execute_tasks(...)

        # 5. 成本记录
        self.cost_controller.record_cost(actual_tokens)

        # 6. 质检和总结
        ...
```

#### Step 4: 保留的基础组件 ✅

**保持不变**：
1. `DecisionTree` - 决策树（可选使用）
2. `AgentChain` - 责任链（可选使用）
3. `CostController` - 成本控制（集成到 Orchestrator）
4. `ToolRegistry` - 工具注册（集成到 Orchestrator）
5. `BaseAgent` - Agent 基类（继续使用）

---

## 最终架构

### 核心层（Core Layer）
```
AgentOrchestrator（核心编排器）
├── PlanningAgent（规划）
├── ExecutionAgent（执行）
│   ├── KnowledgeSearchAgent
│   ├── CodeAnalysisAgent
│   ├── DataProcessingAgent
│   └── DesignAgent
├── QualityAgent（质检）
└── SummaryAgent（总结）
```

### 基础设施层（Infrastructure Layer）
```
├── CostController（成本控制）
├── ToolRegistry（工具注册）
├── DecisionTree（决策树）
├── AgentChain（责任链）
└── AgentFactory（统一工厂）
```

### 数据层（Data Layer）
```
├── AgentExecution（执行记录）
├── AgentExecutionStep（执行步骤）
├── AgentExecutionMetrics（执行指标）
└── AgentKnowledgeUsage（知识使用）
```

---

## 重构清单

### 需要删除 ❌
- [ ] `nodes/root_node.py`
- [ ] `nodes/simple_generator_node.py`
- [ ] `nodes/step1_analyzer_node.py`
- [ ] `nodes/step2_executor_node.py`
- [ ] `nodes/step3_quality_node.py`
- [ ] `nodes/step4_summary_node.py`
- [ ] `nodes/__init__.py`
- [ ] `nodes/` 目录

### 需要重构 🔄
- [ ] `agent_factory.py` - 合并两个工厂
- [ ] `orchestrator.py` - 集成 CostController 和 ToolRegistry
- [ ] `__init__.py` - 更新导出

### 需要保留 ✅
- [x] `decision_tree.py`
- [x] `agent_chain.py`
- [x] `cost_controller.py`
- [x] `tool_registry.py`
- [x] `base_agent.py`
- [x] `agents/planning_agent.py`
- [x] `agents/execution_agent.py`
- [x] `agents/quality_agent.py`
- [x] `agents/summary_agent.py`
- [x] `orchestrator.py`

### 需要新增 ➕
- [ ] 流式输出支持
- [ ] WebSocket 集成
- [ ] 缓存机制
- [ ] 监控告警

---

## 重构后的优势

### 1. 架构统一
- 单一的编排器入口
- 清晰的 Agent 职责划分
- 统一的工厂模式

### 2. 功能完整
- 保留所有有价值的组件
- 集成成本控制和工具注册
- 支持灵活扩展

### 3. 易于维护
- 减少冗余代码
- 清晰的依赖关系
- 完善的文档

### 4. 性能优化
- 成本控制自动降级
- 工具注册即插即用
- 支持并行执行

---

## 下一步行动

### Phase 3 任务
1. **删除节点系统**（1小时）
2. **合并 AgentFactory**（2小时）
3. **增强 AgentOrchestrator**（4小时）
4. **更新测试用例**（2小时）
5. **更新文档**（1小时）

### Phase 4 任务
1. **流式输出**（1天）
2. **WebSocket 集成**（1天）
3. **缓存机制**（1天）
4. **监控告警**（1天）

---

**创建时间**: 2026-04-18  
**版本**: v1.0  
**状态**: 待执行
