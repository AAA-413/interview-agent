---
skill: service-startup
description: 前后端服务标准启动流程
tags: [startup, backend, frontend, troubleshooting]
---

# 服务启动 Skill

规范化的前后端服务启动流程，包含环境检查、缓存清理、服务启动和功能验证。

## 使用场景

- 开发环境启动服务
- 代码更新后重启服务
- 故障排查需要重启
- 新环境首次部署

## 快速启动

### 前置条件：启动 Docker 基础设施

```bash
docker compose up -d
```

### 后端启动（一键命令）

```bash
# 清理缓存 + 启动后端
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force; .venv\Scripts\python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

### 前端启动（一键命令）

```bash
# 启动前端（新终端）
cd frontend && npm run dev
```

## 标准启动流程

### 步骤 0：启动基础设施服务（Docker）

**重要：必须先启动 PostgreSQL、Redis、MinIO，后端才能正常运行。**

```bash
# 在项目根目录执行
docker compose up -d

# 验证所有容器健康
docker ps --filter "name=interview" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

**预期输出（3 个容器均为 healthy）：**
```
NAMES                STATUS                    PORTS
interview-postgres   Up X seconds (healthy)    0.0.0.0:5432->5432/tcp
interview-redis      Up X seconds (healthy)    0.0.0.0:6379->6379/tcp
interview-minio      Up X seconds (healthy)    0.0.0.0:9000-9001->9000-9001/tcp
```

**容器说明：**
| 容器 | 端口 | 用途 |
|------|------|------|
| interview-postgres | 5432 | PostgreSQL + pgvector（向量检索） |
| interview-redis | 6379 | Redis（任务队列、缓存、会话） |
| interview-minio | 9000/9001 | MinIO 对象存储（文件上传） |

**停止基础设施：**
```bash
docker compose down        # 停止并保留数据
docker compose down -v     # 停止并删除数据卷（慎用）
```

### 步骤 1：环境检查

```bash
# 检查 Python 版本
python --version  # 需要 3.11+

# 检查虚拟环境
.venv\Scripts\python.exe --version

# 检查 PostgreSQL
psql --version

# 检查 Redis
redis-cli ping

# 检查 Node.js
node --version  # 需要 18+
```

### 步骤 2：端口检查

```bash
# 检查后端端口（8002）
netstat -ano | findstr :8002

# 检查前端端口（5173）
netstat -ano | findstr :5173

# 如果端口被占用，终止进程
taskkill /F /PID <PID>
```

### 步骤 3：清理 Python 缓存

**重要：每次启动前必须执行**

```bash
# PowerShell
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# Git Bash
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
```

**为什么要清理缓存？**
- Python 会缓存编译后的字节码（.pyc 文件）
- 代码更新后，缓存可能导致加载旧代码
- 使用 `-B` 标志可以禁用字节码生成

### 步骤 4：启动后端服务

```bash
# 标准启动（推荐）
.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 开发模式（热重载，不推荐用于测试）
.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

**启动参数说明：**
- `-B`: 禁用字节码缓存
- `--host 0.0.0.0`: 监听所有网络接口
- `--port 8002`: 指定端口
- `--reload`: 代码变更自动重载（可能导致缓存问题）

### 步骤 5：验证后端启动

```bash
# 健康检查
curl http://localhost:8002/api/health

# 预期返回
{"status":"UP","service":"AI Interview Platform"}

# 检查 API 文档
curl http://localhost:8002/docs
```

### 步骤 6：启动前端服务

```bash
# 进入前端目录
cd frontend

# 首次启动需要安装依赖
npm install

# 启动开发服务器
npm run dev
```

**前端端口说明：**
- 默认端口：5173
- 如果被占用，自动使用 5174

### 步骤 7：验证前端启动

```bash
# 检查前端响应
curl http://localhost:5173

# 浏览器访问
# http://localhost:5173
```

## 功能验证清单

### 后端 API 验证

```bash
# 1. 健康检查
curl http://localhost:8002/api/health

# 2. 简历列表
curl http://localhost:8002/api/resumes | python -m json.tool

# 3. 面试技能列表
curl http://localhost:8002/api/interview/skills | head -50

# 4. 知识库列表
curl http://localhost:8002/api/knowledgebase | python -m json.tool
```

### 前端页面验证

浏览器访问以下页面：
1. 首页：http://localhost:5173
2. 简历管理：http://localhost:5173/resumes
3. 面试中心：http://localhost:5173/interview-hub
4. 知识库：http://localhost:5173/knowledge-base

### 核心功能验证

```bash
# 1. 简历上传
echo "测试简历内容" > /tmp/test_resume.txt
curl -X POST http://localhost:8002/api/resumes -F "file=@/tmp/test_resume.txt" | python -m json.tool

# 2. 等待 Worker 处理（5秒）
sleep 5

# 3. 查看简历分析状态
curl http://localhost:8002/api/resumes/<resume_id> | python -m json.tool | grep "analyze_status"

# 4. 删除测试简历
curl -X DELETE http://localhost:8002/api/resumes/<resume_id> | python -m json.tool
```

## 一键启动脚本

### PowerShell 脚本

创建 `start-services.ps1`：

```powershell
# 启动前后端服务

Write-Host "=== 启动基础设施 (Docker) ===" -ForegroundColor Green
docker compose up -d
Start-Sleep -Seconds 3

Write-Host "=== 清理 Python 字节码缓存 ===" -ForegroundColor Green
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Write-Host "`n=== 启动后端服务 ===" -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; .venv\Scripts\python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002"

Write-Host "`n=== 等待后端启动 ===" -ForegroundColor Yellow
Start-Sleep -Seconds 5

Write-Host "`n=== 启动前端服务 ===" -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\frontend'; npm run dev"

Write-Host "`n=== 服务启动完成 ===" -ForegroundColor Green
Write-Host "后端地址: http://localhost:8002" -ForegroundColor Cyan
Write-Host "前端地址: http://localhost:5173" -ForegroundColor Cyan
Write-Host "API 文档: http://localhost:8002/docs" -ForegroundColor Cyan
```

使用方法：
```powershell
.\start-services.ps1
```

### Bash 脚本

创建 `start-services.sh`：

```bash
#!/bin/bash

echo "=== 启动基础设施 (Docker) ==="
docker compose up -d
sleep 3

echo "=== 清理 Python 字节码缓存 ==="
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

echo -e "\n=== 启动后端服务 ==="
.venv/Scripts/python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002 &
BACKEND_PID=$!

echo -e "\n=== 等待后端启动 ==="
sleep 5

echo -e "\n=== 启动前端服务 ==="
cd frontend
npm run dev &
FRONTEND_PID=$!

echo -e "\n=== 服务启动完成 ==="
echo "后端地址: http://localhost:8002"
echo "前端地址: http://localhost:5173"
echo "API 文档: http://localhost:8002/docs"
echo -e "\n后端 PID: $BACKEND_PID"
echo "前端 PID: $FRONTEND_PID"

# 等待用户按 Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
```

使用方法：
```bash
chmod +x start-services.sh
./start-services.sh
```

## 常见问题排查

### 问题 1：端口被占用

**现象：**
```
ERROR: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8002)
```

**解决方案：**
```bash
# 查找占用进程
netstat -ano | findstr :8002

# 终止进程
taskkill /F /PID <PID>

# 或批量终止
for /f "tokens=5" %a in ('netstat -ano ^| findstr :8002') do @taskkill /F /PID %a
```

### 问题 2：代码更新不生效

**现象：** 修改代码后，运行时仍使用旧逻辑。

**原因：** Python 字节码缓存未清理。

**解决方案：**
```bash
# 1. 停止服务
Ctrl+C

# 2. 清理缓存
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 3. 使用 -B 标志重启
.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

### 问题 3：数据库连接失败

**现象：**
```
WARNING: 数据库初始化失败（服务仍可启动）: connection refused
```

**解决方案：**
```bash
# 检查 Docker 容器是否运行
docker ps --filter "name=interview-postgres"

# 如果未运行，启动基础设施
docker compose up -d

# 等待容器 healthy 后测试连接
docker exec interview-postgres pg_isready -U postgres

# 直接测试 psql 连接
psql -h localhost -U postgres -d interview_guide -c "SELECT 1;"
```

### 问题 4：Redis 连接失败

**现象：**
```
WARNING: Redis 连接失败（服务仍可启动）: Connection refused
```

**解决方案：**
```bash
# 检查 Docker 容器是否运行
docker ps --filter "name=interview-redis"

# 如果未运行，启动基础设施
docker compose up -d

# 测试连接
docker exec interview-redis redis-cli ping
```

### 问题 5：Worker 未启动

**现象：** 简历上传后状态一直为 `PENDING`。

**原因：** Redis 或数据库连接失败。

**解决方案：**
```bash
# 1. 检查后端日志
tail -f logs/app.log | grep "worker"

# 2. 确认 Redis 和数据库都已启动
curl http://localhost:8002/api/health

# 3. 查看 Worker 启动日志
# 注意：默认日志级别为 WARNING，INFO 日志不会显示
# Worker 启动成功的标志是简历分析功能正常工作
```

### 问题 6：前端依赖缺失

**现象：**
```
Error: Cannot find module 'xxx'
```

**解决方案：**
```bash
cd frontend

# 清理依赖
rm -rf node_modules package-lock.json

# 重新安装
npm install

# 启动服务
npm run dev
```

### 问题 7：bcrypt 版本不兼容导致登录 500 错误

**现象：**
```
POST /api/auth/login HTTP/1.1" 500 Internal Server Error
ValueError: password cannot be longer than 72 bytes, truncate manually if necessary
AttributeError: module 'bcrypt' has no attribute '__about__'
```

**原因：** `bcrypt>=4.1.0` 与 `passlib` 不兼容，passlib 尚未适配新版 bcrypt 的 API 变更。

**解决方案：**
```bash
# 降级 bcrypt 到兼容版本
.venv\Scripts\pip.exe install "bcrypt>=4.0.0,<4.1.0"

# 重启后端服务
Ctrl+C
.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

**预防：** `requirements.txt` 和 `pyproject.toml` 中已锁定 `bcrypt>=4.0.0,<4.1.0`，重新安装依赖即可避免。

### 问题 8：环境变量未加载

**现象：** API Key 或数据库连接失败。

**解决方案：**
```bash
# 检查 .env 文件是否存在
ls -la .env

# 检查环境变量
echo $DASHSCOPE_API_KEY
echo $DATABASE_URL

# 如果未加载，手动加载
source .env  # Linux/Mac
# 或在 PowerShell 中逐行设置
```

## 性能监控

### 关键指标

| 指标 | 正常范围 | 监控方法 |
|------|---------|---------|
| 后端启动时间 | < 5s | 查看日志 "应用启动完成" |
| 前端启动时间 | < 10s | 查看终端输出 |
| 健康检查响应 | < 100ms | `curl -w "@curl-format.txt"` |
| Worker 启动数量 | 3 个 | 查看日志或测试简历分析 |

### 日志监控

```bash
# 实时查看后端日志
tail -f logs/app.log

# 过滤错误日志
tail -f logs/app.log | grep "ERROR"

# 过滤 Worker 日志
tail -f logs/app.log | grep "worker"

# 过滤特定模块日志
tail -f logs/app.log | grep "resume"
```

## 停止服务

### 手动停止

```bash
# 在启动服务的终端按 Ctrl+C
```

### 强制停止

```bash
# 查找进程
netstat -ano | findstr :8002
netstat -ano | findstr :5173

# 终止进程
taskkill /F /PID <BACKEND_PID>
taskkill /F /PID <FRONTEND_PID>
```

### 停止脚本

创建 `stop-services.ps1`：

```powershell
Write-Host "=== 停止后端服务 ===" -ForegroundColor Yellow
$backend = Get-NetTCPConnection -LocalPort 8002 -ErrorAction SilentlyContinue
if ($backend) {
    $pid = $backend.OwningProcess
    Stop-Process -Id $pid -Force
    Write-Host "后端服务已停止 (PID: $pid)" -ForegroundColor Green
}

Write-Host "`n=== 停止前端服务 ===" -ForegroundColor Yellow
$frontend = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue
if ($frontend) {
    $pid = $frontend.OwningProcess
    Stop-Process -Id $pid -Force
    Write-Host "前端服务已停止 (PID: $pid)" -ForegroundColor Green
}

Write-Host "`n=== 所有服务已停止 ===" -ForegroundColor Green
```

## 最佳实践

1. **启动前清理缓存**：避免加载旧代码
2. **使用 -B 标志**：禁用字节码生成
3. **检查端口占用**：避免启动失败
4. **验证服务状态**：确保功能正常
5. **查看日志输出**：及时发现问题
6. **定期重启服务**：清理内存和缓存

## 快速参考

### 服务地址

- 后端 API：http://localhost:8002
- 前端页面：http://localhost:5173
- API 文档：http://localhost:8002/docs
- API JSON：http://localhost:8002/openapi.json

### 关键命令

```bash
# 启动基础设施（PostgreSQL + Redis + MinIO）
docker compose up -d

# 检查容器状态
docker ps --filter "name=interview"

# 停止基础设施
docker compose down

# 清理缓存
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 启动后端
.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 启动前端
cd frontend && npm run dev

# 健康检查
curl http://localhost:8002/api/health

# 查看日志
tail -f logs/app.log

# 停止服务
taskkill /F /PID <PID>
```

## 相关文档

- [服务启动指南](../../docs/01-项目管理/服务启动指南.md)
- [下次会话快速启动指南](../../docs/01-项目管理/下次会话快速启动指南.md)
- [Git 工作流程](./git-workflow.md)
