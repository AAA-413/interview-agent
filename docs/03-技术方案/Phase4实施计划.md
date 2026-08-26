# Phase 4 实施计划：高级特性

## 概述

Phase 4 将实现 4 个高级特性，提升系统的生产就绪度和用户体验。

---

## 任务 1：流式输出（1天）

### 目标
实现 LLM 响应的流式输出，提升用户体验，让用户实时看到生成过程。

### 技术方案

#### 1.1 LLM Provider 流式支持

```python
# app/common/ai/llm_provider_protocol.py


class LLMProvider(Protocol):
    """LLM Provider 协议"""

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式调用 LLM

        Yields:
            响应块，包含：
            - delta: 增量内容
            - finish_reason: 结束原因（可选）
        """
        ...
```

#### 1.2 Agent 流式执行

```python
# app/modules/agent_orchestration/orchestrator.py


class AgentOrchestrator:
    async def execute_stream(
        self,
        user_input: str,
        kb_ids: Optional[List[int]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式执行 Agent 编排

        Yields:
            执行事件：
            - type: "plan" | "execute" | "quality" | "summary" | "done"
            - data: 事件数据
        """
        # 1. 规划阶段
        yield {"type": "plan", "data": {"status": "start"}}
        plan = await self.planning_agent.plan(user_input, kb_ids)
        yield {"type": "plan", "data": {"status": "done", "plan": plan}}

        # 2. 执行阶段
        yield {"type": "execute", "data": {"status": "start"}}
        async for result in self._execute_tasks_stream(plan):
            yield {"type": "execute", "data": result}

        # 3. 质检阶段
        yield {"type": "quality", "data": {"status": "start"}}
        quality_check = await self.quality_agent.check(...)
        yield {"type": "quality", "data": quality_check}

        # 4. 总结阶段（流式）
        yield {"type": "summary", "data": {"status": "start"}}
        async for chunk in self._summarize_stream(...):
            yield {"type": "summary", "data": chunk}

        # 5. 完成
        yield {"type": "done", "data": {"status": "success"}}
```

#### 1.3 实现步骤

1. **扩展 LLMProvider**（2小时）
   - 添加 `chat_stream` 方法
   - 实现 LangChain 流式调用

2. **实现 Agent 流式执行**（3小时）
   - `execute_stream` 方法
   - `_execute_tasks_stream` 方法
   - `_summarize_stream` 方法

3. **测试验证**（1小时）
   - 单元测试
   - 集成测试

---

## 任务 2：WebSocket 集成（1天）

### 目标
实现 WebSocket 支持，实现实时双向通信，支持流式输出和进度推送。

### 技术方案

#### 2.1 WebSocket 路由

```python
# app/modules/agent_orchestration/websocket.py

from fastapi import WebSocket, WebSocketDisconnect
import json


class AgentWebSocketManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        """接受连接"""
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        """断开连接"""
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    async def send_message(self, session_id: str, message: dict):
        """发送消息"""
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            await websocket.send_json(message)


# WebSocket 路由
@router.websocket("/ws/agent/{session_id}")
async def agent_websocket(
    websocket: WebSocket,
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Agent 编排 WebSocket 端点"""
    manager = AgentWebSocketManager()
    await manager.connect(session_id, websocket)

    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_json()

            if data["type"] == "execute":
                # 执行 Agent 编排（流式）
                orchestrator = AgentOrchestrator(...)

                async for event in orchestrator.execute_stream(
                    user_input=data["message"],
                    kb_ids=data.get("kb_ids"),
                ):
                    # 推送执行事件
                    await manager.send_message(session_id, event)

            elif data["type"] == "cancel":
                # 取消执行
                await manager.send_message(session_id, {"type": "cancelled", "data": {"message": "任务已取消"}})
                break

    except WebSocketDisconnect:
        manager.disconnect(session_id)
```

#### 2.2 前端集成示例

```typescript
// frontend/src/services/agentWebSocket.ts

class AgentWebSocket {
  private ws: WebSocket | null = null;
  
  connect(sessionId: string, onMessage: (event: any) => void) {
    this.ws = new WebSocket(`ws://localhost:8002/api/agent/ws/${sessionId}`);
    
    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      onMessage(data);
    };
    
    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }
  
  send(message: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }
  
  disconnect() {
    if (this.ws) {
      this.ws.close();
    }
  }
}
```

#### 2.3 实现步骤

1. **WebSocket 管理器**（2小时）
   - 连接管理
   - 消息推送

2. **WebSocket 路由**（2小时）
   - 路由定义
   - 事件处理

3. **前端集成**（2小时）
   - WebSocket 客户端
   - UI 更新

4. **测试验证**（2小时）
   - 连接测试
   - 流式输出测试

---

## 任务 3：缓存机制（1天）

### 目标
实现多层缓存机制，减少 LLM 调用，降低成本，提升响应速度。

### 技术方案

#### 3.1 缓存层次

```
L1: 内存缓存（Redis）
  - 规划结果缓存（相似问题）
  - 执行结果缓存（幂等任务）
  - 质检结果缓存

L2: 数据库缓存
  - 历史执行记录
  - 知识库检索结果
```

#### 3.2 缓存实现

```python
# app/modules/agent_orchestration/cache.py

import hashlib
import json
from typing import Any, Dict, Optional
from redis import asyncio as aioredis


class AgentCache:
    """Agent 缓存管理器"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = aioredis.from_url(redis_url)

    def _generate_key(self, prefix: str, data: Dict[str, Any]) -> str:
        """生成缓存键"""
        content = json.dumps(data, sort_keys=True)
        hash_value = hashlib.md5(content.encode()).hexdigest()
        return f"{prefix}:{hash_value}"

    async def get_plan(self, user_input: str, kb_ids: list) -> Optional[Dict]:
        """获取规划缓存"""
        key = self._generate_key(
            "plan",
            {
                "user_input": user_input,
                "kb_ids": kb_ids,
            },
        )

        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)
        return None

    async def set_plan(
        self,
        user_input: str,
        kb_ids: list,
        plan: Dict,
        ttl: int = 3600,
    ):
        """设置规划缓存"""
        key = self._generate_key(
            "plan",
            {
                "user_input": user_input,
                "kb_ids": kb_ids,
            },
        )

        await self.redis.setex(
            key,
            ttl,
            json.dumps(plan),
        )

    async def get_execution_result(
        self,
        task_id: str,
        task_input: Dict,
    ) -> Optional[Dict]:
        """获取执行结果缓存"""
        key = self._generate_key(
            "execution",
            {
                "task_id": task_id,
                "input": task_input,
            },
        )

        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)
        return None

    async def set_execution_result(
        self,
        task_id: str,
        task_input: Dict,
        result: Dict,
        ttl: int = 7200,
    ):
        """设置执行结果缓存"""
        key = self._generate_key(
            "execution",
            {
                "task_id": task_id,
                "input": task_input,
            },
        )

        await self.redis.setex(
            key,
            ttl,
            json.dumps(result),
        )
```

#### 3.3 集成到 Orchestrator

```python
class AgentOrchestrator:
    
    def __init__(self, ..., cache: Optional[AgentCache] = None):
        self.cache = cache or AgentCache()
    
    async def execute(self, user_input: str, kb_ids: list):
        # 1. 尝试从缓存获取规划
        plan = await self.cache.get_plan(user_input, kb_ids)
        if plan:
            logger.info("📦 使用缓存的规划")
        else:
            plan = await self.planning_agent.plan(user_input, kb_ids)
            await self.cache.set_plan(user_input, kb_ids, plan)
        
        # 2. 执行任务（带缓存）
        for task in plan["subtasks"]:
            result = await self.cache.get_execution_result(
                task["id"],
                task,
            )
            
            if result:
                logger.info(f"📦 使用缓存的执行结果: {task['id']}")
            else:
                result = await self._execute_task(task)
                await self.cache.set_execution_result(
                    task["id"],
                    task,
                    result,
                )
```

#### 3.4 实现步骤

1. **缓存管理器**（2小时）
   - Redis 连接
   - 缓存键生成
   - 缓存读写

2. **集成到 Orchestrator**（2小时）
   - 规划缓存
   - 执行结果缓存

3. **缓存失效策略**（2小时）
   - TTL 设置
   - 手动失效

4. **测试验证**（2小时）
   - 缓存命中测试
   - 性能测试

---

## 任务 4：监控告警（1天）

### 目标
实现完整的监控告警系统，实时追踪系统状态，及时发现问题。

### 技术方案

#### 4.1 监控指标

```python
# app/modules/agent_orchestration/monitoring.py

from prometheus_client import Counter, Histogram, Gauge
import time

# 定义指标
agent_execution_total = Counter(
    "agent_execution_total", "Total number of agent executions", ["status", "execution_path"]
)

agent_execution_duration = Histogram("agent_execution_duration_seconds", "Agent execution duration", ["execution_path"])

agent_cost_total = Counter("agent_cost_total_usd", "Total cost in USD", ["model"])

agent_token_usage = Counter(
    "agent_token_usage_total",
    "Total token usage",
    ["model", "type"],  # type: prompt/completion
)

agent_quality_score = Gauge("agent_quality_score", "Quality check score", ["dimension"])

agent_retry_total = Counter("agent_retry_total", "Total number of retries", ["reason"])


class AgentMonitor:
    """Agent 监控器"""

    def record_execution(
        self,
        status: str,
        execution_path: str,
        duration: float,
    ):
        """记录执行"""
        agent_execution_total.labels(
            status=status,
            execution_path=execution_path,
        ).inc()

        agent_execution_duration.labels(
            execution_path=execution_path,
        ).observe(duration)

    def record_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
    ):
        """记录成本"""
        agent_cost_total.labels(model=model).inc(cost)

        agent_token_usage.labels(
            model=model,
            type="prompt",
        ).inc(prompt_tokens)

        agent_token_usage.labels(
            model=model,
            type="completion",
        ).inc(completion_tokens)

    def record_quality(self, dimensions: Dict[str, float]):
        """记录质量分数"""
        for dimension, score in dimensions.items():
            agent_quality_score.labels(
                dimension=dimension,
            ).set(score)

    def record_retry(self, reason: str):
        """记录重试"""
        agent_retry_total.labels(reason=reason).inc()
```

#### 4.2 告警规则

```yaml
# monitoring/alerts.yml

groups:
  - name: agent_alerts
    interval: 30s
    rules:
      # 执行失败率告警
      - alert: HighExecutionFailureRate
        expr: |
          rate(agent_execution_total{status="failed"}[5m]) 
          / rate(agent_execution_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent 执行失败率过高"
          description: "过去 5 分钟失败率超过 10%"
      
      # 成本告警
      - alert: HighCostUsage
        expr: rate(agent_cost_total_usd[1h]) > 10
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Agent 成本过高"
          description: "每小时成本超过 $10"
      
      # 质量分数告警
      - alert: LowQualityScore
        expr: agent_quality_score < 70
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent 质量分数过低"
          description: "质量分数低于 70 分"
      
      # 重试率告警
      - alert: HighRetryRate
        expr: rate(agent_retry_total[5m]) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent 重试率过高"
          description: "过去 5 分钟重试率过高"
```

#### 4.3 集成到 Orchestrator

```python
class AgentOrchestrator:
    
    def __init__(self, ..., monitor: Optional[AgentMonitor] = None):
        self.monitor = monitor or AgentMonitor()
    
    async def execute(self, user_input: str, kb_ids: list):
        start_time = time.time()
        status = "success"
        
        try:
            # 执行逻辑
            ...
            
            # 记录质量分数
            if quality_check:
                self.monitor.record_quality(quality_check["dimensions"])
            
            # 记录成本
            self.monitor.record_cost(
                model="gpt-4",
                prompt_tokens=...,
                completion_tokens=...,
                cost=...,
            )
            
        except Exception as e:
            status = "failed"
            raise
        
        finally:
            # 记录执行
            duration = time.time() - start_time
            self.monitor.record_execution(
                status=status,
                execution_path=execution_path.name,
                duration=duration,
            )
```

#### 4.4 实现步骤

1. **监控指标定义**（2小时）
   - Prometheus 指标
   - 监控器实现

2. **集成到 Orchestrator**（2小时）
   - 执行监控
   - 成本监控
   - 质量监控

3. **告警规则配置**（2小时）
   - Prometheus 告警
   - 告警通知（邮件/Slack）

4. **监控面板**（2小时）
   - Grafana 面板
   - 可视化图表

---

## 实施时间表

| 任务 | 预计时间 | 优先级 |
|------|---------|--------|
| 流式输出 | 1天 | P0 |
| WebSocket 集成 | 1天 | P0 |
| 缓存机制 | 1天 | P1 |
| 监控告警 | 1天 | P1 |

**总计**: 4天

---

## 依赖和前置条件

### 依赖安装

```bash
# Redis（缓存）
pip install redis

# Prometheus（监控）
pip install prometheus-client

# WebSocket
# FastAPI 已内置支持
```

### 基础设施

1. **Redis 服务**
   ```bash
   docker run -d -p 6379:6379 redis:latest
   ```

2. **Prometheus 服务**
   ```bash
   docker run -d -p 9090:9090 prom/prometheus
   ```

3. **Grafana 服务**
   ```bash
   docker run -d -p 3000:3000 grafana/grafana
   ```

---

## 验收标准

### 流式输出
- [ ] LLM 响应支持流式输出
- [ ] Agent 执行支持流式事件推送
- [ ] 前端能实时显示生成过程

### WebSocket
- [ ] WebSocket 连接稳定
- [ ] 支持双向通信
- [ ] 支持多客户端连接

### 缓存
- [ ] 缓存命中率 > 30%
- [ ] 响应时间降低 > 50%
- [ ] 成本降低 > 30%

### 监控
- [ ] 所有关键指标可监控
- [ ] 告警规则正常触发
- [ ] Grafana 面板完整

---

**创建时间**: 2026-04-18  
**版本**: v1.0  
**状态**: 待执行
