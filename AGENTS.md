# AGENTS.md

## Project Overview

docconv 是智能化 PDF 转 Markdown 工具。通过 AI 视觉模型分析
PDF 页面内容，自动识别文本、表格、流程图等元素，
生成结构化 Markdown 输出。

- **语言**：Python 3.10+
- **包名**：docconv（版本 1.0.0）
- **CLI 框架**：click
- **AI 模型**：支持 Anthropic 和 OpenAI 兼容 API
- **入口命令**：`docconv`

## Commands

### 安装与运行

```bash
pip install docconv
docconv convert input.pdf -o output.md
```

### 完整命令参考

| 命令 | 用途 |
| ----- | ----- |
| `docconv convert <file> -o <out>` | 执行 PDF → Markdown 转换 |
| `docconv resume <file> -o <out>` | 从断点续传转换 |
| `docconv status [file]` | 显示转换进度 |
| `docconv info <file>` | 显示 PDF 基本信息 |
| `docconv cache stats` | 显示缓存统计 |
| `docconv cache clear` | 清空缓存 |
| `docconv models list` | 列出所有模型配置 |
| `docconv models check` | 检查模型可用性 |

### 开发命令

```bash
# 运行全部测试（pytest）
pytest tests/

# 运行单个测试模块
pytest tests/test_core_types.py
```

## Development Rules

1. 所有源码位于 `src/docconv/` 下，
   遵循分层架构：
   cli → core → parser/processor/validator/ai → infra → output
2. 类型定义集中在 `src/docconv/core/types.py`
3. AI 模型调用必须通过 `ModelManager` 抽象基类，不可直接调用 API
4. 缓存和状态管理分别由 `CacheManager` 和 `StateManager` 负责
5. 异步处理使用 `asyncio.gather` 实现页面并行转换

## Validation

- 转换结果包含 `errors` 字段，任何页面处理失败都会记录
- 内容验证器（`content_validator.py`、`table_validator.py`、`mermaid_validator.py`）对输出质量进行校验
- `--dry-run` 模式可用于预检，不实际调用 AI

## Security

- 禁止在代码中硬编码 API Key，必须通过环境变量 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 传入
- `--sensitive` 模式下禁用磁盘缓存、日志脱敏
- 不读取或输出 `.env`、token、密钥文件

<!-- docsync:start -->
## DocSync

DocSync manages document synchronization for this project.
Use slash commands instead of manual CLI.

### DocSync Commands

- `/docsync:init` - Project initialization
- `/docsync:sync` - Daily document sync
- `/docsync:sync --fast` - Quick sync using git facts
- `/docsync:sync [file]` - Sync specific file(s)
- `/docsync:rules` - Maintain override rules

### Rules

- Detailed rules: `.docsync/rules/default.md`
- Override rules: `.docsync/rules/override.md`

### Safety Constraints

- Do NOT execute git commit, git push, npm publish
- Do NOT invent commands, ports, environment variables, APIs, or deployment steps
- Do NOT read or output .env, tokens, or secrets
- Mark uncertain content as TODO(review)

### Rule Priority

1. User explicit instruction in current conversation
2. Safety constraints
3. `.docsync/rules/override.md`
4. Repository facts
5. `.docsync/rules/default.md`
<!-- docsync:end -->