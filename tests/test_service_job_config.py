"""测试 JobConfig 配置模块。"""

import os
import pytest

from docconv.service.job_config import JobConfig


class TestJobConfigDefaults:
    def test_default_values(self):
        cfg = JobConfig()
        assert cfg.storage_root == ".data/docconv"
        assert cfg.retention_hours == 24
        assert cfg.max_running_jobs == 1
        assert cfg.max_queued_jobs == 20
        assert cfg.worker_poll_interval_seconds == 2
        assert cfg.enabled is True
        assert cfg.recover_running_on_start is True
        assert cfg.cleanup_expired is True
        assert cfg.recover_timeout_seconds == 600
        assert cfg.heartbeat_interval_seconds == 30

    def test_to_dict(self):
        cfg = JobConfig()
        d = cfg.to_dict()
        assert d["max_running_jobs"] == 1
        assert d["storage_root"] == ".data/docconv"


class TestJobConfigFromDict:
    def test_override_single(self):
        cfg = JobConfig.from_dict({"max_running_jobs": 4})
        assert cfg.max_running_jobs == 4
        assert cfg.max_queued_jobs == 20  # default unchanged

    def test_override_multiple(self):
        cfg = JobConfig.from_dict({
            "max_running_jobs": 3,
            "max_queued_jobs": 50,
            "retention_hours": 48,
        })
        assert cfg.max_running_jobs == 3
        assert cfg.max_queued_jobs == 50
        assert cfg.retention_hours == 48


class TestJobConfigValidation:
    def test_max_running_jobs_less_than_1(self):
        with pytest.raises(ValueError, match="max_running_jobs"):
            JobConfig(max_running_jobs=0)

    def test_max_queued_jobs_less_than_1(self):
        with pytest.raises(ValueError, match="max_queued_jobs"):
            JobConfig(max_queued_jobs=0)

    def test_poll_interval_too_low(self):
        with pytest.raises(ValueError, match="worker_poll_interval_seconds"):
            JobConfig(worker_poll_interval_seconds=0)

    def test_poll_interval_too_high(self):
        with pytest.raises(ValueError, match="worker_poll_interval_seconds"):
            JobConfig(worker_poll_interval_seconds=10)

    def test_retention_hours_less_than_1(self):
        with pytest.raises(ValueError, match="retention_hours"):
            JobConfig(retention_hours=0)

    def test_recover_timeout_too_low(self):
        with pytest.raises(ValueError, match="recover_timeout_seconds"):
            JobConfig(recover_timeout_seconds=30)

    def test_heartbeat_interval_too_low(self):
        with pytest.raises(ValueError, match="heartbeat_interval_seconds"):
            JobConfig(heartbeat_interval_seconds=5)

    def test_heartbeat_interval_too_high(self):
        with pytest.raises(ValueError, match="heartbeat_interval_seconds"):
            JobConfig(heartbeat_interval_seconds=180)

    def test_valid_boundary_values(self):
        cfg = JobConfig(
            max_running_jobs=1,
            max_queued_jobs=1,
            worker_poll_interval_seconds=1,
            retention_hours=1,
            recover_timeout_seconds=60,
            heartbeat_interval_seconds=10,
        )
        assert cfg.max_running_jobs == 1

        cfg2 = JobConfig(
            max_running_jobs=100,
            max_queued_jobs=1000,
            worker_poll_interval_seconds=5,
            heartbeat_interval_seconds=120,
        )
        assert cfg2.max_queued_jobs == 1000


class TestJobConfigFromEnv:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("DOCCONV_MAX_RUNNING_JOBS", "5")
        monkeypatch.setenv("DOCCONV_MAX_QUEUED_JOBS", "100")
        cfg = JobConfig.from_env()
        assert cfg.max_running_jobs == 5
        assert cfg.max_queued_jobs == 100

    def test_env_bool_parsing(self, monkeypatch):
        monkeypatch.setenv("DOCCONV_ENABLED", "false")
        monkeypatch.setenv("DOCCONV_RECOVER_ON_START", "true")
        cfg = JobConfig.from_env()
        assert cfg.enabled is False
        assert cfg.recover_running_on_start is True

    def test_env_invalid_value_keeps_default(self, monkeypatch):
        monkeypatch.setenv("DOCCONV_MAX_RUNNING_JOBS", "not_a_number")
        cfg = JobConfig.from_env()
        assert cfg.max_running_jobs == 1  # default

    def test_overrides_take_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("DOCCONV_MAX_RUNNING_JOBS", "5")
        cfg = JobConfig.from_env({"max_running_jobs": 10})
        assert cfg.max_running_jobs == 10
