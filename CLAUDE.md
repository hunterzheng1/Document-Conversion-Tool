# CLAUDE.md

## Project Context

docconv 是智能化 PDF 转 Markdown 工具（Python 3.10+）。
通过 AI 视觉模型分析页面内容，自动识别文本、表格、
流程图等元素并生成 Markdown。

- **包名**：docconv（v1.0.0）
- **CLI 框架**：click
- **AI 模型**：Anthropic / OpenAI 兼容 API
- **入口**：`docconv convert <file> -o <out>`

## Common Commands

```bash
# 运行转换
docconv convert input.pdf -o output.md

# 查看信息
docconv info input.pdf
docconv status input.pdf

# 缓存与模型
docconv cache stats
docconv models check
```

## Directory Structure

```text
src/docconv/
├── cli/            # 命令行界面 (click)
├── core/           # 核心逻辑 + 类型定义
├── parser/         # PDF 解析
├── processor/      # 页面处理（分类、文本、图片、表格、Mermaid）
├── validator/      # 内容验证
├── ai/             # AI 模型集成
├── infra/          # 缓存、状态、指标、日志
└── output/         # Markdown 写入 + 报告
```

## @AGENTS.md

This project uses AGENTS.md as the cross-agent rules source.
See `AGENTS.md` for full command reference, development rules,
and security constraints.
