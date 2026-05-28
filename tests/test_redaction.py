"""日志脱敏模块测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.redaction import redact_text, redact_dict, REDACTED


class TestRedactText:
    """测试 redact_text 函数。"""

    def test_empty_string(self):
        assert redact_text("") == ""

    def test_none_returns_none(self):
        assert redact_text(None) is None

    def test_no_secrets_unchanged(self):
        assert redact_text("Hello world") == "Hello world"

    def test_sk_api_key_redacted(self):
        text = "Error with key sk-ant-abc1234567890abcdef1234567890ab"
        result = redact_text(text)
        assert "sk-ant-" not in result
        assert REDACTED in result

    def test_openai_key_redacted(self):
        text = "key=sk-proj-abc1234567890abcdef1234567890ab"
        result = redact_text(text)
        assert "sk-proj-" not in result

    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret"
        result = redact_text(text)
        assert "eyJhbGci" not in result
        assert REDACTED in result

    def test_url_token_redacted(self):
        text = "https://api.example.com?token=abc123&other=val"
        result = redact_text(text)
        assert "abc123" not in result
        assert REDACTED in result

    def test_env_style_key_redacted(self):
        text = "MY_API_KEY=super_secret_value"
        result = redact_text(text)
        assert "super_secret_value" not in result

    def test_multiple_secrets_redacted(self):
        text = "key1=sk-ant-aaaa1111222233334444 key2=sk-proj-bbbb5555666677778888"
        result = redact_text(text)
        assert "sk-ant-" not in result
        assert "sk-proj-" not in result

    def test_job_id_not_redacted(self):
        """job_id 等普通标识符不应被脱敏。"""
        text = "job_abc_001 started"
        result = redact_text(text)
        assert result == "job_abc_001 started"


class TestRedactDict:
    """测试 redact_dict 函数。"""

    def test_non_sensitive_unchanged(self):
        data = {"name": "test", "count": 42}
        result = redact_dict(data)
        assert result == {"name": "test", "count": 42}

    def test_sensitive_key_redacted(self):
        data = {"api_key": "secret123", "name": "test"}
        result = redact_dict(data)
        assert result["api_key"] == REDACTED
        assert result["name"] == "test"

    def test_token_key_redacted(self):
        data = {"access_token": "tok_abc", "user": "admin"}
        result = redact_dict(data)
        assert result["access_token"] == REDACTED

    def test_nested_dict_redacted(self):
        data = {"config": {"secret": "hidden", "normal": "ok"}}
        result = redact_dict(data)
        assert result["config"]["secret"] == REDACTED
        assert result["config"]["normal"] == "ok"

    def test_non_string_values_unchanged(self):
        data = {"count": 10, "active": True, "items": [1, 2, 3]}
        result = redact_dict(data)
        assert result == data

    def test_password_redacted(self):
        data = {"password": "my_pass", "username": "admin"}
        result = redact_dict(data)
        assert result["password"] == REDACTED
