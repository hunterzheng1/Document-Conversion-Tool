# docconv 智能化 PDF 转 Markdown 文档器

## 概述

docconv 是将 PDF 文档智能转换为 Markdown 格式的命令行工具。
通过 AI 视觉模型分析页面内容，自动识别文本、表格、流程图
等元素，并生成结构化 Markdown 输出。

### 核心特性

- **智能页面分类**：自动识别纯文本页、图片表格页、流程图、示意图等页面类型
- **AI 视觉分析**：支持 Anthropic 和 OpenAI 兼容 API，对非纯文本页面进行视觉理解
- **表格转 Markdown**：将 PDF 表格转换为 Markdown 表格格式
- **流程图转 Mermaid**：将流程图/示意图转换为 Mermaid 语法
- **断点续传**：支持中断后从上次进度继续转换
- **缓存机制**：已处理页面结果缓存，避免重复调用 AI
- **内容验证**：对转换结果进行质量校验

## 环境要求

- Python >= 3.10
- 需要配置 AI 模型 API Key（`ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`）

## 安装

```bash
pip install docconv
```

## 使用方法

### 转换 PDF

```bash
docconv convert input.pdf -o output.md
```

### 常用选项

| 选项 | 说明 |
| ----- | ----- |
| `-o, --output` | 输出 Markdown 文件路径（必填） |
| `-c, --config` | 配置文件路径 |
| `--model-profile` | 模型档位：auto / primary / economy / fallback |
| `--dpi` | 页面渲染 DPI（默认 200） |
| `--concurrency` | 并发页面数（默认 2） |
| `--dry-run` | 仅分析 PDF，不调用 AI |
| `--no-cache` | 禁用缓存 |
| `--no-resume` | 从头开始，忽略断点 |
| `--sensitive` | 敏感模式：禁用磁盘缓存，日志脱敏 |
| `--force` | 覆盖已存在的输出文件 |

### 其他命令

```bash
# 查看 PDF 基本信息
docconv info input.pdf

# 查看转换进度
docconv status input.pdf

# 从断点续传
docconv resume input.pdf -o output.md

# 缓存管理
docconv cache stats
docconv cache clear

# 模型管理
docconv models list
docconv models check
```

## 项目结构

```text
src/docconv/
├── cli/            # CLI 命令行界面
├── core/           # 核心转换逻辑与类型定义
├── parser/         # PDF 解析器
├── processor/      # 页面处理器（分类、文本、图片、表格、Mermaid）
├── validator/      # 内容验证器
├── ai/             # AI 模型集成（Anthropic / OpenAI 兼容）
├── infra/          # 基础设施（缓存、状态、指标、日志）
└── output/         # 输出写入器（Markdown + 报告）
```

## License

MIT
