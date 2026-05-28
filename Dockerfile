# ============================================================
# DocConv Dockerfile — 多阶段构建
# ============================================================

# ----------------------------------------------------------
# Stage 1: builder — 安装依赖到 venv
# ----------------------------------------------------------
FROM python:3.10-slim AS builder

WORKDIR /build

# 安装构建依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# 创建虚拟环境
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 复制 requirements 并安装依赖（利用 Docker 缓存层）
COPY requirements.txt requirements-service.txt /build/
RUN pip install --no-cache-dir -r requirements-service.txt

# ----------------------------------------------------------
# Stage 2: runtime — 最小化运行镜像
# ----------------------------------------------------------
FROM python:3.10-slim AS runtime

# 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    STORAGE_ROOT=/data/docconv \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000 \
    LOG_LEVEL=INFO

# 从 builder 复制 venv
COPY --from=builder /opt/venv /opt/venv

# 创建非 root 用户
RUN groupadd -r docconv && \
    useradd -r -g docconv -d /data -s /sbin/nologin docconv && \
    mkdir -p /data/docconv && \
    chown -R docconv:docconv /data

# 创建应用目录
WORKDIR /app

# 复制应用代码
COPY src/ /app/src/
COPY config/ /app/config/

# 切换到非 root 用户
USER docconv

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import http.client; c = http.client.HTTPConnection('127.0.0.1', 8000); c.request('GET', '/api/v1/health'); r = c.getresponse(); exit(0 if r.status == 200 else 1)" || exit 1

# 默认入口
ENTRYPOINT ["docconv"]
CMD ["serve"]
