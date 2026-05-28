"""FastAPI 应用工厂。"""

from __future__ import annotations

import copy
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from docconv.service import ConversionJobService
from docconv.web.api.dependencies import configure_auth

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 默认 Server 配置
# ---------------------------------------------------------------------------

DEFAULT_SERVER_CONFIG: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8000,
    "api_prefix": "/api/v1",
    "upload": {
        "max_file_size_mb": 100,
        "allowed_extensions": [".pdf"],
    },
    "auth": {
        "enabled": False,
        "token": None,
    },
    "docs": {
        "enabled": True,
    },
    "job": {
        "storage_root": ".data/docconv",
        "retention_hours": 24,
        "max_running_jobs": 1,
        "max_queued_jobs": 20,
    },
}


def _merge_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """合并默认配置和用户覆盖。

    Args:
        overrides: 用户提供的配置覆盖

    Returns:
        合并后的完整配置
    """
    config = copy.deepcopy(DEFAULT_SERVER_CONFIG)

    if overrides:
        for key, value in overrides.items():
            if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                config[key].update(value)
            else:
                config[key] = value

    # 环境变量覆盖
    if os_port := os.environ.get("DOCONV_SERVER_PORT"):
        config["port"] = int(os_port)
    if os_host := os.environ.get("DOCONV_SERVER_HOST"):
        config["host"] = os_host

    return config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。

    启动时初始化 ConversionJobService，关闭时不执行特殊操作。
    """
    logger.info("API 服务启动中...")

    # 初始化 job service
    job_config = app.state.server_config.get("job", {})
    job_service = ConversionJobService(config=job_config)
    app.state.job_service = job_service

    # 配置认证
    auth_config = app.state.server_config.get("auth", {})
    configure_auth(
        enabled=auth_config.get("enabled", False),
        token=auth_config.get("token"),
    )

    logger.info(f"API 服务已启动，前缀: {app.state.server_config.get('api_prefix', '/api/v1')}")

    yield

    logger.info("API 服务正在关闭...")


def create_app(
    config: dict[str, Any] | None = None,
    job_service: ConversionJobService | None = None,
) -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    Args:
        config: Server 配置，不提供则使用默认值
        job_service: 预创建的 ConversionJobService 实例，不提供则自动创建

    Returns:
        配置好的 FastAPI 应用
    """
    server_config = _merge_config(config)

    # 文档页配置
    docs_config = server_config.get("docs", {})
    docs_enabled = docs_config.get("enabled", True)

    app = FastAPI(
        title="docconv API",
        description="PDF 转 Markdown 文档转换服务 HTTP API",
        version="1.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        lifespan=lifespan,
    )

    # 存储配置到 app.state
    app.state.server_config = server_config
    app.state.job_service = job_service

    # 注册中间件和异常处理器
    from docconv.web.api.middleware import setup_middleware
    setup_middleware(app)

    # 注册路由
    api_prefix = server_config.get("api_prefix", "/api/v1")

    from docconv.web.api.health import router as health_router
    from docconv.web.api.jobs import router as jobs_router
    from docconv.web.api.models_api import router as models_router

    # health 和 models 直接挂载到前缀下
    app.include_router(health_router, prefix=api_prefix)
    app.include_router(jobs_router, prefix=api_prefix)
    app.include_router(models_router, prefix=api_prefix)

    # 静态文件服务（Web UI）
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path
    static_dir = Path(__file__).resolve().parent.parent.parent / "server" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        # 根路径返回 index.html
        from fastapi.responses import HTMLResponse

        @app.get("/")
        async def serve_index():
            index_path = static_dir / "index.html"
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

    return app


# 方便直接运行: python -m docconv.web.api.app
if __name__ == "__main__":
    import uvicorn
    app = create_app()
    config = app.state.server_config
    uvicorn.run(
        app,
        host=config.get("host", "0.0.0.0"),
        port=config.get("port", 8000),
    )
