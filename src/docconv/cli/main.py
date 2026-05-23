"""CLI 入口：基于 click 的命令行界面。"""

from __future__ import annotations

import asyncio
import os
import sys

import click
import yaml

from docconv import __version__
from docconv.core.converter import DocumentConverter
from docconv.core.types import ConversionResult
from docconv.infra.state_manager import StateManager
from docconv.infra.cache_manager import CacheManager
from docconv.infra.logger import setup_logger
from docconv.output.markdown_writer import MarkdownWriter
from docconv.output.report_writer import ReportWriter

logger = setup_logger("docconv")


def load_config(config_path: str) -> dict:
    """加载配置文件。"""
    if not config_path or not os.path.exists(config_path):
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@click.group()
@click.version_option(version=__version__, prog_name="docconv")
@click.option("--config", "-c", default="config/config.yaml", help="配置文件路径")
@click.pass_context
def main(ctx, config):
    """PDF 转 Markdown 文档转换工具。"""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config)


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("-o", "--output", default=None, help="输出文件路径")
@click.option("--resume", is_flag=True, help="断点续传")
@click.pass_context
def convert(ctx, input_file, output, resume):
    """转换 PDF 文件为 Markdown。"""
    cfg = ctx.obj["config"]
    converter = DocumentConverter(cfg)

    async def _run():
        return await converter.convert(input_file, resume=resume)

    result = asyncio.run(_run())

    writer = MarkdownWriter(cfg.get("output", {}))
    out_path = writer.write(result, output)

    # 写入报告
    report_path = out_path.replace(".md", "_report.md")
    report_writer = ReportWriter()
    report_writer.write_report(result, report_path)

    click.echo(f"转换完成: {out_path}")
    click.echo(f"报告: {report_path}")
    click.echo(f"耗时: {result.duration_seconds:.1f}s")
    click.echo(f"成功: {result.success_pages}/{result.total_pages} 页")


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("-o", "--output", default=None, help="输出文件路径")
@click.pass_context
def resume(ctx, input_file, output):
    """断点续传转换。"""
    ctx.invoke(convert, input_file=input_file, output=output, resume=True)


@main.command()
@click.argument("input_file", type=click.Path(exists=True), required=False)
@click.pass_context
def status(ctx, input_file):
    """查看转换状态。"""
    cfg = ctx.obj["config"]
    state_mgr = StateManager(cfg.get("state", {}))

    if input_file:
        state = state_mgr.load(input_file)
        click.echo(f"文件: {state.file_path}")
        click.echo(f"状态: {state.status}")
        click.echo(f"进度: {state.progress:.1%}")
        click.echo(f"已完成: {len(state.completed_pages)}/{state.total_pages} 页")
    else:
        states = state_mgr.list_states()
        if not states:
            click.echo("无转换状态")
            return
        for s in states:
            click.echo(f"  {s.file_path}: {s.status} ({s.progress:.1%})")


@main.command()
@click.pass_context
def info(ctx):
    """显示工具信息。"""
    cfg = ctx.obj["config"]
    click.echo(f"docconv v{__version__}")
    click.echo(f"配置文件: config/config.yaml")
    click.echo(f"缓存目录: {cfg.get('cache', {}).get('cache_dir', '.cache/docconv')}")
    click.echo(f"状态目录: {cfg.get('state', {}).get('state_dir', '.state/docconv')}")


@main.command()
@click.option("--clear", is_flag=True, help="清空缓存")
@click.option("--size", is_flag=True, help="显示缓存大小")
@click.pass_context
def cache(ctx, clear, size):
    """缓存管理。"""
    cfg = ctx.obj["config"]
    cache_mgr = CacheManager(cfg.get("cache", {}))

    if clear:
        cache_mgr.clear()
        click.echo("缓存已清空")
    elif size:
        sz = cache_mgr.get_size()
        click.echo(f"缓存大小: {sz} 字节")
    else:
        sz = cache_mgr.get_size()
        click.echo(f"缓存大小: {sz} 字节")
        click.echo("使用 --clear 清空，--size 查看大小")


@main.command()
@click.pass_context
def models(ctx):
    """显示模型配置。"""
    cfg = ctx.obj["config"]
    models = cfg.get("models", {})

    if not models:
        click.echo("未配置模型")
        return

    for name, mconf in models.items():
        provider = mconf.get("provider", "unknown")
        model = mconf.get("model", "unknown")
        click.echo(f"  {name}: {provider} / {model}")


if __name__ == "__main__":
    main()
