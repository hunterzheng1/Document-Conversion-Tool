"""验证 pyproject.toml 包元数据、依赖、extras、entry points 是否符合 spec 要求。"""

import os
import subprocess
import sys

# pyproject.toml 在项目根目录（tests/ 上一级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pyproject_path():
    return os.path.join(PROJECT_ROOT, "pyproject.toml")


def _read_utf8(path: str) -> str:
    """读取文件，使用 UTF-8 编码。"""
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestPyprojectMetadata:
    """验证 pyproject.toml 基本元数据。"""

    def test_file_exists(self):
        """pyproject.toml 文件存在。"""
        assert os.path.exists(_pyproject_path()), "pyproject.toml 不存在"

    def test_pip_installable(self):
        """pip install -e . 可安装。"""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", PROJECT_ROOT],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"pip install -e . 失败: {result.stderr}"

    def test_docconv_command_available(self):
        """安装后 docconv 命令可用。"""
        result = subprocess.run(
            [sys.executable, "-m", "docconv.cli.main", "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"docconv --help 不可用: {result.stderr}"
        assert "PDF" in result.stdout or "转换" in result.stdout

    def test_version_matches(self):
        """包版本与 __version__ 一致。"""
        from docconv import __version__
        assert __version__ == "1.0.0"


class TestPyprojectExtras:
    """验证 optional-dependencies extras。"""

    def test_service_extra_in_toml(self):
        """pyproject.toml 包含 service extra。"""
        content = _read_utf8(_pyproject_path())
        assert "service" in content
        assert "fastapi" in content.lower()
        assert "uvicorn" in content.lower()

    def test_dev_extra_in_toml(self):
        """pyproject.toml 包含 dev extra。"""
        content = _read_utf8(_pyproject_path())
        assert "dev" in content
        assert "pytest" in content.lower()

    def test_integrations_extra_in_toml(self):
        """pyproject.toml 包含 integrations extra。"""
        content = _read_utf8(_pyproject_path())
        assert "integrations" in content

    def test_service_extra_install(self):
        """pip install -e ".[service]" 安装成功。"""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", f"{PROJECT_ROOT}[service]"],
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, f"pip install .[service] 失败: {result.stderr}"

    def test_dev_extra_install(self):
        """pip install -e ".[dev]" 安装成功。"""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", f"{PROJECT_ROOT}[dev]"],
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, f"pip install .[dev] 失败: {result.stderr}"

    def test_serve_command_help(self):
        """service extras 安装后 docconv serve --help 可用。"""
        result = subprocess.run(
            [sys.executable, "-m", "docconv.cli.main", "serve", "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"docconv serve --help 不可用: {result.stderr}"

    def test_worker_command_help(self):
        """service extras 安装后 docconv worker --help 可用。"""
        result = subprocess.run(
            [sys.executable, "-m", "docconv.cli.main", "worker", "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"docconv worker --help 不可用: {result.stderr}"

    def test_integrations_extra_install(self):
        """pip install -e ".[integrations]" 安装成功。"""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", f"{PROJECT_ROOT}[integrations]"],
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, f"pip install .[integrations] 失败: {result.stderr}"

    def test_build_system_setuptools(self):
        """build-system 使用 setuptools。"""
        content = _read_utf8(_pyproject_path())
        assert "setuptools" in content

    def test_entry_point(self):
        """CLI entry point 指向 docconv.cli.main:main。"""
        content = _read_utf8(_pyproject_path())
        assert "docconv.cli.main:main" in content

    def test_python_version_constraint(self):
        """requires-python >= 3.10。"""
        content = _read_utf8(_pyproject_path())
        assert ">=3.10" in content or ">= 3.10" in content


class TestRequirementsFiles:
    """验证 requirements 文件（base/prod/dev）。"""

    def test_requirements_base_exists(self):
        """requirements.txt 存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "requirements.txt"))

    def test_requirements_service_exists(self):
        """requirements-service.txt 存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "requirements-service.txt"))

    def test_requirements_dev_exists(self):
        """requirements-dev.txt 存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "requirements-dev.txt"))

    def test_base_has_click(self):
        """requirements.txt 包含 click。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "requirements.txt"))
        assert "click" in content.lower()

    def test_base_has_pyyaml(self):
        """requirements.txt 包含 pyyaml。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "requirements.txt"))
        assert "pyyaml" in content.lower() or "PyYAML" in content

    def test_service_has_fastapi(self):
        """requirements-service.txt 包含 fastapi。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "requirements-service.txt"))
        assert "fastapi" in content.lower()

    def test_service_has_uvicorn(self):
        """requirements-service.txt 包含 uvicorn。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "requirements-service.txt"))
        assert "uvicorn" in content.lower()

    def test_service_references_base(self):
        """requirements-service.txt 引用 requirements.txt。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "requirements-service.txt"))
        assert "-r requirements.txt" in content

    def test_dev_references_base_and_service(self):
        """requirements-dev.txt 引用 base 和 service。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "requirements-dev.txt"))
        assert "-r requirements.txt" in content
        assert "-r requirements-service.txt" in content

    def test_dev_has_pytest(self):
        """requirements-dev.txt 包含 pytest。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "requirements-dev.txt"))
        assert "pytest" in content.lower()

    def test_dev_has_ruff(self):
        """requirements-dev.txt 包含 ruff。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "requirements-dev.txt"))
        assert "ruff" in content.lower()

    def test_version_consistency_with_pyproject(self):
        """requirements 文件中的版本约束与 pyproject.toml 一致。"""
        pyproject = _read_utf8(_pyproject_path())
        base_req = _read_utf8(os.path.join(PROJECT_ROOT, "requirements.txt"))
        assert "click>=8.1" in pyproject or "click>=8.1" in base_req
        svc_req = _read_utf8(os.path.join(PROJECT_ROOT, "requirements-service.txt"))
        assert "fastapi>=0.110" in pyproject or "fastapi>=0.110" in svc_req


class TestGitignoreAndDockerignore:
    """验证 .gitignore 和 .dockerignore 规则。"""

    def test_gitignore_exists(self):
        """.gitignore 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, ".gitignore"))

    def test_gitignore_excludes_env(self):
        """.gitignore 排除 .env* 文件。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".gitignore"))
        assert ".env" in content

    def test_gitignore_excludes_data(self):
        """.gitignore 排除 .data/ 目录。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".gitignore"))
        assert ".data/" in content

    def test_gitignore_excludes_cache(self):
        """.gitignore 排除 .cache/ 目录。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".gitignore"))
        assert ".cache/" in content

    def test_gitignore_excludes_docconv_runtime(self):
        """.gitignore 排除 .docconv_* 运行时数据。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".gitignore"))
        assert ".docconv_" in content

    def test_gitignore_excludes_sqlite(self):
        """.gitignore 排除 *.sqlite3 文件。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".gitignore"))
        assert "*.sqlite3" in content

    def test_dockerignore_exists(self):
        """.dockerignore 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, ".dockerignore"))

    def test_dockerignore_excludes_env(self):
        """.dockerignore 排除 .env*（防泄露）。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".dockerignore"))
        assert ".env" in content

    def test_dockerignore_excludes_data(self):
        """.dockerignore 排除 .data/、.cache/、*.sqlite3（数据不入库）。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".dockerignore"))
        assert ".data/" in content
        assert ".cache/" in content
        assert "*.sqlite3" in content

    def test_dockerignore_excludes_dev_dirs(self):
        """.dockerignore 排除开发目录。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".dockerignore"))
        assert ".git/" in content
        assert "tests/" in content
        assert ".claude/" in content
        assert "openspec/" in content


class TestEnvExample:
    """验证 .env.example 环境变量模板。"""

    def test_env_example_exists(self):
        """.env.example 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, ".env.example"))

    def test_env_has_anthropic_key(self):
        """.env.example 包含 ANTHROPIC_API_KEY。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".env.example"))
        assert "ANTHROPIC_API_KEY" in content

    def test_env_has_openai_key(self):
        """.env.example 包含 OPENAI_API_KEY。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".env.example"))
        assert "OPENAI_API_KEY" in content

    def test_env_has_storage_root(self):
        """.env.example 包含 STORAGE_ROOT。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".env.example"))
        assert "STORAGE_ROOT" in content

    def test_env_has_server_host(self):
        """.env.example 包含 SERVER_HOST。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".env.example"))
        assert "SERVER_HOST" in content

    def test_env_has_server_port(self):
        """.env.example 包含 SERVER_PORT。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".env.example"))
        assert "SERVER_PORT" in content

    def test_env_has_log_level(self):
        """.env.example 包含 LOG_LEVEL。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".env.example"))
        assert "LOG_LEVEL" in content

    def test_env_no_real_secrets(self):
        """.env.example 不包含真实密钥。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, ".env.example"))
        # 检查不包含常见的真实 key 模式
        assert "sk-" not in content or "your-key" in content.lower()
        assert "pk-" not in content or "your-key" in content.lower()


class TestDockerfile:
    """验证 Dockerfile 容器构建配置。"""

    def test_dockerfile_exists(self):
        """Dockerfile 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "Dockerfile"))

    def test_uses_slim_base(self):
        """使用 python:3.10-slim 基础镜像。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Dockerfile"))
        assert "python:3.10-slim" in content

    def test_multistage_build(self):
        """多阶段构建（builder + runtime）。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Dockerfile"))
        assert "AS builder" in content
        assert "AS runtime" in content

    def test_non_root_user(self):
        """创建非 root 用户 docconv。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Dockerfile"))
        assert "useradd" in content or "useradd" in content.lower()
        assert "USER docconv" in content

    def test_healthcheck(self):
        """配置 HEALTHCHECK。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Dockerfile"))
        assert "HEALTHCHECK" in content
        assert "/api/v1/health" in content

    def test_exposes_port(self):
        """暴露端口 8000。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Dockerfile"))
        assert "EXPOSE 8000" in content

    def test_default_cmd_serve(self):
        """默认 CMD 为 serve。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Dockerfile"))
        assert 'CMD ["serve"]' in content or 'CMD ["docconv", "serve"]' in content

    def test_does_not_copy_env(self):
        """Dockerfile 不显式复制 .env 文件。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Dockerfile"))
        # COPY 指令不应包含 .env
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("COPY"):
                assert ".env" not in stripped, f"Dockerfile COPY 不应包含 .env: {stripped}"

    def test_sets_storage_root_env(self):
        """设置 STORAGE_ROOT 环境变量。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Dockerfile"))
        assert "STORAGE_ROOT" in content


class TestDockerCompose:
    """验证 docker-compose.yml.example 示例部署配置。"""

    def test_docker_compose_exists(self):
        """docker-compose.yml.example 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))

    def test_has_api_service(self):
        """包含 api 服务。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))
        assert "api:" in content

    def test_has_worker_service(self):
        """包含 worker 服务。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))
        assert "worker:" in content

    def test_api_exposes_port(self):
        """api 服务暴露端口 8000。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))
        assert "8000" in content

    def test_shared_volume(self):
        """api 和 worker 共享 docconv-data volume。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))
        assert "docconv-data" in content

    def test_healthcheck_configured(self):
        """api 服务配置 healthcheck。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))
        assert "healthcheck:" in content

    def test_uses_env_file(self):
        """使用 .env 文件注入环境变量。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))
        assert "env_file:" in content

    def test_no_real_secrets(self):
        """示例配置中无真实密钥。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))
        # 检查不包含常见的真实 key 模式
        assert "sk-" not in content
        assert "pk-" not in content

    def test_has_volumes_section(self):
        """声明 volumes 区块。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "docker-compose.yml.example"))
        assert "volumes:" in content


class TestSystemdServices:
    """验证 systemd 服务单元文件。"""

    def test_api_service_exists(self):
        """docconv-api.service 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-api.service"))

    def test_worker_service_exists(self):
        """docconv-worker.service 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-worker.service"))

    def test_api_non_root_user(self):
        """API 服务以非 root 用户运行。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-api.service"))
        assert "User=docconv" in content

    def test_worker_non_root_user(self):
        """Worker 服务以非 root 用户运行。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-worker.service"))
        assert "User=docconv" in content

    def test_api_restart_always(self):
        """API 服务崩溃后自动重启。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-api.service"))
        assert "Restart=always" in content

    def test_worker_restart_always(self):
        """Worker 服务崩溃后自动重启。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-worker.service"))
        assert "Restart=always" in content

    def test_api_after_network(self):
        """API 服务在网络就绪后启动。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-api.service"))
        assert "After=network.target" in content

    def test_worker_after_api(self):
        """Worker 服务在 API 之后启动。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-worker.service"))
        assert "docconv-api.service" in content

    def test_api_wanted_by(self):
        """API 服务支持开机自启。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-api.service"))
        assert "WantedBy=multi-user.target" in content

    def test_worker_wanted_by(self):
        """Worker 服务支持开机自启。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-worker.service"))
        assert "WantedBy=multi-user.target" in content

    def test_api_env_file(self):
        """API 服务读取环境变量文件。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-api.service"))
        assert "EnvironmentFile=" in content

    def test_api_serve_command(self):
        """API 服务运行 docconv serve。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-api.service"))
        assert "docconv serve" in content

    def test_worker_command(self):
        """Worker 服务运行 docconv worker。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "deploy/systemd/docconv-worker.service"))
        assert "docconv worker" in content


class TestMakefile:
    """验证 Makefile 常见操作命令。"""

    def test_makefile_exists(self):
        """Makefile 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "Makefile"))

    def test_phony_declared(self):
        """使用 .PHONY 声明伪目标。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert ".PHONY:" in content

    def test_install_target(self):
        """包含 install 目标。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert "install:" in content

    def test_install_service_target(self):
        """包含 install-service 目标。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert "install-service:" in content

    def test_test_target(self):
        """包含 test 目标。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert "test:" in content
        assert "pytest" in content

    def test_lint_target(self):
        """包含 lint 目标。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert "lint:" in content
        assert "ruff" in content

    def test_build_target(self):
        """包含 build 目标（docker build）。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert "build:" in content
        assert "docker build" in content

    def test_clean_target(self):
        """包含 clean 目标。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert "clean:" in content
        assert "__pycache__" in content

    def test_help_target(self):
        """包含 help 目标。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert "help:" in content

    def test_default_goal(self):
        """默认目标为 help。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "Makefile"))
        assert ".DEFAULT_GOAL := help" in content


class TestVerificationScripts:
    """验证 Docker 和 pip install 验证脚本。"""

    def test_verify_docker_exists(self):
        """verify-docker.sh 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "scripts/verify-docker.sh"))

    def test_verify_install_exists(self):
        """verify-install.sh 文件存在。"""
        assert os.path.exists(os.path.join(PROJECT_ROOT, "scripts/verify-install.sh"))

    def test_verify_docker_has_shebang(self):
        """verify-docker.sh 有 bash shebang。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-docker.sh"))
        assert content.startswith("#!/bin/bash")

    def test_verify_install_has_shebang(self):
        """verify-install.sh 有 bash shebang。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-install.sh"))
        assert content.startswith("#!/bin/bash")

    def test_verify_docker_has_set_e(self):
        """verify-docker.sh 使用 set -euo pipefail。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-docker.sh"))
        assert "set -euo pipefail" in content

    def test_verify_install_has_set_e(self):
        """verify-install.sh 使用 set -euo pipefail。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-install.sh"))
        assert "set -euo pipefail" in content

    def test_verify_docker_checks_non_root(self):
        """verify-docker.sh 检查非 root 用户。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-docker.sh"))
        assert "docconv" in content and "whoami" in content

    def test_verify_docker_checks_env(self):
        """verify-docker.sh 验证 .env 不在镜像内。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-docker.sh"))
        assert ".env" in content

    def test_verify_docker_checks_size(self):
        """verify-docker.sh 检查镜像大小 < 500MB。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-docker.sh"))
        assert "500" in content

    def test_verify_docker_cleans_up(self):
        """verify-docker.sh 清理测试镜像。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-docker.sh"))
        assert "docker rmi" in content or "rmi" in content

    def test_verify_install_tests_base(self):
        """verify-install.sh 测试基础安装。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-install.sh"))
        assert "docconv --help" in content

    def test_verify_install_tests_service(self):
        """verify-install.sh 测试 service extras。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-install.sh"))
        assert "[service]" in content
        assert "docconv serve" in content
        assert "docconv worker" in content

    def test_verify_install_tests_dev(self):
        """verify-install.sh 测试 dev extras。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-install.sh"))
        assert "[dev]" in content
        assert "pytest" in content
        assert "ruff" in content

    def test_verify_install_tests_integrations(self):
        """verify-install.sh 测试 integrations extras。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-install.sh"))
        assert "[integrations]" in content

    def test_verify_install_uses_venv(self):
        """verify-install.sh 使用独立虚拟环境。"""
        content = _read_utf8(os.path.join(PROJECT_ROOT, "scripts/verify-install.sh"))
        assert "venv" in content

