#!/bin/bash
# ============================================================
# DocConv pip install extras 验证脚本
# 用法: ./scripts/verify-install.sh
# 在独立虚拟环境中验证不同 extras 组合的安装行为
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PASS=0
FAIL=0

green() { echo -e "\033[32m$1\033[0m"; }
red()   { echo -e "\033[31m$1\033[0m"; }
info()  { echo -e "\033[36m[INFO]\033[0m $1"; }
ok()    { green "[PASS] $1"; ((PASS++)); }
fail()  { red "[FAIL] $1"; ((FAIL++)); }

cd "$PROJECT_ROOT"

# ----------------------------------------------------------
# 辅助函数：在临时 venv 中测试
# ----------------------------------------------------------
test_in_venv() {
    local venv_name="$1"
    local extras="$2"
    local check_cmd="$3"
    local venv_dir="/tmp/docconv-venv-${venv_name}"

    info "========== 测试 ${venv_name} =========="

    # 清理旧 venv
    rm -rf "$venv_dir"

    # 创建虚拟环境
    python3 -m venv "$venv_dir"
    source "$venv_dir/bin/activate"

    # 安装
    info "安装 docconv${extras}..."
    if pip install -q -e "${PROJECT_ROOT}${extras}" 2>&1; then
        ok "${venv_name} extras 安装成功"
    else
        fail "${venv_name} extras 安装失败"
        deactivate
        return 1
    fi

    # 执行检查命令
    if eval "$check_cmd" 2>&1; then
        ok "${venv_name} 命令验证通过"
    else
        fail "${venv_name} 命令验证失败"
    fi

    # 清理
    deactivate
    rm -rf "$venv_dir"
    echo ""
}

# ----------------------------------------------------------
# 检查 Python 可用
# ----------------------------------------------------------
if ! command -v python3 &>/dev/null; then
    info "Python3 未安装，跳过 install 验证"
    exit 0
fi

# ----------------------------------------------------------
# 1. 基础安装：仅 CLI
# ----------------------------------------------------------
test_in_venv "base" "" "docconv --help >/dev/null 2>&1"

# ----------------------------------------------------------
# 2. Service extras：serve/worker
# ----------------------------------------------------------
test_in_venv "service" "[service]" \
    "docconv serve --help >/dev/null 2>&1 && docconv worker --help >/dev/null 2>&1"

# ----------------------------------------------------------
# 3. Dev extras：pytest/ruff
# ----------------------------------------------------------
test_in_venv "dev" "[dev]" \
    "pytest --version >/dev/null 2>&1 && ruff --version >/dev/null 2>&1"

# ----------------------------------------------------------
# 4. Integrations extras
# ----------------------------------------------------------
test_in_venv "integrations" "[integrations]" \
    "python3 -c 'import importlib.metadata; d=importlib.metadata.distribution(\"docconv\"); print(d.name)'"

# ----------------------------------------------------------
# 总结
# ----------------------------------------------------------
echo ""
echo "==========================================="
echo "  pip install 验证结果: $PASS 通过, $FAIL 失败"
echo "==========================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
