# Redis Streams 异步任务流水线 — 面试技术细节

## 一、整体架构

```
API 请求
  ↓ 同步写入DB（状态=PENDING），立即返回
  ↓ XADD 发送消息到 Redis Stream
  ↓ 返回任务ID给前端（<200ms）

Redis Stream
  ↓ xreadgroup 消费（消费者组模式）

StreamWorker（后台常驻进程）
  ↓ 更新状态=PROCESSING
  ↓ 执行实际业务（LLM调用等，耗时10-60秒）
  ↓ 更新状态=COMPLETED/FAILED
  ↓ XACK 确认消息
```

**三个独立 Worker**:
1. `resume-analyze-worker`: 简历分析
2. `interview-evaluate-worker`: 面试评估
3. `knowledge-base-index-worker`: 知识库向量索引

## 二、核心组件

### 2.1 StreamTaskProducer（生产者）

**代码位置**: `app/common/base_async_task.py:15-28`

```python
class StreamTaskProducer:
    def __init__(self, redis_service: RedisService, stream_key: str):
        self._redis = redis_service
        self._stream_key = stream_key

    async def send_task(self, fields: dict[str, str], maxlen: int = 1000) -> None:
        await self._redis.xadd(self._stream_key, fields, maxlen=maxlen)
```

**使用方式**:
```python
# 简历分析
producer = AnalyzeStreamProducer(redis_service)
await producer.send_analyze_task(resume_id)  # XADD resume:analyze:stream resumeId=123
```

### 2.2 StreamWorker（消费者）

**代码位置**: `app/infrastructure/redis/stream_worker.py`

```python
class StreamWorker:
    async def run_forever(self) -> None:
        # 创建消费者组（幂等）
        await self._redis.xgroup_create(self._stream_key, CONSUMER_GROUP, id="0", mkstream=True)

        while not self._stopped:
            # 阻塞读取新消息
            results = await self._redis.xreadgroup(
                CONSUMER_GROUP,
                self._consumer_name,  # 唯一消费者名: {name}-{uuid8}
                {self._stream_key: ">"},  # 只读取新消息
                count=self._read_count,
                block=self._block_ms,  # 5秒阻塞
            )
            for msg_id, fields in results:
                await self._handler(fields)  # 处理消息
                await self._redis.xack(self._stream_key, CONSUMER_GROUP, msg_id)  # 确认
```

### 2.3 StreamTaskHandler（任务处理器基类）

**代码位置**: `app/common/base_async_task.py:31-84`

```python
class StreamTaskHandler(ABC):
    @property
    @abstractmethod
    def field_name(self) -> str:  # 消息主键字段名，如 "resumeId"

    @abstractmethod
    async def process(self, db: AsyncSession, key_value: str) -> None:  # 实际业务逻辑

    @abstractmethod
    async def update_status(self, db, key_value, status, error=None) -> None:  # 更新状态

    async def handle(self, fields: dict[str, str]) -> None:
        async with self._session_factory() as db:
            await self.update_status(db, raw, AsyncTaskStatus.PROCESSING)
            await asyncio.wait_for(self.process(db, raw), timeout=300)  # 5分钟超时
            await self.update_status(db, raw, AsyncTaskStatus.COMPLETED)
            await db.commit()
```

## 三、具体业务实现

### 3.1 简历分析（`resume/async_tasks.py`）

```
XADD resume:analyze:stream resumeId=123
  ↓
ResumeAnalyzeTaskHandler.handle()
  ├─ 更新状态=PROCESSING
  ├─ 调用 ResumeGradingService.analyze_resume()（LLM分析）
  ├─ 保存分析结果到 DB
  └─ 更新状态=COMPLETED
```

### 3.2 面试评估（`interview/async_tasks.py`）

```
XADD interview:evaluate:stream sessionId=abc
  ↓
InterviewEvaluateTaskHandler.handle()
  ├─ 更新状态=PROCESSING
  ├─ 调用 UnifiedEvaluationService.evaluate()（并发批量LLM评估）
  ├─ 保存评估报告到 DB
  └─ 更新状态=COMPLETED
```

### 3.3 知识库索引（`knowledge_base/async_tasks.py`）

```
XADD knowledgebase:index:stream kbId=456
  ↓
KnowledgeBaseIndexTaskHandler.handle()
  ├─ 更新状态=PROCESSING
  ├─ 读取文档文本 → 语义切分 → Embedding → 存入 pgvector
  └─ 更新状态=COMPLETED
```

## 四、关键设计细节

### 4.1 消费者组（Consumer Group）
- 所有 Worker 属于同一个 Consumer Group（`default-workers`）
- 同一 Stream 的消息只会被组内一个消费者处理
- 支持水平扩展：启动多个 Worker 实例自动负载均衡

### 4.2 消息确认（ACK）
- 处理成功后 `XACK`，消息标记为已处理
- 处理失败不 ACK，消息会保留在 pending list
- 但当前没有实现 pending list 重试（消息丢失风险点，可优化）

### 4.3 超时保护
- 每个任务有 5 分钟超时（`TASK_TIMEOUT_SECONDS = 300`）
- 超时后自动回滚事务，更新状态为 FAILED

### 4.4 错误处理
- 任务异常：回滚事务 → 开新连接更新状态为 FAILED + 记录错误信息
- Worker 异常：sleep 3秒后重试（不退出循环）
- Redis 连接超时：sleep 3秒后重试

### 4.5 应用启动
```python
# main.py lifespan
workers = [resume_worker, interview_worker, knowledge_base_worker]
worker_tasks = [asyncio.create_task(w.run_forever()) for w in workers]

yield  # 应用运行中

# 关闭时优雅停止
for worker in workers:
    worker.stop()
for task in worker_tasks:
    task.cancel()
```

## 五、同步 vs 异步对比

| 维度 | 同步处理 | 异步处理（当前方案） |
|------|----------|---------------------|
| 接口响应时间 | 15-60秒 | <200ms |
| 用户体验 | 等待转圈 | 上传即返回，后台处理 |
| 服务重启影响 | 请求丢失 | 消息在 Redis 中持久化 |
| 扩展性 | 单机 | 多 Worker 水平扩展 |

## 六、面试常见追问

**Q: 为什么用 Redis Streams 而不是 Celery/RQ？**
A: 项目已经有 Redis，引入 Streams 不需要额外组件。Redis Streams 的消费者组模式天然支持负载均衡和消息确认，足够满足当前规模。Celery 更重量级（需要 broker + result backend + worker 进程），对于三个简单任务来说 over-engineering。

**Q: Redis Streams 和 Kafka 有什么区别？**
A: Redis Streams 是轻量级的持久化消息队列，适合单机或小规模场景。Kafka 是分布式流处理平台，支持分区、副本、消费者组再平衡等，适合大规模数据管道。当前场景单机 Redis 足够。

**Q: 如果 Worker 挂了，消息会丢失吗？**
A: 不会立即丢失。Redis Streams 的消息会持久化（取决于 AOF/RDB 策略）。消费者组会维护 pending list，未 ACK 的消息可以在 Worker 恢复后通过 `XPENDING` + `XCLAIM` 重新处理。但当前代码没有实现 pending list 重试，这是一个可优化点。

**Q: 为什么用 `xreadgroup` 而不是 `subscribe`？**
A: Redis Pub/Sub 是 fire-and-forget，消息不持久化，订阅者离线时消息丢失。Streams 的消费者组模式支持消息持久化、ACK 确认、pending list 重试，更适合任务队列场景。
