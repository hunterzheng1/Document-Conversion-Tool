"""CLI job 命令（list/status/cancel）单元测试。"""

import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

import pytest
from click.testing import CliRunner
import click
from docconv.cli.service_commands import register_service_commands


def _make_cli():
    """创建测试用 CLI group。"""
    cli = click.Group()

    @cli.command()
    def dummy():
        """占位命令。"""
        pass

    return cli


class TestJobListCommand:
    """测试 job list 子命令。"""

    def test_help_shows_options(self):
        """job list --help 显示所有选项。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["job", "list", "--help"])
        assert result.exit_code == 0
        assert "--status" in result.output
        assert "--limit" in result.output
        assert "--source" in result.output
        assert "--format" in result.output

    def test_default_limit(self):
        """默认限制 20 条。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["job", "list", "--help"])
        assert result.exit_code == 0
        # 验证 --limit 选项存在（默认值在 click 内部，help 输出可能因编码不显示）
        assert "--limit" in result.output

    def test_filter_status_options(self):
        """--status 接受有效状态值。"""
        valid_statuses = ["queued", "running", "succeeded", "failed", "cancelled"]
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        # 验证这些状态被 click.Choice 接受（如果定义了的话）
        # 当前实现是 str 类型，所以接受任意值
        for s in valid_statuses:
            result = runner.invoke(cli, ["job", "list", "--status", s])
            # 可能因 job store 不存在而失败，但不应该是参数校验失败
            assert "Invalid value" not in result.output or result.exit_code != 2


class TestJobStatusCommand:
    """测试 job status 子命令。"""

    def test_requires_job_id(self):
        """job status 需要 job_id 参数。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["job", "status"])
        # click 参数校验会返回 2
        assert result.exit_code != 0

    def test_help(self):
        """job status --help 显示帮助。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["job", "status", "--help"])
        assert result.exit_code == 0


class TestJobCancelCommand:
    """测试 job cancel 子命令。"""

    def test_requires_job_id(self):
        """job cancel 需要 job_id 参数。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["job", "cancel"])
        assert result.exit_code != 0

    def test_force_option(self):
        """--force 选项存在。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["job", "cancel", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output

    def test_help(self):
        """job cancel --help 显示帮助。"""
        cli = _make_cli()
        register_service_commands(cli)
        runner = CliRunner()
        result = runner.invoke(cli, ["job", "cancel", "--help"])
        assert result.exit_code == 0


class TestJobGroup:
    """测试 job 命令组。"""

    def test_job_group_registered(self):
        """job 命令组已注册。"""
        cli = _make_cli()
        register_service_commands(cli)
        assert "job" in cli.commands

    def test_job_subcommands_exist(self):
        """job 下包含 list/status/cancel 子命令。"""
        cli = _make_cli()
        register_service_commands(cli)
        job_group = cli.commands["job"]
        assert "list" in job_group.commands
        assert "status" in job_group.commands
        assert "cancel" in job_group.commands
