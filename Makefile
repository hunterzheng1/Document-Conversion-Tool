# ============================================================
# DocConv Makefile — 常见开发、构建、部署操作
# ============================================================

.PHONY: help install install-service test lint typecheck build run clean

# 默认目标
.DEFAULT_GOAL := help

# 显示所有可用命令
help:
	@echo "DocConv - 可用命令:"
	@echo ""
	@echo "  install            安装开发环境全部依赖 (pip install -e .[dev])"
	@echo "  install-service    安装服务运行依赖 (pip install -e .[service])"
	@echo "  test               运行全部 pytest 测试"
	@echo "  lint               运行 ruff 代码检查"
	@echo "  typecheck          运行 mypy 类型检查"
	@echo "  build              构建 Docker 镜像"
	@echo "  run                启动 docker compose 服务"
	@echo "  clean              清理缓存、构建产物和 Python 中间文件"

# 安装开发环境
install:
	pip install -e ".[dev]"

# 安装服务环境
install-service:
	pip install -e ".[service]"

# 运行测试
test:
	pytest tests/ -v

# 代码检查
lint:
	ruff check src/ tests/

# 类型检查
typecheck:
	mypy src/

# 构建 Docker 镜像
build:
	docker build -t docconv:latest .

# 启动 compose 服务
run:
	docker compose up -d

# 清理
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	rm -rf .cache/ .pytest_cache/ build/ dist/ *.egg-info/
	docker system prune -f 2>/dev/null || true
