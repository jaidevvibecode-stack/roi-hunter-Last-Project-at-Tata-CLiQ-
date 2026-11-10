"""
ingestion/common/logging_utils.py
----------------------------------
Structured JSON logging with run_id, source, account_id context.
Never logs tokens, passwords, or PII.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Any

from pythonjsonlogger import jsonlogger

_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "token",
        "password",
        "secret",
        "api_key",
        "authorization",
        "distinct_id",
        "email",
        "phone",
        "name",
    }
)


_PATTERNS = [
    (re.compile(r"(access_token|client_secret|app_secret|password|secret|api_key)=[^&\s\"']+", re.I), r"\1=***"),
    (re.compile(r"(authorization:?\s*(?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]+", re.I), r"\1***"),
    (re.compile(r"\bEAA[A-Za-z0-9]{20,}\b"), "***META_TOKEN***"),                 # Meta access tokens
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "***EMAIL***"),
    (re.compile(r"(?<!\d)(?:\+?91[- ]?)?[6-9]\d{9}(?!\d)"), "***PHONE***"),        # Indian mobile numbers
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "***AWS_KEY***"),
]


def redact(text: str) -> str:
    """Mask credentials and PII inside free-text log messages."""
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class SanitizingJsonFormatter(jsonlogger.JsonFormatter):
    """Remove or mask sensitive fields before emitting."""

    def process_log_record(self, log_record: dict[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for k, v in log_record.items():
            if any(sensitive in k.lower() for sensitive in _SENSITIVE_KEYS):
                sanitized[k] = "***REDACTED***"
            elif isinstance(v, str):
                sanitized[k] = redact(v)
            else:
                sanitized[k] = v
        return sanitized


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON formatter. Call once at process start."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        SanitizingJsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter:  # type: ignore[type-arg]
    """
    Return a logger adapter pre-loaded with context fields.

    Usage:
        log = get_logger(__name__, run_id=run_id, source="meta_insights", account_id=acct)
        log.info("Job started", extra={"date": "2024-01-15"})
    """
    logger = logging.getLogger(name)
    return logging.LoggerAdapter(logger, context)
