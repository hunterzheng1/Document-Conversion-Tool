"""统一配置加载与归一化。

职责：
- 从 YAML 文件加载配置，兼容旧键名
- 提供 AppConfig dataclass，包含全部配置项和校验逻辑
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# 缓存配置归一化
# ---------------------------------------------------------------------------

CACHE_CONFIG_ERROR = "CA1001"
MIN_TTL_SECONDS = 86400
MAX_TTL_SECONDS = 31536000


class CacheConfigError(ValueError):
    """缓存配置异常。"""

    def __init__(self, message: str, error_code: str = CACHE_CONFIG_ERROR):
        self.error_code = error_code
        super().__init__(f"[{error_code}] {message}")


def normalize_cache_config(raw_config: dict | None = None) -> dict:
    """将外部配置归一化为 CacheManager 可消费的格式。

    负责：
    - path -> cache_dir 映射
    - ttl_days * 86400 -> ttl 转换
    - ttl 和 ttl_days 同时存在时优先使用 ttl
    - 校验 ttl 范围（86400 ~ 31536000 秒）
    - 校验 max_size_gb > 0
    - 校验 cache_dir 路径合法

    Args:
        raw_config: 原始缓存配置字典

    Returns:
        归一化后的配置字典，包含 cache_dir, ttl, max_size_gb,
        enabled, prompt_version, sensitive_mode

    Raises:
        CacheConfigError: 配置非法时抛出，错误码 CA1001
    """
    cfg = raw_config or {}

    # --- cache_dir 归一化 ---
    cache_dir = cfg.get("cache_dir") or cfg.get("path")
    if cache_dir is None:
        cache_dir = ".cache/docconv"
    cache_dir = str(cache_dir).strip()
    if not cache_dir:
        raise CacheConfigError("cache_dir 不能为空")
    if ".." in cache_dir:
        raise CacheConfigError(f"cache_dir 包含非法路径穿越: {cache_dir}")

    # --- ttl 归一化 ---
    ttl = cfg.get("ttl")
    if ttl is None:
        ttl_days = cfg.get("ttl_days", 14)
        ttl = int(ttl_days) * 86400
    else:
        ttl = int(ttl)

    if ttl < MIN_TTL_SECONDS or ttl > MAX_TTL_SECONDS:
        raise CacheConfigError(
            f"ttl 超出范围: {ttl} 秒，必须在 {MIN_TTL_SECONDS} ~ {MAX_TTL_SECONDS} 秒之间"
        )

    # --- max_size_gb 校验 ---
    max_size_gb = cfg.get("max_size_gb", 5)
    if not isinstance(max_size_gb, (int, float)) or max_size_gb <= 0:
        raise CacheConfigError(f"max_size_gb 必须大于 0，当前值: {max_size_gb}")

    return {
        "cache_dir": cache_dir,
        "ttl": ttl,
        "max_size_gb": float(max_size_gb),
        "enabled": cfg.get("enabled", True),
        "prompt_version": cfg.get("prompt_version", "v1"),
        "sensitive_mode": cfg.get("sensitive_mode", False),
    }


# ---------------------------------------------------------------------------
# 旧键名兼容映射
# ---------------------------------------------------------------------------
_LEGACY_KEY_MAP: dict[str, str] = {
    # 旧 cache 键 -> 新键
    "cache.path": "cache.cache_dir",
    "cache.ttl_days": "cache.ttl",
    # 旧 resume 键 -> 新键
    "resume.state_dir": "state.state_dir",
}


def _apply_legacy_mapping(raw: dict) -> dict:
    """将旧键名迁移到新键名，不删除旧键（向后兼容）。"""
    result = dict(raw)
    for legacy, new in _LEGACY_KEY_MAP.items():
        parts = legacy.split(".")
        value = raw
        for p in parts:
            if isinstance(value, dict) and p in value:
                value = value[p]
            else:
                value = None
                break
        if value is not None:
            new_parts = new.split(".")
            target = result
            for p in new_parts[:-1]:
                target = target.setdefault(p, {})
            target[new_parts[-1]] = value
    return result


def load_app_config(config_path: str | None = None) -> dict:
    """从 YAML 文件加载应用配置。

    参数:
        config_path: 配置文件路径。若为 None，优先取环境变量 DOCCONV_CONFIG，
                     回退到 config/config.yaml。

    返回:
        归一化后的配置字典。文件不存在时返回空字典，不抛异常。

    异常:
        ValueError: YAML 解析错误时抛出带明确消息的异常。
    """
    if config_path is None:
        config_path = os.environ.get("DOCCONV_CONFIG", "config/config.yaml")

    path = Path(config_path)
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 配置解析失败 ({config_path}): {exc}") from exc

    if raw is None or not isinstance(raw, dict):
        return {}

    return _apply_legacy_mapping(raw)


# ---------------------------------------------------------------------------
# AppConfig dataclass
# ---------------------------------------------------------------------------
@dataclass
class CacheConfig:
    """缓存配置。"""
    cache_dir: str = ".docconv/cache"
    ttl: int = 7
    enabled: bool = True


@dataclass
class ServerConfig:
    """服务配置。"""
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    log_level: str = "info"


@dataclass
class StateConfig:
    """断点续传状态配置。"""
    state_dir: str = ".docconv/state"


@dataclass
class JobsConfig:
    """任务管理配置。"""
    worker_id: str = ""
    db_path: str = ".docconv/jobs.db"
    max_running: int = 1
    poll_interval: float = 5.0

    def __post_init__(self):
        if not self.worker_id:
            self.worker_id = f"{socket.gethostname()}-{os.getpid()}"


@dataclass
class StorageConfig:
    """存储配置。"""
    root: str = ".docconv/storage"


@dataclass
class ModelsConfig:
    """AI 模型配置。"""
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    base_url: str = ""


@dataclass
class AppConfig:
    """应用统一配置。

    包含 design.md 9.1 节全部配置项。
    """
    server: ServerConfig = field(default_factory=ServerConfig)
    jobs: JobsConfig = field(default_factory=JobsConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    state: StateConfig = field(default_factory=StateConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)

    @classmethod
    def from_dict(cls, raw: dict) -> "AppConfig":
        """从原始配置字典创建 AppConfig。"""
        # 初始化 jobs 时设置默认 worker_id
        jobs_raw = raw.get("jobs", {})
        if not jobs_raw.get("worker_id"):
            jobs_raw["worker_id"] = f"{socket.gethostname()}-{os.getpid()}"

        cache_raw = raw.get("cache", {})
        state_raw = raw.get("state", {})
        server_raw = raw.get("server", {})
        storage_raw = raw.get("storage", {})
        models_raw = raw.get("models", {})

        return cls(
            server=ServerConfig(
                host=server_raw.get("host", "127.0.0.1"),
                port=int(server_raw.get("port", 8000)),
                reload=bool(server_raw.get("reload", False)),
                log_level=server_raw.get("log_level", "info"),
            ),
            jobs=JobsConfig(
                worker_id=jobs_raw.get("worker_id", ""),
                db_path=jobs_raw.get("db_path", ".docconv/jobs.db"),
                max_running=int(jobs_raw.get("max_running", 1)),
                poll_interval=float(jobs_raw.get("poll_interval", 5.0)),
            ),
            storage=StorageConfig(
                root=storage_raw.get("root", ".docconv/storage"),
            ),
            cache=CacheConfig(
                cache_dir=cache_raw.get("cache_dir", cache_raw.get("cache_dir", ".docconv/cache")),
                ttl=int(cache_raw.get("ttl", 7)),
                enabled=bool(cache_raw.get("enabled", True)),
            ),
            state=StateConfig(
                state_dir=state_raw.get("state_dir", ".docconv/state"),
            ),
            models=ModelsConfig(
                provider=models_raw.get("provider", "anthropic"),
                model=models_raw.get("model", "claude-sonnet-4-20250514"),
                api_key=models_raw.get("api_key", ""),
                base_url=models_raw.get("base_url", ""),
            ),
        )

    def validate(self) -> None:
        """校验配置有效性。

        异常:
            ValueError: port 越界（1-65535）或 storage.root 不存在。
        """
        if not (1 <= self.server.port <= 65535):
            raise ValueError(
                f"server.port 越界: {self.server.port}，必须在 1-65535 范围内"
            )

        storage_root = Path(self.storage.root)
        if not storage_root.exists():
            raise ValueError(
                f"storage.root 路径不存在: {self.storage.root}"
            )

    def to_dict(self) -> dict:
        """序列化为字典（不含 api_key）。"""
        return {
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "reload": self.server.reload,
                "log_level": self.server.log_level,
            },
            "jobs": {
                "worker_id": self.jobs.worker_id,
                "db_path": self.jobs.db_path,
                "max_running": self.jobs.max_running,
                "poll_interval": self.jobs.poll_interval,
            },
            "storage": {
                "root": self.storage.root,
            },
            "cache": {
                "cache_dir": self.cache.cache_dir,
                "ttl": self.cache.ttl,
                "enabled": self.cache.enabled,
            },
            "state": {
                "state_dir": self.state.state_dir,
            },
            "models": {
                "provider": self.models.provider,
                "model": self.models.model,
                "base_url": self.models.base_url,
            },
        }
