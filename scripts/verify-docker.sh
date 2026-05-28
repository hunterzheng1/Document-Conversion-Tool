#!/bin/bash
# ============================================================
# DocConv Docker 构建与运行验证脚本
# 用法: ./scripts/verify-docker.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="docconv:test"
PASS=0
FAIL=0

green() { echo -e "\033[32m$1\033[0m"; }
red()   { echo -e "\033[31m$1\033[0m"; }
info()  { echo -e "\033[36m[INFO]\033[0m $1"; }
ok()    { green "[PASS] $1"; ((PASS++)); }
fail()  { red "[FAIL] $1"; ((FAIL++)); }

# ----------------------------------------------------------
# 0. 检查 Docker 是否可用
# ----------------------------------------------------------
if ! command -v docker &>/dev/null; then
    info "Docker 未安装，跳过 Docker 验证"
    exit 0
fi

if ! docker info &>/dev/null; then
    info "Docker 守护进程未运行，跳过 Docker 验证"
    exit 0
fi

cd "$PROJECT_ROOT"

# ----------------------------------------------------------
# 1. 构建镜像
# ----------------------------------------------------------
info "步骤 1: 构建 Docker 镜像..."
if docker build -t "$IMAGE_NAME" . 2>&1; then
    ok "镜像构建成功"
else
    fail "镜像构建失败"
    exit 1
fi

# ----------------------------------------------------------
# 2. 验证镜像大小 < 500MB
# ----------------------------------------------------------
info "步骤 2: 检查镜像大小..."
IMAGE_SIZE=$(docker image inspect "$IMAGE_NAME" --format='{{.Size}}' 2>/dev/null || echo "0")
IMAGE_SIZE_MB=$((IMAGE_SIZE / 1024 / 1024))
info "镜像大小: ${IMAGE_SIZE_MB} MB"
if [ "$IMAGE_SIZE_MB" -lt 500 ]; then
    ok "镜像大小 < 500MB (${IMAGE_SIZE_MB} MB)"
else
    fail "镜像大小超过 500MB (${IMAGE_SIZE_MB} MB)"
fi

# ----------------------------------------------------------
# 3. 验证非 root 用户
# ----------------------------------------------------------
info "步骤 3: 验证容器内以非 root 用户运行..."
USER_INFO=$(docker run --rm "$IMAGE_NAME" whoami 2>/dev/null || echo "unknown")
info "容器运行用户: $USER_INFO"
if [ "$USER_INFO" = "docconv" ]; then
    ok "容器以非 root 用户 docconv 运行"
else
    fail "容器未以 docconv 用户运行 (实际: $USER_INFO)"
fi

# ----------------------------------------------------------
# 4. 验证 .env 和数据目录不在镜像内
# ----------------------------------------------------------
info "步骤 4: 验证敏感文件不在镜像内..."
for path in ".env" ".data" ".cache" ".docconv_"; do
    if docker run --rm "$IMAGE_NAME" test -e "/app/$path" 2>/dev/null; then
        fail "镜像内存在 $path（应被排除）"
    else
        ok "镜像内不存在 $path"
    fi
done

# ----------------------------------------------------------
# 5. 清理测试镜像
# ----------------------------------------------------------
info "步骤 5: 清理测试镜像..."
docker rmi "$IMAGE_NAME" 2>/dev/null || true
ok "测试镜像已清理"

# ----------------------------------------------------------
# 总结
# ----------------------------------------------------------
echo ""
echo "==========================================="
echo "  Docker 验证结果: $PASS 通过, $FAIL 失败"
echo "==========================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
