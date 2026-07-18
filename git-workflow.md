# Plexus Git 工作流规范

> 适用于 Plexus Agent OS 全部子项目：plexus-core、plexus-im、plexus-server、plexus-web、plexus-admin、plexus-mcp-server

---

## 一、仓库初始化

### 1.1 首次提交

每个子项目在完成初始开发后，执行首次提交：

```bash
cd plexus-core   # 或其他子项目
git init
git add .
git commit -m "feat: 初始化项目骨架"
```

### 1.2 关联远程仓库

```bash
git remote add origin git@github.com:<org>/plexus-core.git
git push -u origin master
```

---

## 二、分支策略

采用 **Git Flow 简化版**，适合多服务并行开发的团队。

### 2.1 分支类型

| 分支类型 | 命名格式 | 生命周期 | 说明 |
|---------|----------|---------|------|
| 主分支 | `master` | 永久 | 生产环境代码，始终可部署 |
| 开发分支 | `develop` | 永久 | 日常开发集成分支 |
| 功能分支 | `feat/<功能名>` | 合并后删除 | 新功能开发 |
| 修复分支 | `fix/<问题描述>` | 合并后删除 | Bug 修复 |
| 发布分支 | `release/<版本号>` | 发布后删除 | 版本发布准备 |
| 热修复分支 | `hotfix/<问题描述>` | 合并后删除 | 线上紧急修复 |

### 2.2 分支关系图

```
master ─────●─────────────────●─────────────────●──── 生产
             \               /                   \
release/1.0 ──●─────────────/                     \
               \           /                       \
hotfix ─────────●─────────/                         \
               /         /                           \
develop ──●───●────●─────●──────●───────────────────── 集成
           \       \           /
feat/xxx ───●       \         /
                     \       /
feat/yyy ─────────────●─────/
```

### 2.3 分支命名规范

```
feat/agent-workflow-engine       # 功能分支
fix/session-timeout-bug          # 修复分支
release/1.0.0                    # 发布分支
hotfix/critical-auth-bypass      # 热修复分支
chore/upgrade-adk-dependency     # 杂项分支
refactor/event-pipeline          # 重构分支
```

**规则：**
- 全部小写，单词用 `-` 连接
- 前缀必须与 commit type 一致（feat/fix/chore/refactor/perf/ci/build）
- 名称简洁但能说明意图

---

## 三、Commit Message 规范

### 3.1 格式

```
<type>(<scope>): <subject>

[body]

[footer]
```

### 3.2 Type 前缀

| 前缀 | 含义 | 使用场景 |
|------|------|---------|
| `feat` | 新功能 | 新增业务功能、API、页面 |
| `fix` | 修复 bug | 修复线上问题、逻辑错误 |
| `docs` | 文档 | README、注释、API 文档 |
| `style` | 代码格式 | 空格、分号、格式化，不影响逻辑 |
| `refactor` | 重构 | 代码结构调整，不新增功能也不修 bug |
| `perf` | 性能优化 | 提升速度、降低内存 |
| `test` | 测试 | 新增/修改测试用例 |
| `chore` | 杂项 | 构建脚本、依赖升级、CI 配置 |
| `ci` | 持续集成 | GitHub Actions、Jenkins 配置 |
| `build` | 构建 | 编译相关、webpack/vite 配置 |
| `revert` | 回滚 | 撤销之前的提交 |

### 3.3 Scope（可选）

scope 说明影响的模块或范围：

| 项目 | 可用 scope |
|------|-----------|
| plexus-core | `agent`, `tool`, `mcp`, `api`, `db`, `session`, `document`, `config`, `cli` |
| plexus-im | `ws`, `event`, `kafka`, `room`, `filter`, `api` |
| plexus-server | `user`, `auth`, `common`, `agent`, `api`, `db` |
| plexus-web | `chat`, `admin`, `layout`, `api` |

### 3.4 示例

```bash
# 好的 commit message
feat(agent): 新增多轮对话编排引擎
fix(session): 修复会话超时后未正确清理资源的问题
refactor(event): 将 SSE 事件处理管道拆分为独立模块
perf(api): 优化 Agent 列表查询，增加缓存层
docs(readle): 补充本地开发环境搭建指南
chore(deps): 升级 google-adk 到 1.2.0
ci(github): 添加 PR 自动化代码检查流水线

# 不好的 commit message
update code              # 太模糊
fix bug                  # 没有说明修了什么
feat: 新功能             # scope 缺失时可接受，但尽量加上
WIP                      # 不要提交半成品到 develop/master
```

### 3.5 提交粒度

- **一个 commit = 一个逻辑变更**：不要把多个不相关的改动塞进一个 commit
- **commit 应该能独立通过 CI**：每个 commit 都应该是可构建、可测试的
- **WIP 提交只允许在功能分支上**：合并到 develop 前必须 squash 或整理

---

## 四、工作流程

### 4.1 新功能开发

```bash
# 1. 从 develop 创建功能分支
git checkout develop
git pull origin develop
git checkout -b feat/new-agent-type

# 2. 开发并提交（可以多次小提交）
git add src/plexus/agents/new_agent.py
git commit -m "feat(agent): 新增 new_agent 基础结构"

git add src/plexus/toolkits/new_tool.py
git commit -m "feat(tool): 新增 new_tool 实现"

# 3. 合并前同步 develop（rebase 保持线性历史）
git fetch origin
git rebase origin/develop

# 4. 推送并创建 PR
git push origin feat/new-agent-type
# 在 GitHub/GitLab 上创建 PR: feat/new-agent-type -> develop

# 5. Code Review 通过后合并，删除功能分支
git checkout develop
git branch -d feat/new-agent-type
```

### 4.2 Bug 修复

```bash
# 1. 从 develop 创建修复分支
git checkout develop
git checkout -b fix/session-cleanup

# 2. 修复并提交
git add .
git commit -m "fix(session): 修复断开连接后会话未清理的问题

根因：WebSocket close 事件未触发 session cleanup。
解决方案：在 on_close 回调中增加 session 清理逻辑。

Closes #42"

# 3. 合并到 develop
git checkout develop
git merge --no-ff fix/session-cleanup
git branch -d fix/session-cleanup
```

### 4.3 版本发布

```bash
# 1. 从 develop 创建发布分支
git checkout develop
git checkout -b release/1.0.0

# 2. 只做版本号修改、文档更新、最后的 bugfix
git commit -m "chore: bump version to 1.0.0"

# 3. 合并到 master 并打 tag
git checkout master
git merge --no-ff release/1.0.0
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin master --tags

# 4. 同步回 develop
git checkout develop
git merge --no-ff release/1.0.0
git branch -d release/1.0.0
```

### 4.4 线上热修复

```bash
# 1. 从 master 创建热修复分支
git checkout master
git checkout -b hotfix/auth-bypass

# 2. 修复并提交
git commit -m "fix(auth): 修复未登录用户可绕过鉴权的严重漏洞"

# 3. 同时合并到 master 和 develop
git checkout master
git merge --no-ff hotfix/auth-bypass
git tag -a v1.0.1 -m "Hotfix v1.0.1: auth bypass"
git checkout develop
git merge --no-ff hotfix/auth-bypass
git branch -d hotfix/auth-bypass
```

---

## 五、合并策略

### 5.1 合并方式

| 场景 | 合并方式 | 说明 |
|------|---------|------|
| 功能分支 -> develop | `--no-ff` merge 或 squash | 保留功能分支的完整历史 |
| release -> master | `--no-ff` merge | 保留发布分支的完整记录 |
| hotfix -> master + develop | `--no-ff` merge | 保留修复记录 |
| 同步 develop 最新代码 | rebase | 功能分支保持线性历史 |

### 5.2 PR / Merge Request 规范

- **必须至少 1 人 Code Review**（建议 plexus-core 由核心框架维护者 review）
- **PR 标题遵循 commit message 格式**
- **PR 描述应包含**：
  - 做了什么（What）
  - 为什么做（Why）
  - 如何测试（How to test）
  - 关联的 Issue 编号
- **功能分支合并后必须删除**

### 5.3 保护分支规则

建议对 `master` 和 `develop` 设置保护：

- **master**：禁止直接 push，必须通过 PR 合并，至少 1 人 approve
- **develop**：禁止直接 push（可选），通过 PR 合并

---

## 六、多仓库协作

### 6.1 子项目版本对齐

Plexus 各子项目存在运行时依赖关系，建议：

| 子项目 | 版本策略 |
|--------|---------|
| plexus-core | 独立版本号（v1.x.x） |
| plexus-im | 独立版本号（v1.x.x） |
| plexus-server | 独立版本号（v1.x.x） |
| plexus-web | 独立版本号（v1.x.x） |
| plexus-admin | 跟随 plexus-server |
| plexus-mcp-server | 独立版本号（v1.x.x） |

### 6.2 接口变更协调

当 plexus-core 的 API 接口变更时：

1. **先在 plexus-core 的 develop 分支完成改动**
2. **通知下游**（plexus-server、plexus-im）同步适配
3. **各子项目独立发版**，通过版本号记录兼容关系

### 6.3 Monorepo vs Multirepo

当前采用 **Multirepo**（每个子项目独立仓库），适合：
- 不同技术栈（Python/Go/Java/前端）
- 独立部署和发版
- 团队成员可独立工作

如后续需要统一管理，可考虑引入 **Nx** 或 **Turborepo**（前端）或统一的 CI 编排。

---

## 七、Git 配置建议

### 7.1 全局配置

```bash
# 提交者信息
git config --global user.name "你的名字"
git config --global user.email "your@email.com"

# 默认分支名
git config --global init.defaultBranch master

# 自动处理行尾
git config --global core.autocrlf true   # Windows
git config --global core.autocrlf input  # Mac/Linux

# rebase 作为默认合并策略
git config --global pull.rebase true

# push 时默认推送当前分支
git config --global push.default current
```

### 7.2 .gitignore 模板

各子项目已有的 .gitignore 基本够用，建议补充：

```gitignore
# IDE
.idea/
.vscode/
*.swp
*.swo

# Environment
.env
.env.local
.env.*.local

# Logs
logs/
*.log

# OS
.DS_Store
Thumbs.db

# Python
__pycache__/
*.pyc
.venv/
*.egg-info/

# Go
vendor/

# Java
target/
*.class
*.jar

# Node
node_modules/
dist/
```

---

## 八、Commit Message 快速参考卡

```
+-------------------------------------------------------+
|  <type>(<scope>): <subject>                           |
|                                                       |
|  type:  feat | fix | docs | style | refactor |        |
|         perf | test | chore | ci | build | revert     |
|                                                       |
|  scope: agent | tool | mcp | api | db | session |     |
|         ws | event | kafka | room | auth | user       |
|                                                       |
|  subject: 简洁描述，祈使句，首字母小写，不加句号       |
|                                                       |
|  示例:                                                |
|    feat(agent): 新增工作流编排引擎                     |
|    fix(session): 修复会话超时未清理资源                |
|    perf(api): 增加 Agent 列表查询缓存                  |
+-------------------------------------------------------+
```

---

## 九、常用命令速查

```bash
# 查看分支图
git log --oneline --graph --all

# 暂存当前工作
git stash
git stash pop

# 撤销工作区修改
git checkout -- <file>

# 撤销暂存
git reset HEAD <file>

# 修改最后一次 commit
git commit --amend

# 交互式 rebase（整理 commit 历史）
git rebase -i HEAD~3

# 查看某文件的修改历史
git log --follow -p -- <file>

# 查找引入 bug 的 commit
git bisect start
git bisect bad HEAD
git bisect good <last-known-good>
```
