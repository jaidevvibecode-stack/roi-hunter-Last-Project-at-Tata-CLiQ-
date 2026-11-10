from __future__ import annotations

from ingestion.common.logging_utils import redact


def test_masks_tokens_and_pii():
    out = redact("GET /x?access_token=EAABsbCS1iHgBO1234567890abcdef&a=1 user a.b@tata.com ph 9876543210")
    assert "EAAB" not in out and "tata.com" not in out and "9876543210" not in out
    assert "access_token=***" in out


def test_masks_bearer_and_aws():
    assert "abc123" not in redact("Authorization: Bearer abc123.def")
    assert "AKIAABCDEFGHIJKLMNOP" not in redact("key AKIAABCDEFGHIJKLMNOP")


def test_plain_text_untouched():
    assert redact("Loaded 1200 rows for act_123") == "Loaded 1200 rows for act_123"
