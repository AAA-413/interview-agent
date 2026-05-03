FROM python:3.11-slim

# 配置国内镜像源
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends gcc postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# 配置 pip 镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 复制并安装依赖（利用缓存层）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# 复制应用代码
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY skills ./skills

# 创建日志目录并设置权限
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 暴露端口
EXPOSE 8002

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/api/health')" || exit 1

# 启动命令：gunicorn + uvicorn workers
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8002", \
     "--timeout", "300", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
