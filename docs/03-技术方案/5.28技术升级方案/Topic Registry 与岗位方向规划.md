# Topic Registry 与岗位方向规划

文档日期：2026-05-28

## 1. 背景

动态面试官需要稳定的 `topic_key`，用于：

- 题目分类。
- topic 去重。
- 趋势统计。
- 个人训练计划。
- 同题再练。
- 质量基准。

但 `topic_key` 不能完全交给 LLM 自由生成，否则会出现同义主题分裂、跨岗位误匹配和统计失真。

因此需要后端维护受控 Topic Registry，并根据岗位方向加载对应 topic pack。

## 2. 服务目标

第一阶段服务目标不是“所有岗位”，而是：

```text
技术开发岗 + AI 方向增强
```

重点覆盖：

- 前端开发。
- 后端开发。
- Java 后端。
- Python 后端。
- AI Agent 应用开发。
- LLM 应用开发。
- LLM 微调与强化学习基础。

暂不优先覆盖：

- 纯算法岗。
- 测试岗。
- 运维/SRE 专项。
- 安全岗。
- 数据分析/BI。
- 产品/运营岗位。
- 企业招聘官侧。

## 3. 分层 Topic Registry

不使用“一套全局扁平 topic 覆盖所有岗位”，而是采用分层 topic pack：

```text
common_engineering
frontend
backend_common
java_backend
python_backend
database_cache_mq
ai_agent
llm_application
llm_finetuning_rl
system_design
fallback
```

创建面试时，根据 `skill_id + JD + 简历技术栈 + 用户目标岗位` 选择若干 pack：

```text
前端开发:
  common_engineering + frontend + backend_common + system_design

Java 后端:
  common_engineering + backend_common + java_backend + database_cache_mq + system_design

Python 后端:
  common_engineering + backend_common + python_backend + database_cache_mq + system_design

AI Agent / LLM 应用:
  common_engineering + backend_common + python_backend + ai_agent + llm_application + database_cache_mq + system_design

LLM 微调/强化学习:
  common_engineering + python_backend + llm_application + llm_finetuning_rl + system_design
```

## 4. Topic 定义格式

建议第一版用代码或 YAML/JSON 配置维护。

示例：

```json
{
  "topic_key": "rag_multi_channel_retrieval",
  "label": "RAG 多通道检索",
  "pack": "llm_application",
  "skill_key": "rag",
  "description": "围绕向量召回、关键词召回、混合检索、重排序和召回评估的能力主题。",
  "aliases": ["RAG", "多通道检索", "多路召回", "BM25", "向量检索", "Cross-Encoder", "重排序", "Query Rewrite"],
  "supported_question_types": ["PROJECT", "KNOWLEDGE", "SYSTEM_DESIGN"]
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `topic_key` | 稳定内部 key，用于统计和去重 |
| `label` | 中文展示名 |
| `pack` | 所属 topic pack |
| `skill_key` | 能力维度 key |
| `description` | 主题解释，可用于 embedding |
| `aliases` | 规则召回关键词 |
| `supported_question_types` | 支持的题型 |

## 5. 第一版 Topic Pack 草案

### 5.1 common_engineering

| topic_key | label |
| --- | --- |
| `project_metric_validation` | 项目指标与效果验证 |
| `project_role_ownership` | 项目职责与个人贡献 |
| `technical_tradeoff_analysis` | 技术取舍分析 |
| `production_incident_troubleshooting` | 线上问题排查 |
| `testing_quality_assurance` | 测试与质量保障 |
| `deployment_release_process` | 部署与发布流程 |
| `logging_observability` | 日志与可观测性 |
| `performance_optimization` | 性能优化 |
| `security_basic_awareness` | 基础安全意识 |
| `team_collaboration_communication` | 协作与沟通 |

### 5.2 frontend

| topic_key | label |
| --- | --- |
| `frontend_component_design` | 前端组件设计 |
| `react_state_management` | React 状态管理 |
| `vue_state_management` | Vue 状态管理 |
| `frontend_routing_permission` | 前端路由与权限 |
| `frontend_performance_optimization` | 前端性能优化 |
| `browser_rendering_event_loop` | 浏览器渲染与事件循环 |
| `frontend_network_error_handling` | 前端网络与异常处理 |
| `typescript_type_design` | TypeScript 类型设计 |
| `frontend_build_engineering` | 前端工程化构建 |
| `frontend_form_validation` | 表单与校验 |
| `frontend_ui_state_consistency` | UI 状态一致性 |
| `frontend_accessibility_basic` | 前端可访问性基础 |

### 5.3 backend_common

| topic_key | label |
| --- | --- |
| `api_design_contract` | API 设计与契约 |
| `auth_permission_control` | 认证与权限控制 |
| `async_task_pipeline` | 异步任务流水线 |
| `concurrency_control` | 并发控制 |
| `idempotency_design` | 幂等设计 |
| `rate_limit_degradation` | 限流与降级 |
| `backend_error_handling` | 后端异常处理 |
| `file_upload_storage` | 文件上传与存储 |
| `background_job_reliability` | 后台任务可靠性 |
| `api_pagination_filtering` | 分页、过滤与查询 |

### 5.4 java_backend

| topic_key | label |
| --- | --- |
| `spring_ioc_aop` | Spring IOC 与 AOP |
| `spring_transaction_management` | Spring 事务管理 |
| `spring_mvc_request_lifecycle` | Spring MVC 请求链路 |
| `mybatis_sql_mapping` | MyBatis 与 SQL 映射 |
| `jvm_memory_gc` | JVM 内存与 GC |
| `java_thread_pool_tuning` | Java 线程池调优 |
| `java_concurrent_collections` | Java 并发集合 |
| `distributed_lock_java` | 分布式锁 |
| `spring_boot_configuration` | Spring Boot 配置管理 |
| `java_exception_design` | Java 异常设计 |
| `spring_ai_integration` | Spring AI 集成 |

### 5.5 python_backend

| topic_key | label |
| --- | --- |
| `fastapi_request_lifecycle` | FastAPI 请求链路 |
| `python_asyncio_concurrency` | Python asyncio 并发 |
| `sqlalchemy_async_session` | SQLAlchemy 异步会话 |
| `python_dependency_management` | Python 依赖管理 |
| `python_project_structure` | Python 工程结构 |
| `python_background_tasks` | Python 后台任务 |
| `pydantic_data_validation` | Pydantic 数据校验 |
| `python_exception_handling` | Python 异常处理 |
| `python_testing_pytest` | Pytest 测试 |
| `python_performance_profiling` | Python 性能分析 |

### 5.6 database_cache_mq

| topic_key | label |
| --- | --- |
| `mysql_index_optimization` | MySQL 索引优化 |
| `mysql_transaction_isolation` | MySQL 事务隔离 |
| `sql_query_optimization` | SQL 查询优化 |
| `redis_cache_consistency` | Redis 缓存一致性 |
| `redis_cache_penetration_hotkey` | 缓存穿透与热点 Key |
| `redis_distributed_lock` | Redis 分布式锁 |
| `redis_streams_queue` | Redis Streams 队列 |
| `message_queue_reliability` | 消息队列可靠性 |
| `database_schema_design` | 数据库表结构设计 |
| `pgvector_vector_storage` | pgvector 向量存储 |

### 5.7 ai_agent

| topic_key | label |
| --- | --- |
| `agent_planning_execution` | Agent 规划与执行 |
| `multi_agent_collaboration` | 多 Agent 协作 |
| `agent_memory_context` | Agent 记忆与上下文 |
| `agent_tool_selection` | Agent 工具选择 |
| `mcp_tool_integration` | MCP 工具集成 |
| `agent_quality_evaluation` | Agent 质量评估 |
| `agent_failure_recovery` | Agent 失败恢复 |
| `agent_state_management` | Agent 状态管理 |
| `react_agent_reasoning` | ReAct 推理范式 |
| `plan_execute_agent_pattern` | Plan-and-Execute 模式 |

### 5.8 llm_application

| topic_key | label |
| --- | --- |
| `rag_multi_channel_retrieval` | RAG 多通道检索 |
| `embedding_vector_search` | Embedding 与向量检索 |
| `reranking_cross_encoder` | Cross-Encoder 重排序 |
| `query_rewrite_strategy` | 查询改写策略 |
| `prompt_engineering` | Prompt 工程 |
| `function_calling_tool_calling` | Function Calling 与工具调用 |
| `llm_context_cost_control` | 上下文与成本控制 |
| `llm_output_structuring` | LLM 结构化输出 |
| `llm_evaluation_metrics` | LLM 应用评估指标 |
| `streaming_response_sse` | 流式输出与 SSE |
| `knowledge_base_chunking` | 知识库切分策略 |
| `rag_permission_filtering` | RAG 权限过滤 |

### 5.9 llm_finetuning_rl

| topic_key | label |
| --- | --- |
| `sft_data_preparation` | SFT 数据构造 |
| `lora_qlora_finetuning` | LoRA/QLoRA 微调 |
| `instruction_tuning_basics` | 指令微调基础 |
| `dpo_preference_optimization` | DPO 偏好优化 |
| `rlhf_pipeline_basics` | RLHF 流程基础 |
| `ppo_rl_training_basics` | PPO 强化学习训练基础 |
| `reward_modeling_basics` | 奖励模型基础 |
| `finetuning_evaluation` | 微调效果评估 |
| `dataset_quality_filtering` | 数据质量过滤 |
| `model_overfitting_and_generalization` | 过拟合与泛化 |

### 5.10 system_design

| topic_key | label |
| --- | --- |
| `high_concurrency_design` | 高并发系统设计 |
| `scalability_design` | 可扩展性设计 |
| `availability_fault_tolerance` | 高可用与容错 |
| `data_consistency_design` | 数据一致性设计 |
| `distributed_system_tradeoffs` | 分布式系统取舍 |
| `observability_design` | 可观测性设计 |
| `cost_latency_tradeoff` | 成本与延迟取舍 |
| `system_capacity_estimation` | 容量评估 |
| `security_permission_design` | 安全与权限设计 |
| `workflow_orchestration_design` | 工作流编排设计 |

### 5.11 fallback

| topic_key | label |
| --- | --- |
| `custom_project_topic` | 自定义项目主题 |
| `other_project_experience` | 其他项目经历 |
| `other_knowledge` | 其他知识点 |
| `other_system_design` | 其他系统设计 |
| `uncertain_topic` | 不确定主题 |

## 6. 映射流程

推荐流程：

```text
1. 识别岗位方向
   skill_id + JD + 简历技术栈 + target_role -> role_domain

2. 加载 topic packs
   common_engineering + role_domain packs + resume_detected_skill packs

3. LLM 输出候选主题
   raw_topic + evidence_snippet + question_type + keywords

4. 后端规范化
   alias 规则召回候选
   + embedding 相似度排序
   + pack 匹配校正
   + question_type 匹配校正

5. 置信度判断
   高置信直接映射
   中置信可让 LLM 在 top3 中裁决
   低置信 fallback
```

## 7. 置信度计算

不要直接使用 LLM 自报的 `confidence`。最终置信度由后端计算。

第一版建议：

```text
confidence =
  alias_score * 0.35
+ embedding_score * 0.35
+ pack_match_score * 0.15
+ question_type_match_score * 0.10
+ llm_vote_score * 0.05
```

其中：

- `alias_score`：关键词、别名命中程度。
- `embedding_score`：候选主题和受控 topic 描述的向量相似度。
- `pack_match_score`：候选 topic 是否属于当前加载的岗位方向 pack。
- `question_type_match_score`：题型是否被该 topic 支持。
- `llm_vote_score`：可选，仅在中置信时让 LLM 从 top3 裁决。

阈值：

```text
>= 0.80: 高置信，直接使用标准 topic_key
0.60 - 0.80: 中置信，可触发 LLM top3 裁决
< 0.60: 低置信，fallback
```

第一版可以先不用 `llm_vote_score`，采用：

```text
alias_score + embedding_score + pack_match_score + question_type_match_score
```

如果错配较多，再补 LLM vote。

## 8. Fallback 策略

宁可不匹配，也不要错匹配。

低置信时：

- 项目题：`custom_project_topic` 或 `other_project_experience`
- 知识题：`other_knowledge`
- 系统设计题：`other_system_design`
- 信息不足：`uncertain_topic`

fallback topic 仍然需要保存：

- `raw_topic`
- `raw_keywords`
- `evidence_snippet`
- `normalization_confidence`
- `fallback_reason`

这些数据可以后续帮助扩充 Topic Registry。

## 9. 速度评估

Topic 映射不会成为主要性能瓶颈。

原因：

- Topic Registry 第一版规模约 100-150 个 topic。
- topic embedding 可预先计算。
- 运行时只需要对 LLM 候选主题和 evidence 做少量 embedding。
- 规则召回和向量相似度都很快。
- LLM 裁决只在中置信时触发。

预期耗时：

```text
规则匹配: 毫秒级
本地向量相似度: 毫秒级到几十毫秒
embedding API: 约 100ms - 几百 ms，可批量和缓存
LLM top3 裁决: 最慢，应作为少数情况兜底
```

真正耗时的仍然是题目生成和回答评估。

## 10. 实施建议

第一版：

1. 用代码或 YAML 定义 Topic Registry。
2. 先覆盖本文列出的 10 个 topic pack。
3. 实现 alias 规则召回。
4. 预留 embedding 相似度接口，但可先用简单文本匹配跑通。
5. 保存 `normalization_confidence` 和 `fallback_reason`。
6. 低置信不强行映射。

第二版：

1. 给所有 topic 描述生成 embedding。
2. 引入候选主题向量相似度。
3. 对中置信样本启用 LLM top3 裁决。
4. 基于 fallback 日志扩充 Topic Registry。

第三版：

1. 按真实用户表现优化 topic pack。
2. 为不同岗位维护不同默认权重。
3. 将 topic profile 接入个人训练计划。

