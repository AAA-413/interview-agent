---
skill: git-workflow
description: Git 代码提交和推送的标准工作流程
tags: [git, workflow, version-control]
---

# Git 工作流程 Skill

规范化的 Git 代码提交和推送流程，确保代码质量和提交历史清晰。

## 使用场景

- 完成功能开发需要提交代码
- 修复 bug 需要推送到远程仓库
- 文档更新需要版本管理
- 多人协作需要同步代码

## 部署架构

```
本地开发 (Windows)              GitHub/Gitee (远程仓库)           腾讯云服务器 (生产环境)
     │                              │                                  │
     │ git push origin main         │                                  │
     │ ─────────────────────────►   │                                  │
     │                              │   git fetch origin               │
     │                              │ ◄────────────────────────────────│
     │                              │   git checkout v1.0 (切特定版本) │
     │                              │                                  │
     │ git tag v1.0                 │                                  │
     │ git push origin v1.0         │                                  │
     │ ─────────────────────────►   │                                  │
```

## 分支工作流

### 核心原则

- **main 分支**：永远是可运行的稳定版本，腾讯云服务器跑的就是 main
- **功能/修复分支**：所有改动在分支上做，确认没问题再合并回 main
- **分支命名规范**：`feat/功能名`（新功能）、`fix/问题名`（修 bug）、`docs/内容`（文档）

### 分支示意图

```
main (稳定版，服务器部署)
 ├── feat/smart-download       ← 新功能开发
 ├── fix/quality-score-bug     ← 修 bug
 └── docs/update-readme        ← 文档更新
```

### 日常开发流程（每次改代码前做一遍）

```bash
# 1. 确保在 main 上，拉最新
git checkout main
git pull origin main

# 2. 创建分支，开始改代码
git checkout -b fix/某个bug     # 修 bug
# 或
git checkout -b feat/某个功能   # 新功能

# 3. 改完了，提交到分支
git add 改动的文件
git commit -m "fix: 修复xxx问题"

# 4. 合并回 main
git checkout main
git merge fix/某个bug

# 5. 推送到远程（两个远程都要推）
git push origin main
git push github main

# 6. 推送分支到远程（备份，方便回溯）
git push origin fix/某个bug

# 7. 删掉已合并的本地分支（可选，保持整洁）
git branch -d fix/某个bug
```

### 发布版本（重要功能上线后打标签）

```bash
# 当 main 上的功能稳定后，打标签标记版本
git tag -a v1.1 -m "v1.1: 新增xxx功能"

# 推送标签到远程
git push origin v1.1
git push github v1.1

# 查看所有标签
git tag -l
```

### 服务器部署

```bash
# ssh 到腾讯云服务器
ssh root@你的服务器IP
cd /path/to/project

# 拉取最新代码和标签
git fetch origin

# === 方式1：部署最新版（日常更新）===
git checkout main
git pull origin main

# === 方式2：部署特定版本（回退或指定版本）===
git checkout v1.0          # 用标签切到 v1.0
git checkout 20d259c       # 用 commit hash 切到某次提交

# 重启服务...

# === 想回到最新版 ===
git checkout main
git pull origin main
```

### 完整示例

```bash
# 开始：创建分支修复 quality_score 显示 0% 的 bug
git checkout main
git checkout -b fix/quality-score-display

# 修改代码...
git add frontend/src/pages/SmartDownloadPage.tsx
git commit -m "fix: 修复 quality_score 显示 0% (null vs undefined)"

# 测试通过，合并回 main
git checkout main
git merge fix/quality-score-display
git push origin main
git push github main

# 推送分支到远程（备份）
git push origin fix/quality-score-display

# 功能稳定后，打标签
git tag -a v1.0.1 -m "v1.0.1: 修复 quality_score 显示"
git push origin v1.0.1

# 服务器部署
# ssh 到服务器
git fetch origin
git checkout v1.0.1
# 重启服务

# 清理本地分支
git branch -d fix/quality-score-display
```

## 标准工作流程

### 1. 查看当前状态

```bash
# 查看修改文件
git status

# 查看具体修改内容
git diff

# 查看最近提交记录
git log --oneline -5
```

### 2. 暂存文件

**选择性暂存（推荐）：**
```bash
# 暂存特定文件
git add <file1> <file2> <file3>

# 暂存特定目录
git add <directory>/

# 示例：暂存文档更新
git add README.md docs/01-项目管理/服务启动指南.md
```

**全部暂存（谨慎使用）：**
```bash
# 暂存所有修改（不推荐，可能包含敏感文件）
git add -A

# 暂存当前目录所有修改
git add .
```

### 3. 提交代码

**标准提交格式：**
```bash
git commit -m "$(cat <<'EOF'
<type>: <subject>

<body>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**提交类型（type）：**
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `refactor`: 代码重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具链更新
- `style`: 代码格式调整

**提交示例：**

```bash
# 功能开发
git commit -m "$(cat <<'EOF'
feat: 实现智能下载知识库功能

- 新增 GitHub 仓库抓取服务
- 新增搜索引擎集成（Tavily）
- 实现 Agent 编排框架
- 前端页面完整实现

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# Bug 修复
git commit -m "$(cat <<'EOF'
fix: 修复简历删除功能报错

- 清理 Python 字节码缓存
- 添加 delete_resume 方法
- 更新错误处理逻辑

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# 文档更新
git commit -m "$(cat <<'EOF'
docs: 规范前后端服务启动流程

- 新增《服务启动指南》文档
- 更新 README.md 快速启动命令
- 提供一键启动脚本

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### 4. 推送到远程

```bash
# 推送到主分支
git push origin main

# 推送到其他分支
git push origin <branch-name>

# 强制推送（谨慎使用）
git push origin main --force
```

### 5. 验证推送结果

```bash
# 查看远程状态
git remote -v

# 查看远程分支
git branch -r

# 查看提交历史
git log --oneline --graph -10
```

## 常见场景处理

### 场景 1：修改上次提交

```bash
# 修改提交信息
git commit --amend -m "新的提交信息"

# 添加遗漏文件到上次提交
git add <forgotten-file>
git commit --amend --no-edit
```

### 场景 2：撤销暂存

```bash
# 撤销所有暂存
git reset HEAD

# 撤销特定文件暂存
git reset HEAD <file>
```

### 场景 3：撤销修改

```bash
# 撤销工作区修改（危险操作）
git checkout -- <file>

# 撤销所有工作区修改（危险操作）
git checkout -- .
```

### 场景 4：回退提交

```bash
# 回退到上一个提交（保留修改）
git reset --soft HEAD~1

# 回退到上一个提交（丢弃修改，危险操作）
git reset --hard HEAD~1

# 回退到指定提交
git reset --soft <commit-hash>
```

### 场景 5：解决冲突

```bash
# 拉取远程更新
git pull origin main

# 如果有冲突，手动解决后
git add <resolved-files>
git commit -m "merge: 解决合并冲突"
git push origin main
```

### 场景 6：暂存当前工作

```bash
# 暂存当前修改
git stash

# 查看暂存列表
git stash list

# 恢复暂存
git stash pop

# 删除暂存
git stash drop
```

## 最佳实践

### 1. 提交前检查

```bash
# 检查修改内容
git diff

# 检查暂存内容
git diff --cached

# 检查提交历史
git log --oneline -5
```

### 2. 提交粒度

- **单一职责**：每次提交只做一件事
- **原子性**：提交应该是完整的、可运行的
- **可回滚**：每次提交都应该可以独立回滚

### 3. 提交信息规范

- **标题**：简洁明了，不超过 50 字符
- **正文**：详细说明修改内容和原因
- **引用**：关联 Issue 或 PR 编号

### 4. 敏感信息检查

**禁止提交：**
- `.env` 文件（包含 API Key）
- `credentials.json`（认证信息）
- `*.pem`、`*.key`（私钥文件）
- `node_modules/`（依赖目录）
- `__pycache__/`（Python 缓存）
- `*.log`（日志文件）

**检查方法：**
```bash
# 查看即将提交的文件
git status

# 检查 .gitignore 配置
cat .gitignore
```

### 5. 推送前验证

```bash
# 运行测试
pytest tests/

# 检查代码格式
ruff check .

# 类型检查
mypy app/
```

## 常见错误处理

### 错误 1：推送被拒绝

```bash
# 错误信息
! [rejected] main -> main (fetch first)

# 解决方案
git pull origin main --rebase
git push origin main
```

### 错误 2：提交了敏感文件

```bash
# 从历史中删除文件
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch <file>" \
  --prune-empty --tag-name-filter cat -- --all

# 强制推送（危险操作）
git push origin main --force
```

### 错误 3：提交信息写错

```bash
# 修改最近一次提交信息
git commit --amend -m "正确的提交信息"

# 如果已推送，需要强制推送
git push origin main --force
```

### 错误 4：推送到错误分支

```bash
# 删除远程错误分支
git push origin --delete <wrong-branch>

# 推送到正确分支
git push origin <correct-branch>
```

## 版本控制

### 查看历史版本

```bash
# 查看提交历史（简洁版）
git log --oneline

# 查看带分支图的历史
git log --oneline --graph -10

# 查看某个文件的修改历史
git log --oneline -- frontend/src/pages/SmartDownloadPage.tsx
```

### 切换到任意历史版本

```bash
# 切到某个 commit 看看（只读，不影响任何东西）
git checkout 2de9f57

# 看完了，回到最新
git checkout main
```

### 撤销某次提交（安全方式）

```bash
# 撤销最近一次提交，生成一个新的"撤销提交"
git revert HEAD

# 撤销指定提交
git revert 20d259c

# 推送撤销结果
git push origin main
```

### 给重要版本打标签

```bash
# 给当前版本打标签
git tag v1.0

# 给指定 commit 打标签
git tag v1.0-beta 2de9f57

# 推送标签到远程
git push origin v1.0

# 查看所有标签
git tag -l

# 切到某个标签版本
git checkout v1.0
```

### 回退到某个版本（危险操作）

```bash
# 回退到上一个提交（保留文件修改，只撤销 commit）
git reset --soft HEAD~1

# 回退到上一个提交（丢弃所有改动，慎用）
git reset --hard HEAD~1

# 回退到指定提交（丢弃之后的所有改动，慎用）
git reset --hard 2de9f57

# 如果已经推送，需要强制推送（会覆盖远程历史，慎用）
git push origin main --force
```

**注意**：`reset --hard` 和 `--force` 推送会丢失历史，优先用 `revert`。

### 暂存当前工作（临时切走）

```bash
# 暂存当前未提交的修改
git stash

# 查看暂存列表
git stash list

# 恢复暂存
git stash pop

# 删除暂存
git stash drop
```

## 分支管理

### 创建分支

```bash
# 创建并切换到新分支
git checkout -b <branch-name>

# 或使用新语法
git switch -c <branch-name>
```

### 切换分支

```bash
# 切换到已存在分支
git checkout <branch-name>

# 或使用新语法
git switch <branch-name>
```

### 合并分支

```bash
# 切换到目标分支
git checkout main

# 合并源分支
git merge <source-branch>

# 推送合并结果
git push origin main
```

### 删除分支

```bash
# 删除本地分支
git branch -d <branch-name>

# 强制删除本地分支
git branch -D <branch-name>

# 删除远程分支
git push origin --delete <branch-name>
```

## 快速参考

### 日常开发速查

```bash
# === 开始改代码 ===
git checkout main && git pull origin main   # 切到 main 拉最新
git checkout -b fix/xxx                     # 创建分支

# === 提交改动 ===
git add <file>                              # 暂存文件
git commit -m "fix: 描述"                    # 提交

# === 合并推送 ===
git checkout main && git merge fix/xxx      # 合并回 main
git push origin main && git push github main  # 推送到两个远程

# === 发布版本 ===
git tag -a v1.1 -m "v1.1: 描述"             # 打标签
git push origin v1.1 && git push github v1.1  # 推送标签

# === 服务器部署 ===
git fetch origin                            # 拉取远程最新（含标签）
git checkout main && git pull origin main   # 部署最新版
git checkout v1.0                           # 或部署特定版本

# === 版本控制 ===
git log --oneline                           # 查看历史
git tag -l                                  # 查看所有标签
git checkout <hash>                         # 切到某个版本查看
git checkout main                           # 回到最新
git revert <hash>                           # 撤销某次提交（安全）
```

### 常用命令速查

```bash
# 查看状态
git status

# 查看修改
git diff

# 暂存文件
git add <file>

# 提交代码
git commit -m "message"

# 推送代码
git push origin main

# 拉取更新
git pull origin main

# 查看日志
git log --oneline -10

# 查看分支
git branch -a
```

### 提交模板

```bash
git commit -m "$(cat <<'EOF'
<type>: <简短描述>

<详细说明>
- 修改点 1
- 修改点 2
- 修改点 3

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

## 注意事项

1. **推送前必须测试**：确保代码可运行
2. **避免强制推送**：除非确实需要重写历史
3. **保护主分支**：所有改动在分支上做，确认没问题再合并回 main
4. **两个远程都要推**：`git push origin main` 和 `git push github main`
5. **重要功能上线后打标签**：方便服务器回退到任意版本
6. **服务器用 `git fetch` + `git checkout tag`**：比 `git pull` 更精确可控
7. **清晰的提交信息**：方便后续追溯和回滚

## 相关文档

- [服务启动指南](../../docs/01-项目管理/服务启动指南.md)
- [下次会话快速启动指南](../../docs/01-项目管理/下次会话快速启动指南.md)
- [Git 官方文档](https://git-scm.com/doc)
