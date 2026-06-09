# Input Data
请生成共 {{ questionCount }} 个主问题。

## 难度级别
{{ difficultyDescription }}

## 面试方向
{{ skillName }}（{{ skillDescription }}）

## 问题分布要求
| 方向 | 数量 | 说明 |
|------|------|------|
{{ allocationTable }}

## 已考知识点（避免重复）
{{ historicalSection }}

## 本轮换题策略
{{ variationSection }}

## 参考题库（references）
{{ referenceSection }}

## 职位描述
{{ jdSection }}

## 输出要求
- questions 数组必须包含恰好 {{ questionCount }} 个元素，不多不少
- 禁止复用“最近原题”，也不要只改几个词后生成近似问题
- 如需考同一技术点，必须换成不同场景、不同约束或不同追问目标
- 每个主问题必须包含 topicSummary 字段：10 字以内的知识点摘要（用于历史去重），格式示例：
  - "Redis RDB/AOF 持久化对比"
  - "MySQL 索引失效场景"
  - "HashMap 扩容机制"
  - "TCP 三次握手流程"
