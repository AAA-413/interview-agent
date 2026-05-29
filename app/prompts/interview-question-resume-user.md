# Input Data
请生成共 {{ questionCount }} 个针对项目经历的面试主问题。

## 面试方向
{{ skillName }}（{{ skillDescription }}）

## 难度级别
{{ difficultyDescription }}

## 候选人简历
---简历内容开始---
{{ resumeText }}
---简历内容结束---

## 职位描述
{{ jdSection }}

## 已考知识点（避免重复）
{{ historicalSection }}

## 输出要求
- questions 数组必须包含恰好 {{ questionCount }} 个元素，不多不少
- 如果提供了 JD，请优先选择与 JD 岗位要求最相关的简历经历和技术栈提问；JD 只用于选择追问重点，禁止编造简历中不存在的项目、技术栈或工作经历
- 每个主问题必须包含 topicSummary 字段：10 字以内的知识点摘要（用于历史去重），格式示例：
  - "Redis 缓存策略设计"
  - "MySQL 索引优化"
  - "Kafka 异步消息解耦"
