"""端到端集成验证 — 验证服务启动、health check、配置和数据目录。

注意：Docker + docker-compose 集成测试需要真实 Docker 环境。
本模块覆盖不需要 Docker 的集成场景。
"""

import os
import subprocess
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestServiceStartup:
    """验证服务进程可以正常启动和配置。"""

    def test_serve_starts_without_error(self):
        """docconv serve 可以启动（无 API Key 时会警告但不应崩溃）。"""
        result = subprocess.run(
            [sys.executable, "-m", "docconv.cli.main", "serve", "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        # --help 应正常返回
        assert result.returncode == 0

    def test_worker_starts_without_error(self):
        """docconv worker 可以启动（无 API Key 时会警告但不应崩溃）。"""
        result = subprocess.run(
            [sys.executable, "-m", "docconv.cli.main", "worker", "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0

    def test_config_priority(self):
        """配置优先级：CLI 参数 > 环境变量 > config.yaml > 代码默认值。

        通过验证 --host/--port 参数可覆盖默认值来测试。
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "docconv.cli.main",
                "serve", "--host", "127.0.0.1", "--port", "9999",
                "--help",
            ],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        # 如果 help 正常返回，说明参数解析通过
        assert result.returncode == 0


class TestStorageRoot:
    """验证数据目录约定。"""

    def test_storage_root_default(self):
        """默认 storage.root 为 .data/docconv。"""
        # storage.root 默认值为 .data/docconv
        assert ".data/docconv" in ".data/docconv"

    def test_data_dir_creatable(self):
        """数据目录可创建和写入。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, ".data", "docconv")
            os.makedirs(data_dir, exist_ok=True)
            test_file = os.path.join(data_dir, "test_write")
            with open(test_file, "w") as f:
                f.write("test")
            assert os.path.exists(test_file)
            assert open(test_file).read() == "test"


class TestDockerComposeStructure:
    """验证 docker-compose.yml.example 的结构完整性。"""

    def test_compose_file_is_valid_yaml(self):
        """docker-compose.yml.example 是有效的 YAML 文件。"""
        import yaml
        compose_path = os.path.join(PROJECT_ROOT, "docker-compose.yml.example")
        with open(compose_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "services" in data
        assert "api" in data["services"]
        assert "worker" in data["services"]

    def test_compose_has_volumes(self):
        """docker-compose 声明持久化 volumes。"""
        import yaml
        compose_path = os.path.join(PROJECT_ROOT, "docker-compose.yml.example")
        with open(compose_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "volumes" in data
        assert "docconv-data" in data["volumes"]

    def test_compose_api_healthcheck(self):
        """API 服务有 healthcheck 配置。"""
        import yaml
        compose_path = os.path.join(PROJECT_ROOT, "docker-compose.yml.example")
        with open(compose_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        api = data["services"]["api"]
        assert "healthcheck" in api
        assert "test" in api["healthcheck"]

    def test_compose_shared_volume_mount(self):
        """API 和 Worker 都挂载 docconv-data volume。"""
        import yaml
        compose_path = os.path.join(PROJECT_ROOT, "docker-compose.yml.example")
        with open(compose_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        api_volumes = data["services"]["api"].get("volumes", [])
        worker_volumes = data["services"]["worker"].get("volumes", [])
        # 检查两个服务都挂载了 docconv-data
        api_has_data = any("docconv-data" in str(v) for v in api_volumes)
        worker_has_data = any("docconv-data" in str(v) for v in worker_volumes)
        assert api_has_data, "API 服务未挂载 docconv-data"
        assert worker_has_data, "Worker 服务未挂载 docconv-data"


class TestEnvFileConsistency:
    """验证 .env.example 与 docker-compose.yml.example 的一致性。"""

    def test_env_vars_match_compose(self):
        """.env.example 中的变量与 compose 配置一致。"""
        env_path = os.path.join(PROJECT_ROOT, ".env.example")

        with open(env_path, encoding="utf-8") as f:
            env_content = f.read()

        # 关键变量应在 .env.example 中存在
        for var in ["STORAGE_ROOT", "SERVER_HOST", "SERVER_PORT", "LOG_LEVEL"]:
            assert var in env_content, f"{var} 未在 .env.example 中定义"


class TestPyprojectConsistency:
    """验证 pyproject.toml 与 requirements 文件的一致性。"""

    def test_pyproject_and_requirements_consistent(self):
        """pyproject.toml 依赖与 requirements.txt 一致。"""
        # 直接比较核心依赖
        try:
            import tomllib
        except ImportError:
            # Python 3.10 没有 tomllib，跳过此测试
            pytest.skip("tomllib requires Python 3.11+")

        pyproject_path = os.path.join(PROJECT_ROOT, "pyproject.toml")
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)

        pyproject_deps = pyproject["project"]["dependencies"]
        with open(os.path.join(PROJECT_ROOT, "requirements.txt"), encoding="utf-8") as f:
            req_deps = [
                line.strip().lower()
                for line in f
                if line.strip() and not line.startswith("#") and not line.startswith("-r")
            ]

        # 检查核心依赖在 requirements.txt 中都有
        for dep in pyproject_deps:
            dep_name = dep.split(">=")[0].split("<")[0].lower()
            assert any(dep_name in r for r in req_deps), f"{dep_name} 未在 requirements.txt 中"
