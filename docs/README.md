# 项目文档目录

本目录包含 AI 面试平台的所有技术文档，按照功能和用途分类管理。

## 📁 文档分类

### 01-项目管理
项目管理相关文档，包括项目状态、启动指南等。

- [下次会话快速启动指南.md](./01-项目管理/下次会话快速启动指南.md) - 快速恢复开发环境和上下文
- [当前状态总结.md](./01-项目管理/当前状态总结.md) - 项目当前进度和状态
- [Agent编排框架快速启动指南.md](./01-项目管理/Agent编排框架快速启动指南.md) - Agent 编排框架快速启动和测试指南

### 02-架构设计
系统架构设计文档，包括整体架构、模块设计等。

- [智能Agent编排架构设计.md](./02-架构设计/智能Agent编排架构设计.md) - 智能 Agent 编排系统的完整架构设计

### 03-技术方案
具体技术方案和实现细节文档。

- [上线优化方案与技术选型分析.md](./03-技术方案/上线优化方案与技术选型分析.md) - 上线前的优化方案和技术选型
- [Ragent 知识库优化借鉴方案.md](./03-技术方案/Ragent%20知识库优化借鉴方案.md) - RAG 知识库优化参考方案
- [技术分析优化手册.md](./03-技术方案/技术分析优化手册.md) - 技术分析和优化指南
- [pytest-setup-design.md](./03-技术方案/pytest-setup-design.md) - Pytest 测试框架设计

### 04-问题排查
问题诊断、调试记录和解决方案。

- [async-architecture-debugging-retrospective.md](./04-问题排查/async-architecture-debugging-retrospective.md) - 异步架构调试回顾
- [knowledge-base-phase4-debugging.md](./04-问题排查/knowledge-base-phase4-debugging.md) - 知识库第四阶段调试记录
- [llm-streaming-issue-analysis.md](./04-问题排查/llm-streaming-issue-analysis.md) - LLM 流式输出问题分析

### 05-优化记录
系统优化的实施记录和效果评估。

- [优化实施记录.md](./05-优化记录/优化实施记录.md) - 各项优化措施的实施记录
- [Agent编排框架实现总结.md](./05-优化记录/Agent编排框架实现总结.md) - Agent 编排框架实现过程和架构总结
- [Agent编排框架完整实现总结.md](./05-优化记录/Agent编排框架完整实现总结.md) - Agent 编排框架完整实现详细说明（包含数据库、API、测试）
- [Agent编排框架Phase2实现总结.md](./05-优化记录/Agent编排框架Phase2实现总结.md) - Phase 2 核心 Agent 实现总结

### claude_code_aengt
Claude Code Agent 相关技术文档（保持原有结构）。

- [claude-code-summary.md](./claude_code_aengt/claude-code-summary.md) - Claude Code 总结
- [s01-the-agent-loop.md](./claude_code_aengt/s01-the-agent-loop.md) - Agent 循环机制
- [s02-tool-use.md](./claude_code_aengt/s02-tool-use.md) - 工具使用
- [s03-todo-write.md](./claude_code_aengt/s03-todo-write.md) - Todo 写入
- [s04-subagent.md](./claude_code_aengt/s04-subagent.md) - 子 Agent
- [s05-skill-loading.md](./claude_code_aengt/s05-skill-loading.md) - 技能加载
- [s06-context-compact.md](./claude_code_aengt/s06-context-compact.md) - 上下文压缩
- [s07-task-system.md](./claude_code_aengt/s07-task-system.md) - 任务系统
- [s08-background-tasks.md](./claude_code_aengt/s08-background-tasks.md) - 后台任务
- [s09-agent-teams.md](./claude_code_aengt/s09-agent-teams.md) - Agent 团队
- [s10-team-protocols.md](./claude_code_aengt/s10-team-protocols.md) - 团队协议
- [s11-autonomous-agents.md](./claude_code_aengt/s11-autonomous-agents.md) - 自主 Agent
- [s12-worktree-task-isolation.md](./claude_code_aengt/s12-worktree-task-isolation.md) - 工作树任务隔离

### onboarding
项目入门和结构分析文档（保持原有结构）。

- [python-project-structure-analysis.md](./onboarding/python-project-structure-analysis.md) - Python 项目结构分析

## 📝 文档命名规范

- 使用中文或英文命名，保持一致性
- 使用连字符 `-` 分隔单词（英文文档）
- 文件名应清晰表达文档内容
- 避免使用特殊字符

## 🔄 文档更新流程

1. 新建文档时，根据内容选择合适的分类目录
2. 更新文档后，在文档末尾注明更新时间和版本
3. 重要变更需要在本 README 中更新说明
4. 定期清理过时文档，移至 `archive/` 目录

## 📌 快速导航

### 新人入门
1. [Python 项目结构分析](./onboarding/python-project-structure-analysis.md)
2. [下次会话快速启动指南](./01-项目管理/下次会话快速启动指南.md)
3. [当前状态总结](./01-项目管理/当前状态总结.md)

### 架构理解
1. [智能Agent编排架构设计](./02-架构设计/智能Agent编排架构设计.md)
2. [上线优化方案与技术选型分析](./03-技术方案/上线优化方案与技术选型分析.md)

### Agent 编排框架（最新）
1. [Agent编排框架快速启动指南](./01-项目管理/Agent编排框架快速启动指南.md) - 快速开始使用
2. [Agent编排框架实现总结](./05-优化记录/Agent编排框架实现总结.md) - 实现过程总结
3. [Agent编排框架完整实现总结](./05-优化记录/Agent编排框架完整实现总结.md) - 完整实现详情

### 问题排查
1. [异步架构调试回顾](./04-问题排查/async-architecture-debugging-retrospective.md)
2. [LLM 流式输出问题分析](./04-问题排查/llm-streaming-issue-analysis.md)

---

**最后更新**：2026-04-18  
**维护者**：开发团队
