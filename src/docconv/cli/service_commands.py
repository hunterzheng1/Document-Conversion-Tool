"""CLI 服务化扩展命令：serve、worker、job list/status/cancel。"""

import os
import sys
from pathlib import Path

import click

from docconv.infra.config import load_app_config, AppConfig
from docconv.infra.logger import setup_logger
from docconv.cli.formatters import format_job_list, format_job_detail, format_job_output
from docconv.cli.errors import (
    CLIError,
    CLIInvalidArgumentError,
    CLIInvalidConfigError,
    CLIStateError,
    CLINotAllowedError,
    CLIExecutionError,
    redact_output,
    handle_cli_error,
)

logger = setup_logger(__name__)


def _load_and_validate_config(ctx: click.Context, config: str | None) -> AppConfig:
    """加载配置并校验 storage.root。"""
    raw = load_app_config(config)

    # 合并 CLI 选项覆盖
    if ctx:
        if ctx.params.get("host"):
            raw.setdefault("server", {})["host"] = ctx.params["host"]
        if ctx.params.get("port") is not None:
            raw.setdefault("server", {})["port"] = ctx.params["port"]

    cfg = AppConfig.from_dict(raw)

    # 校验 storage.root 存在
    storage_root = Path(cfg.storage.root)
    if not storage_root.exists():
        raise CLIInvalidConfigError(
            f"storage.root 路径不存在: {cfg.storage.root}，请先创建或使用 --config 指定有效配置"
        )

    return cfg


def _ensure_uvicorn() -> None:
    """检查 uvicorn 是否安装。"""
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        raise CLIExecutionError(
            "uvicorn 未安装，请运行: pip install docconv[service]"
        )


def _register_job_commands(cli: click.Group) -> None:
    """注册 job 管理子命令到 CLI group。"""

    job_group = click.Group(name="job", help="管理转换任务 (list/status/cancel)")

    @job_group.command("list")
    @click.option("--config", "-c", type=str, default=None, help="配置文件路径")
    @click.option("--status", "-s", type=str, default=None, help="过滤状态 (queued/running/succeeded/failed/cancelled)")
    @click.option("--limit", "-l", type=int, default=20, help="返回列表最大条数")
    @click.option("--source", type=str, default=None, help="过滤来源 (cli/web/telegram/feishu)")
    @click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table", help="输出格式")
    def job_list(config: str | None, status: str | None, limit: int, source: str | None, fmt: str) -> None:
        """列出转换任务。"""
        from docconv.service.job_store import SQLiteJobStore

        raw = load_app_config(config)
        storage_root = raw.get("storage", {}).get("root", ".docconv/storage")

        try:
            store = SQLiteJobStore(storage_root=storage_root)
        except Exception as e:
            click.echo(f"错误: 无法打开 job store: {redact_output(str(e))}", err=True)
            raise SystemExit(1) from e

        if status:
            jobs = store.list_jobs_by_status(status, limit=limit)
        else:
            jobs = store.list_recent_jobs(limit=limit)

        # 按 source 过滤
        if source:
            jobs = [j for j in jobs if j.source == source]

        job_dicts = [j.to_dict() for j in jobs]
        output = format_job_output(job_dicts, fmt=fmt)
        click.echo(output)

    @job_group.command("status")
    @click.argument("job_id")
    @click.option("--config", "-c", type=str, default=None, help="配置文件路径")
    def job_status(job_id: str, config: str | None) -> None:
        """查看任务详情。"""
        from docconv.service.job_store import SQLiteJobStore

        raw = load_app_config(config)
        storage_root = raw.get("storage", {}).get("root", ".docconv/storage")

        try:
            store = SQLiteJobStore(storage_root=storage_root)
        except Exception as e:
            click.echo(f"错误: 无法打开 job store: {redact_output(str(e))}", err=True)
            raise SystemExit(1) from e

        job = store.get_job(job_id)
        if not job:
            click.echo(f"任务不存在: {job_id}", err=True)
            raise SystemExit(1)

        click.echo(format_job_detail(job.to_dict()))

    @job_group.command("cancel")
    @click.argument("job_id")
    @click.option("--config", "-c", type=str, default=None, help="配置文件路径")
    @click.option("--force", is_flag=True, help="强制取消 running 任务")
    def job_cancel(job_id: str, config: str | None, force: bool) -> None:
        """取消转换任务。"""
        from docconv.service.conversion_job_service import ConversionJobService
        from docconv.service.job_store import SQLiteJobStore

        raw = load_app_config(config)
        storage_root = raw.get("storage", {}).get("root", ".docconv/storage")

        try:
            store = SQLiteJobStore(storage_root=storage_root)
        except Exception as e:
            click.echo(f"错误: 无法打开 job store: {redact_output(str(e))}", err=True)
            raise SystemExit(1) from e

        job = store.get_job(job_id)
        if not job:
            click.echo(f"任务不存在: {job_id}", err=True)
            raise SystemExit(1)

        current_status = job.status
        if current_status in ("succeeded", "failed"):
            click.echo(f"任务已完成/失败，无法取消: {job_id}", err=True)
            raise SystemExit(1)

        if current_status == "running" and not force:
            click.echo(f"任务正在运行，请使用 --force 强制取消: {job_id}", err=True)
            raise SystemExit(1)

        service = ConversionJobService(store, storage_root=storage_root)
        service.cancel_job(job_id)
        click.echo(f"任务 {job_id} 已取消")

    cli.add_command(job_group)


def register_service_commands(cli: click.Group) -> None:
    """注册所有服务化命令（serve、worker、job）到 CLI group。"""

    # --- serve 命令 ---
    @cli.command("serve")
    @click.option("--config", "-c", type=str, default=None, help="配置文件路径")
    @click.option("--host", type=str, default=None, help="监听地址")
    @click.option("--port", "-p", type=int, default=None, help="监听端口 (1-65535)")
    @click.option("--reload", is_flag=True, default=False, help="开发模式自动重载")
    @click.option("--log-level", type=str, default=None, help="日志级别")
    def serve_command(config: str | None, host: str | None, port: int | None, reload: bool, log_level: str | None) -> None:
        """启动 API 服务。"""
        # 端口校验
        if port is not None and not (1 <= port <= 65535):
            raise CLIInvalidArgumentError(f"端口 {port} 超出范围 (1-65535)")

        # 加载并校验配置
        raw = load_app_config(config)

        # 应用 CLI 覆盖
        if host:
            raw.setdefault("server", {})["host"] = host
        if port is not None:
            raw.setdefault("server", {})["port"] = port
        if log_level:
            raw.setdefault("server", {})["log_level"] = log_level
        if reload:
            raw.setdefault("server", {})["reload"] = True

        cfg = AppConfig.from_dict(raw)

        # 校验 storage.root
        storage_root = Path(cfg.storage.root)
        if not storage_root.exists():
            raise CLIInvalidConfigError(
                f"storage.root 路径不存在: {cfg.storage.root}"
            )

        # 检查 uvicorn
        _ensure_uvicorn()

        # 延迟导入 server
        try:
            from docconv.web.api.app import create_app
            import uvicorn

            app = create_app(storage_root=str(storage_root))

            click.echo(f"启动 API 服务: http://{cfg.server.host}:{cfg.server.port}")
            click.echo("按 Ctrl+C 停止服务。")

            uvicorn.run(
                app,
                host=cfg.server.host,
                port=cfg.server.port,
                reload=cfg.server.reload,
            )
        except ImportError:
            raise CLIExecutionError(
                "uvicorn 未安装，请运行: pip install docconv[service]"
            )

    # --- worker 命令 ---
    @cli.command("worker")
    @click.option("--config", "-c", type=str, default=None, help="配置文件路径")
    @click.option("--worker-id", type=str, default=None, help="Worker 标识")
    @click.option("--log-level", type=str, default=None, help="日志级别")
    @click.option("--max-jobs", type=int, default=None, help="并发上限")
    def worker_command(config: str | None, worker_id: str | None, log_level: str | None, max_jobs: int | None) -> None:
        """启动 Worker 进程，轮询并执行转换任务。"""
        import socket

        # 加载配置
        raw = load_app_config(config)

        # 校验 storage.root
        storage_root = raw.get("storage", {}).get("root", ".docconv/storage")
        if not Path(storage_root).exists():
            raise CLIInvalidConfigError(
                f"storage.root 路径不存在: {storage_root}"
            )

        # 生成或使用 worker_id
        if not worker_id:
            worker_id = f"{socket.gethostname()}-{os.getpid()}"

        try:
            from docconv.worker.local_worker import LocalWorker
            from docconv.service.job_store import SQLiteJobStore

            jobs_cfg = raw.get("jobs", {})
            store = SQLiteJobStore(storage_root=storage_root)
            worker = LocalWorker(
                worker_id=worker_id,
                job_store=store,
                storage_root=storage_root,
                poll_interval=jobs_cfg.get("poll_interval", 5.0),
                max_running=max_jobs or jobs_cfg.get("max_running", 1),
            )

            click.echo(f"启动 Worker: {worker_id}")
            click.echo("按 Ctrl+C 停止。")

            worker.run()
        except KeyboardInterrupt:
            click.echo("\nWorker 已停止。")

    # --- job 管理命令 ---
    _register_job_commands(cli)
