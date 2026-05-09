# 智能下载优化 TODO

## 问题清单

### BUG-1: 质量评分始终显示 0%

**现象**: 前端质量评分一直显示 0%，即使下载完成。

**根因分析**:
- 后端在 `quality_check` 阶段设置 `progress.quality_score = quality_result["score"] / 100.0`
- 但 quality_check 状态只持续 1-2 秒（1次轮询窗口），之后状态变为 `summarizing`
- 前端 `quality_score` 显示逻辑没有绑定状态，但可能在 quality_check 之前就已经是 undefined/null
- 另一种可能：初始 `DownloadProgress` 的 `quality_score` 为 `None`，序列化为 JSON `null`，前端判断 `!== undefined` 通过但值为 null → `(null * 100).toFixed(0)` = "0"

**修复方案**:
- [ ] 后端：`DownloadProgress` 初始化时 `quality_score` 设为 `None`（当前已是），确保 quality_check 后正确赋值
- [ ] 前端：修改显示条件为 `{progress.quality_score != null && progress.quality_score > 0 && (...)}`
- [ ] 验证：添加后端日志确认 `quality_score` 值在各阶段的变化

**相关文件**:
- 后端: `app/modules/agent_orchestration/smart_download_router.py:592`
- 前端: `frontend/src/pages/SmartDownloadPage.tsx:408-411`

---

### BUG-2: 复杂任务总是重试 3 次

**现象**: 智能下载复杂任务时，重试次数总是达到最大值 3 次。

**根因分析**:
- 重试条件: `retry < max_retries - 1 and quality_result.get("failed_task_indices")`
- 如果每次重试后同样的任务仍然失败，会一直重试到 max_retries
- 可能原因：
  1. 搜索结果本身就差（网络问题、搜索词不佳），重试也拿不到好内容
  2. Phase A 的阈值对某些场景过严（substance ≥ 40, relevance ≥ 30）
  3. expanded_keywords 没有正确传递到重试轮（已修复，待验证）
  4. 动态扩展任务（GitHub 搜索生成的子任务）在重试时索引映射错误

**修复方案**:
- [ ] 添加后端日志：每轮重试打印 `failed_task_indices` 和每个失败任务的 `reason`，定位具体失败原因
- [ ] 如果是搜索结果差：考虑在重试时调整搜索策略（换关键词），而不是简单重试
- [ ] 如果是阈值问题：根据实际数据微调 substance/relevance 阈值
- [ ] 验证 expanded_keywords 在重试轮是否正确传递和生效

**相关文件**:
- 后端: `app/modules/agent_orchestration/smart_download_router.py:438-613`
- 后端: `app/modules/agent_orchestration/agents/quality_agent.py` (Phase A 逻辑)

---

### FEAT-1: 重新下载任务需要标记区分

**现象**: 下载任务列表中，重新下载的任务和初始下载的任务外观一致，用户无法区分。

**当前状态**: `downloaded_files` 结构为 `{step_id, description, size}`，没有状态字段。

**修复方案**:
- [ ] 后端：`downloaded_files` 新增 `status` 字段（`"success"` / `"retrying"` / `"failed"`）
- [ ] 后端：重试时将对应任务的 status 更新为 `"retrying"`，成功后改为 `"success"`
- [ ] 前端：任务列表根据 status 显示不同样式：
  - `success`: 绿色勾 ✓
  - `retrying`: 橙色旋转动画 + "重试中"标签
  - `failed`: 红色叉 ✗ + 失败原因
- [ ] 前端：新增任务（动态扩展的 GitHub 子任务）标记 "新增" 标签

**相关文件**:
- 后端: `app/modules/agent_orchestration/smart_download_router.py` (downloaded_files 构建逻辑)
- 前端: `frontend/src/pages/SmartDownloadPage.tsx:415-451` (任务列表渲染)
- 前端: `frontend/src/api/smartDownload.ts:42-46` (DownloadProgress 类型)

---

### FEAT-2: 质检阶段信息展示增强（可选）

**现象**: 质检阶段只显示一个进度条，用户不知道在检查什么。

**修复方案**:
- [ ] 后端：`DownloadProgress` 新增 `quality_details` 字段，包含：
  - `passed_count`: 通过的任务数
  - `failed_count`: 失败的任务数
  - `phase`: "phase_a" / "phase_b"
- [ ] 前端：质检阶段显示 "正在检查 3/10 个任务..." 等动态信息

**相关文件**:
- 后端: `app/modules/agent_orchestration/smart_download_router.py:69-83`
- 前端: `frontend/src/pages/SmartDownloadPage.tsx:453-464`

---

## 优先级

| 编号 | 优先级 | 预估工作量 | 说明 |
|------|--------|-----------|------|
| BUG-1 | P0 | 小 | 质量评分显示问题，影响用户体验 |
| BUG-2 | P0 | 中 | 重试3次浪费时间，需要定位根因 |
| FEAT-1 | P1 | 中 | 任务状态区分，提升可观测性 |
| FEAT-2 | P2 | 小 | 锦上添花，可后续做 |

## 实施顺序

1. **BUG-1** — 先修复质量评分显示（前端条件判断 + 后端日志验证）
2. **BUG-2** — 添加诊断日志，定位重试根因，再决定修复方案
3. **FEAT-1** — 后端 downloaded_files 新增 status 字段 + 前端样式区分
4. **FEAT-2** — 可选，视情况决定是否做
