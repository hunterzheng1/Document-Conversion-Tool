"""测试 service-job-management 数据模型。"""

import os
import tempfile
import pytest

from docconv.service.job_models import (
    JobStatus,
    JobRecord,
    ConversionRequest,
    ServiceError,
    ErrorCodes,
    normalize_cli_request,
)


class TestJobStatus:
    def test_all_status_values(self):
        assert JobStatus.QUEUED == "queued"
        assert JobStatus.RUNNING == "running"
        assert JobStatus.SUCCEEDED == "succeeded"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.CANCELLED == "cancelled"
        assert JobStatus.EXPIRED == "expired"

    def test_valid_transition_queued_to_running(self):
        assert JobStatus.can_transition(JobStatus.QUEUED, JobStatus.RUNNING)

    def test_valid_transition_running_to_succeeded(self):
        assert JobStatus.can_transition(JobStatus.RUNNING, JobStatus.SUCCEEDED)

    def test_valid_transition_queued_to_cancelled(self):
        assert JobStatus.can_transition(JobStatus.QUEUED, JobStatus.CANCELLED)

    def test_invalid_transition_succeeded_to_running(self):
        assert not JobStatus.can_transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)

    def test_expired_is_terminal(self):
        for target in [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCEEDED]:
            assert not JobStatus.can_transition(JobStatus.EXPIRED, target)

    def test_invalid_source_raises(self):
        with pytest.raises(ValueError):
            JobStatus.can_transition("bogus", JobStatus.RUNNING)


class TestJobRecord:
    def test_default_job_record(self):
        record = JobRecord()
        assert record.job_id == ""
        assert record.status == JobStatus.QUEUED
        assert record.output_path == ""

    def test_generate_job_id_format(self):
        jid = JobRecord.generate_job_id()
        assert jid.startswith("job_")
        assert len(jid) >= 19  # job_YYYYMMDD_<uuid_prefix>

    def test_to_dict_roundtrip(self):
        record = JobRecord(
            job_id="job_test_001",
            source="web",
            status=JobStatus.QUEUED,
            original_filename="test.pdf",
            input_path="/data/jobs/job_test_001/input/test.pdf",
        )
        d = record.to_dict()
        restored = JobRecord.from_dict(d)
        assert restored.job_id == "job_test_001"
        assert restored.source == "web"
        assert restored.status == JobStatus.QUEUED

    def test_from_dict_ignores_extra_keys(self):
        d = {"job_id": "x", "source": "cli", "extra_field": "ignore"}
        record = JobRecord.from_dict(d)
        assert record.job_id == "x"
        assert "extra_field" not in record.to_dict()

    def test_copy_with(self):
        record = JobRecord(job_id="job_001", status=JobStatus.QUEUED)
        new_record = record.copy_with(status=JobStatus.RUNNING, locked_by="w1")
        assert new_record.job_id == "job_001"
        assert new_record.status == JobStatus.RUNNING
        assert new_record.locked_by == "w1"
        # Original unchanged
        assert record.status == JobStatus.QUEUED


class TestConversionRequest:
    def test_validate_passes_with_valid_file(self):
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        try:
            req = ConversionRequest(
                source="web",
                input_file_path=f.name,
                original_filename="test.pdf",
            )
            req.validate()  # should not raise
        finally:
            os.unlink(f.name)

    def test_validate_empty_source_raises(self):
        req = ConversionRequest(source="", input_file_path="/x.pdf")
        with pytest.raises(ServiceError) as exc:
            req.validate()
        assert exc.value.code == ErrorCodes.SVC1001

    def test_validate_missing_file_raises(self):
        req = ConversionRequest(
            source="cli", input_file_path="/nonexistent/path/file.pdf"
        )
        with pytest.raises(ServiceError) as exc:
            req.validate()
        assert exc.value.code == ErrorCodes.SVC1001

    def test_validate_instruction_too_long(self):
        req = ConversionRequest(
            source="cli",
            input_file_path="/tmp/x.pdf",
            instruction="x" * 2000,
        )
        with pytest.raises(ServiceError) as exc:
            req.validate()
        assert exc.value.code == ErrorCodes.SVC1001

    def test_validate_options_whitelist(self):
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        try:
            req = ConversionRequest(
                source="cli",
                input_file_path=f.name,
                options={"parallel": 2, "unknown_key": "bad"},
            )
            with pytest.raises(ServiceError) as exc:
                req.validate()
            assert exc.value.code == ErrorCodes.SVC1001
            assert "unknown_key" in exc.value.message
        finally:
            os.unlink(f.name)

    def test_validate_options_whitelist_pass(self):
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        try:
            req = ConversionRequest(
                source="cli",
                input_file_path=f.name,
                options={"parallel": 2, "verbose": True},
            )
            req.validate()  # should pass
        finally:
            os.unlink(f.name)


class TestNormalizeCliRequest:
    def test_normalize_sets_cli_source(self):
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.close()
        try:
            req = normalize_cli_request(f.name, "test.pdf", {"parallel": 1})
            assert req.source == "cli"
            assert req.original_filename == "test.pdf"
        finally:
            os.unlink(f.name)
