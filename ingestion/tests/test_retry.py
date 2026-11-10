"""
ingestion/tests/test_retry.py
------------------------------
Unit tests for the Meta error-code retry classifier.
These tests must pass without any live credentials.
"""
from __future__ import annotations

import pytest

from ingestion.common.retry import is_retryable


class _FakeMetaError(Exception):
    """Simulate a facebook-business SDK FacebookRequestError."""

    def __init__(self, code: int, subcode: int | None = None) -> None:
        self._code = code
        self._subcode = subcode

    def api_error_code(self) -> int:
        return self._code

    def api_error_subcode(self) -> int | None:
        return self._subcode


@pytest.mark.parametrize(
    "code,subcode,expected",
    [
        # Retryable codes
        (4, None, True),
        (17, None, True),
        (613, None, True),
        (80000, None, True),
        (80014, None, True),
        # Retryable subcode
        (1, 1504022, True),
        # Auth — NOT retryable
        (190, None, False),
        # Permission — NOT retryable
        (200, None, False),
        (275, None, False),
        # Bad request — NOT retryable
        (100, None, False),
        # Unknown code without subcode — NOT retryable
        (999, None, False),
    ],
)
def test_is_retryable_meta_codes(code: int, subcode: int | None, expected: bool) -> None:
    err = _FakeMetaError(code, subcode)
    assert is_retryable(err) == expected


def test_is_retryable_network_errors() -> None:
    assert is_retryable(ConnectionError("network reset")) is True
    assert is_retryable(TimeoutError("timeout")) is True
    assert is_retryable(OSError("broken pipe")) is True


def test_non_retryable_generic() -> None:
    assert is_retryable(ValueError("bad value")) is False
    assert is_retryable(KeyError("missing key")) is False
