"""Tests for Result type (Success / Failure)."""

import pytest

from nous.domain.shared.result import Failure, Success


class TestSuccess:
    def test_create_with_value(self):
        r = Success(42)
        assert r.value == 42

    def test_is_ok_true(self):
        assert Success("hello").is_ok is True

    def test_frozen(self):
        r = Success(1)
        with pytest.raises(AttributeError):
            r.value = 2  # type: ignore[misc]


class TestFailure:
    def test_create_with_error(self):
        r = Failure("err")
        assert r.error == "err"

    def test_is_ok_false(self):
        assert Failure("err").is_ok is False

    def test_frozen(self):
        r = Failure("err")
        with pytest.raises(AttributeError):
            r.error = "new"  # type: ignore[misc]


class TestResultUnion:
    """Result = Success | Failure の使い分けテスト。"""

    def test_success_branch(self):
        result: Success[int] | Failure[str] = Success(1)
        if result.is_ok:
            assert result.value == 1
        else:
            pytest.fail("Expected Success")

    def test_failure_branch(self):
        result: Success[int] | Failure[str] = Failure("oops")
        if not result.is_ok:
            assert result.error == "oops"
        else:
            pytest.fail("Expected Failure")
