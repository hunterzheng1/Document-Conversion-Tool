"""CLI 服务命令（serve/worker）单元测试。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

import pytest
from click.testing import CliRunner
from docconv.cli.service_commands import (
    register_service_commands,
    _ensure_uvicorn,
    _load_and_validate_config,
)
from docconv.cli.errors import (
    CLIInvalidArgumentError,
    CLIInvalidConfigError,
    CLIExecutionError,
)
import click


def _make_cli():
    """创建测试用 CLI group。"""
    cli = click.Group()

    @cli.command()
    def dummy():
        """占位命令。"""
        pass

    return cli


class TestEnsureUvicorn:
    """测试 uvicorn 检查。"""

    def test_uvicorn_available(self):
        """uvicorn 已安装时不抛异常。"""
        try:
            import uvicorn  # noqa: F401
            _ensure_uvicorn()  # 不应抛异常
        except ImportError:
            pytest.skip("uvicorn not installed in test environment")


class TestServeCommand:
    """测试 serve 命令。"""

    def test_port_out_of_range_low(self):
        """port < 1 时抛出 CLI1001。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--port", "0"])
        assert result.exit_code != 0
        # 异常信息通过 exception 属性检查
        assert result.exception is not None
        assert "CLI1001" in str(result.exception)

    def test_port_out_of_range_high(self):
        """port > 65535 时抛出 CLI1001。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--port", "70000"])
        assert result.exit_code != 0
        assert result.exception is not None
        assert "CLI1001" in str(result.exception)

    def test_uvicorn_not_installed(self):
        """uvicorn 未安装时输出安装提示。

        注意：当前测试环境可能已安装 uvicorn，此测试仅验证错误码存在。
        """
        # 直接测试 CLIExecutionError
        exc = CLIExecutionError("uvicorn 未安装")
        assert "CLI5001" in str(exc)
        assert "uvicorn" in str(exc)


class TestWorkerCommand:
    """测试 worker 命令。"""

    def test_worker_id_override(self):
        """--worker-id 覆盖默认值。

        验证 worker 命令接受 --worker-id 参数。
        """
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        # worker 命令需要 storage.root 存在，我们模拟测试参数解析
        # 由于 worker.run() 会阻塞，我们只验证参数接受
        result = runner.invoke(cli, ["worker", "--help"])
        assert result.exit_code == 0
        assert "--worker-id" in result.output

    def test_max_jobs_parameter(self):
        """--max-jobs 参数接受。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["worker", "--help"])
        assert result.exit_code == 0
        assert "--max-jobs" in result.output


class TestServeStartupMessage:
    """测试 serve 启动消息格式。"""

    def test_startup_message_format(self):
        """验证启动消息格式（通过 CLI group 检查参数）。"""
        cli = _make_cli()
        register_service_commands(cli)
        serve_cmd = cli.commands["serve"]
        assert serve_cmd.name == "serve"
        params = {p.name for p in serve_cmd.params}
        assert "host" in params
        assert "port" in params
        assert "reload" in params
        assert "config" in params
        assert "log_level" in params
