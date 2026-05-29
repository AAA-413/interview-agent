# JD 结构化与面试策略生成方案

文档日期：2026-05-28

## 1. 核心观点

用户自己填写 JD 后，系统不能只把 JD 原文塞进 prompt。

JD 应该是面试策略输入，影响：

```text
1. Topic 权重
2. 题型配比
3. 追问方向
4. 训练任务优先级
5. 报告风险解释
```

一句话：

```text
JD 不是 prompt 附件，而是面试策略配置。
```

## 2. 为什么不能只塞进 prompt

如果只把 JD 原文拼进 prompt，会有这些问题：

- LLM 是否真的按 JD 调整题目不可控。
- 不同生成轮次对 JD 关注程度不稳定。
- 无法解释某个 topic 为什么被优先问。
- 训练任务无法稳定按 JD 相关性排序。
- 无法对低质量 JD 降权。

因此需要先将 JD 结构化，再进入后续策略服务。

## 3. JD 结构化对象

建议结构：

```json
{
  "raw_jd": "...",
  "quality_score": 78,
  "role_title": "AI Agent 开发实习生",
  "role_domain": "ai_agent",
  "seniority": "intern",
  "required_skills": ["Python", "FastAPI", "RAG", "MCP", "Agent", "Prompt"],
  "preferred_skills": ["LangChain", "多 Agent", "评估体系"],
  "responsibilities": ["参与 AI Agent 应用开发", "构建知识库", "优化检索效果"],
  "domain_keywords": ["LLM", "RAG", "工具调用", "向量检索"],
  "topic_weights": {
    "rag_multi_channel_retrieval": 0.95,
    "mcp_tool_integration": 0.9,
    "agent_planning_execution": 0.88,
    "java_thread_pool_tuning": 0.35
  },
  "question_type_mix": {
    "project": 0.5,
    "knowledge": 0.25,
    "system_design": 0.25
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `quality_score` | JD 质量分，决定 JD 权重 |
| `role_domain` | 岗位方向，用于加载 topic pack |
| `seniority` | 实习、校招、初级、中级等 |
| `required_skills` | 必须技能 |
| `preferred_skills` | 加分技能 |
| `responsibilities` | 岗位职责 |
| `topic_weights` | JD 对各 topic 的重要性 |
| `question_type_mix` | 推荐题型配比 |

## 4. JD 质量评分

用户可能输入很完整的 JD，也可能只写一句：

```text
招聘 Java 开发，要求熟悉相关技术，有责任心。
```

因此需要 `jd_quality_score`。

评分维度：

```text
role_clarity: 是否有明确岗位名
skill_specificity: 技能要求是否具体
responsibility_clarity: 工作职责是否清楚
seniority_signal: 是否能判断候选人等级
domain_signal: 是否能判断岗位方向
```

建议输出：

```json
{
  "quality_score": 42,
  "quality_level": "LOW",
  "missing_parts": ["缺少具体技术栈", "缺少岗位职责", "无法判断等级"],
  "user_suggestion": "建议补充框架、数据库、中间件、项目职责或岗位级别。"
}
```

策略：

- 高质量 JD：提高 JD 在策略中的权重。
- 中质量 JD：JD、skill_id、简历技术栈综合判断。
- 低质量 JD：降低 JD 权重，更多依赖岗位方向和简历技术栈。

## 5. JD 到 Topic 权重

JD 结构化后，需要映射到 Topic Registry。

流程：

```text
JD required_skills / responsibilities / domain_keywords
  -> 召回 topic pack
  -> 计算 topic_weight
  -> 进入 InterviewPlanService
```

示例：

用户简历包含：

```text
Java 后端
商城秒杀
AI Agent
RAG
MCP
```

JD 是 AI Agent 岗，则权重：

```text
rag_multi_channel_retrieval: high
mcp_tool_integration: high
agent_planning_execution: high
fastapi_request_lifecycle: medium
java_thread_pool_tuning: low/medium
```

说明：

- JD 强相关 topic 优先问。
- 简历有但 JD 弱相关 topic 可以问，但降权。
- JD 有但简历没有的 topic，不能问成候选人做过。

## 6. JD 与简历证据的交叉规则

最重要的边界：

```text
JD 相关不代表可以把题目写成候选人做过。
```

规则：

| 情况 | 题型策略 | 示例 |
| --- | --- | --- |
| JD 有，简历有 | `PROJECT` 优先 | “你简历里提到 MCP 工具集成...” |
| JD 有，简历没有 | `KNOWLEDGE` 或 `SYSTEM_DESIGN` | “如果让你接入 MCP 工具服务，你会怎么设计？” |
| JD 没有，简历有 | 降权，可作为项目真实性补充 | “你简历里提到商城秒杀...” |
| JD 没有，简历也没有 | 默认不问，除非是基础能力 | 不主动问边缘内容 |

错误问法：

```text
你在项目中是怎么实现 MCP 的？
```

如果简历没写 MCP，这就是错误的项目题。

正确问法：

```text
这个岗位要求 MCP，如果让你接入一个 MCP 工具服务，你会怎么设计？
```

## 7. JD 影响题型配比

不同岗位方向的题型配比不同。

建议默认：

| 岗位方向 | project | knowledge | system_design |
| --- | ---: | ---: | ---: |
| AI Agent / LLM 应用 | 50% | 25% | 25% |
| Java 后端 | 45% | 35% | 20% |
| Python 后端 | 45% | 30% | 25% |
| 前端开发 | 50% | 30% | 20% |
| LLM 微调 / 强化学习 | 40% | 40% | 20% |

等级修正：

```text
intern / junior: 降低 system_design，提高 knowledge 和 project 表达
mid: 保持默认
senior: 提高 system_design 和 tradeoff 类 topic
```

第一版可以固定：

```text
教练模式 4 topic:
  2 project
  1 knowledge
  1 system_design

严厉模式 5 topic:
  3 project
  1 knowledge
  1 system_design
```

然后用 JD 权重决定具体 topic。

## 8. JD 影响追问方向

同一个 topic，在不同 JD 下追问方向不同。

示例：同样是 RAG 项目。

JD 强调工程落地：

```text
你们是怎么做接口、异步任务、SSE 输出和异常处理的？
```

JD 强调检索效果：

```text
你们怎么评估召回准确率？Query Rewrite 具体提升在哪？
```

JD 强调成本控制：

```text
Embedding、重排和 LLM 调用成本怎么控制？
```

因此 `followup_goals` 应包含 JD 相关追问目标：

```json
{
  "topic_key": "rag_multi_channel_retrieval",
  "jd_focus": ["检索效果评估", "成本控制"],
  "followup_goals": [
    "验证召回指标口径",
    "验证 Query Rewrite 的效果证明",
    "验证重排和 LLM 调用成本控制"
  ]
}
```

## 9. JD 影响训练任务优先级

训练任务优先级公式中应包含 `jd_relevance`：

```text
priority_score =
  weakness_severity * 0.30
+ jd_relevance * 0.25
+ resume_core_project * 0.20
+ repeat_failure * 0.15
+ low_improvement * 0.10
```

示例：

```text
RAG topic 得 72，但 JD 高相关 -> 高优先级
Java 集合 topic 得 60，但 JD 弱相关 -> 中优先级
```

这样训练计划不会被边缘低分知识点干扰。

## 10. 服务拆分建议

```text
JDParseService
  负责解析 JD，输出结构化对象和质量分。

RoleDomainService
  负责识别岗位方向和候选人等级。

TopicWeightService
  负责将 JD 映射到 topic_weights。

QuestionTypeMixService
  负责根据岗位方向、等级和模式生成题型配比。

InterviewPlanService
  消费 topic_weights 和 question_type_mix，生成面试计划。

TrainingTaskPrioritizer
  消费 jd_relevance，排序训练任务。
```

## 11. 缓存策略

JD 结构化结果应缓存。

建议缓存 key：

```text
user_id + jd_hash + target_role + skill_id
```

缓存内容：

```text
structured_jd
topic_weights
question_type_mix
quality_score
```

原因：

- 避免每次创建面试都重新解析 JD。
- 让同一个 JD 下的多次面试策略更稳定。
- 便于复盘 topic 权重来源。

## 12. API 草案

### 12.1 解析 JD

```http
POST /api/interview/jd/parse
```

请求：

```json
{
  "target_role": "AI Agent 开发实习生",
  "skill_id": "ai-agent",
  "jd_text": "..."
}
```

响应：

```json
{
  "quality_score": 78,
  "role_domain": "ai_agent",
  "seniority": "intern",
  "required_skills": [],
  "preferred_skills": [],
  "responsibilities": [],
  "topic_weights": {},
  "question_type_mix": {}
}
```

### 12.2 创建动态面试时复用

```http
POST /api/interview/dynamic-sessions
```

请求中包含：

```json
{
  "resume_id": 16,
  "target_role": "AI Agent 开发实习生",
  "jd_text": "...",
  "structured_jd_id": "optional_cached_id",
  "mode": "COACH"
}
```

后端优先使用缓存的结构化 JD；若无缓存，则同步或异步解析。

## 13. 质量基准

JD 策略需要单独验证：

- JD 高相关 topic 是否被优先选择。
- JD 有但简历没有的内容是否被问成 `KNOWLEDGE/SYSTEM_DESIGN`，而不是 `PROJECT`。
- JD 质量低时是否降低 JD 权重。
- 同一简历配不同 JD 时，topic 选择和追问方向是否明显不同。
- 训练任务是否按 JD 相关性排序，而不是只按最低分排序。

## 14. 第一版实施建议

第一版：

1. 增加 `StructuredJD` DTO。
2. 用 LLM 做 JD 结构化解析。
3. 用规则将 JD 技能和职责映射到 Topic Registry。
4. 生成 `topic_weights` 和 `question_type_mix`。
5. 在动态面试计划生成时使用 topic 权重。
6. 在训练任务排序时使用 `jd_relevance`。

第二版：

1. 增加 JD 质量评分提示。
2. 缓存结构化 JD。
3. 引入 embedding 辅助 JD-topic 匹配。
4. 支持多个 JD 对比，帮助用户选择训练方向。

