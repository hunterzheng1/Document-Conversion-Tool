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
@click.pass_context
def main(ctx):
    """PDF 转 Markdown 文档转换工具。"""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config("config/config.yaml")


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("-o", "--output", required=True, help="输出 Markdown 文件路径")
@click.option("-c", "--config", default=None, help="配置文件路径")
@click.option("--model-profile", type=click.Choice(["auto", "primary", "economy", "fallback"]), default="auto",
              help="模型档位选择")
@click.option("--dpi", type=int, default=200, help="页面渲染 DPI")
@click.option("--concurrency", type=int, default=2, help="并发页面数")
@click.option("--dry-run", is_flag=True, help="仅分析 PDF，不调用 AI，不写 Markdown")
@click.option("--no-cache", is_flag=True, help="禁用缓存查询和写入")
@click.option("--no-resume", is_flag=True, help="忽略历史状态，从头开始")
@click.option("--no-validation", is_flag=True, help="跳过内容验证")
@click.option("--sensitive", is_flag=True, help="敏感模式：禁用磁盘 AI 缓存，日志脱敏")
@click.option("--force", is_flag=True, help="覆盖已存在的输出文件")
@click.option("-v", "--verbose", is_flag=True, help="详细日志输出")
@click.pass_context
def convert(ctx, input_file, output, config, model_profile, dpi, concurrency,
            dry_run, no_cache, no_resume, no_validation, sensitive, force, verbose):
    """执行 PDF → Markdown 转换。"""
    cfg = ctx.obj["config"]
    if config:
        cfg = load_config(config)

    # 应用命令行选项覆盖配置
    if no_cache:
        cfg.setdefault("cache", {})["enabled"] = False
    if sensitive:
        cfg.setdefault("cache", {})["sensitive_mode"] = True
    if verbose:
        cfg.setdefault("logging", {})["level"] = "DEBUG"

    if dry_run:
        # dry-run 模式：仅分析 PDF
        from docconv.parser.pdf_parser import PDFParser
        with PDFParser(input_file) as parser:
            pages = parser.get_page_count()
            meta = parser.get_metadata()
            click.echo(f"文件: {input_file}")
            click.echo(f"页数: {pages}")
            click.echo(f"标题: {meta.get('title', 'N/A')}")
            click.echo(f"作者: {meta.get('author', 'N/A')}")
            click.echo(f"加密: {meta.get('encrypted', False)}")
            click.echo(f"大小: {meta.get('size_bytes', 0)} 字节")
            click.echo(f"\n预估: 纯文本页约 0 Token，图片页约 2000 Token/页")
            click.echo(f"模型档位: {model_profile}")
        return

    if not force and os.path.exists(output):
        click.echo(f"输出文件已存在: {output}，使用 --force 覆盖", err=True)
        raise SystemExit(1)

    converter = DocumentConverter(cfg)
    resume = not no_resume

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
    if result.failed_pages > 0:
        click.echo(f"失败: {result.failed_pages} 页")


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("-o", "--output", default=None, help="输出文件路径")
@click.pass_context
def resume(ctx, input_file, output):
    """从断点续传转换。"""
    ctx.invoke(convert, input_file=input_file, output=output, no_resume=False, force=True)


@main.command()
@click.argument("input_file", type=click.Path(exists=True), required=False)
@click.pass_context
def status(ctx, input_file):
    """显示转换进度。"""
    cfg = ctx.obj["config"]
    state_mgr = StateManager(cfg.get("state", {}))
    cache_mgr = CacheManager(cfg.get("cache", {}))

    if input_file:
        state = state_mgr.load(input_file)
        click.echo(f"文件: {state.file_path}")
        click.echo(f"状态: {state.status}")
        click.echo(f"总页数: {state.total_pages}")
        click.echo(f"已完成: {len(state.completed_pages)} 页")
        click.echo(f"失败: {len(state.failed_pages)} 页")
        click.echo(f"进度: {state.progress:.1%}")
        cache_stats = cache_mgr.get_stats()
        click.echo(f"缓存: {cache_stats['entries']} 条目，{cache_stats['total_size_mb']} MB")
    else:
        states = state_mgr.list_states()
        if not states:
            click.echo("无转换状态")
            return
        for s in states:
            click.echo(f"  {s.file_path}: {s.status} ({s.progress:.1%}) - {len(s.completed_pages)}/{s.total_pages} 页")


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.pass_context
def info(ctx, input_file):
    """显示 PDF 基本信息。"""
    from docconv.parser.pdf_parser import PDFParser
    try:
        with PDFParser(input_file) as parser:
            meta = parser.get_metadata()
            click.echo(f"文件: {input_file}")
            click.echo(f"页数: {meta.get('pages', 0)}")
            click.echo(f"大小: {meta.get('size_bytes', 0)} 字节")
            click.echo(f"标题: {meta.get('title', 'N/A')}")
            click.echo(f"作者: {meta.get('author', 'N/A')}")
            click.echo(f"加密: {meta.get('encrypted', False)}")
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        raise SystemExit(1)


@main.group()
@click.pass_context
def cache(ctx):
    """缓存管理。"""
    pass


@cache.command("stats")
@click.pass_context
def cache_stats(ctx):
    """显示缓存统计。"""
    cfg = ctx.obj["config"]
    cache_mgr = CacheManager(cfg.get("cache", {}))
    stats = cache_mgr.get_stats()
    click.echo(f"条目数: {stats['entries']}")
    click.echo(f"总大小: {stats['total_size_mb']} MB")
    click.echo(f"最近 24h 新增: {stats['recent_entries_24h']}")


@cache.command()
@click.pass_context
def clear(ctx):
    """清空缓存。"""
    cfg = ctx.obj["config"]
    cache_mgr = CacheManager(cfg.get("cache", {}))
    if click.confirm("确认清空所有缓存？"):
        cache_mgr.clear()
        click.echo("缓存已清空")


@main.group()
def models():
    """模型管理。"""
    pass


@models.command()
@click.pass_context
def list(ctx):
    """列出所有模型。"""
    cfg = ctx.obj["config"]
    models = cfg.get("models", {})
    if not models:
        click.echo("未配置模型")
        return
    for name, mconf in models.items():
        provider = mconf.get("provider", "unknown")
        model = mconf.get("model", "unknown")
        click.echo(f"  {name}: {provider} / {model}")


@models.command()
@click.pass_context
def check(ctx):
    """检查模型可用性。"""
    cfg = ctx.obj["config"]
    models = cfg.get("models", {})
    if not models:
        click.echo("未配置模型")
        return
    for name, mconf in models.items():
        provider = mconf.get("provider", "unknown")
        api_key_var = "ANTHROPIC_API_KEY" if "anthropic" in provider else "OPENAI_API_KEY"
        has_key = bool(os.environ.get(api_key_var))
        base_url = mconf.get("base_url", "默认" if not mconf.get("base_url") else mconf["base_url"])
        status = "✅" if has_key else "❌"
        click.echo(f"  {status} {name}: API Key={'已配置' if has_key else '未配置'}, base_url={base_url}")


if __name__ == "__main__":
    main()
