"""
ingestion/common/retry.py
--------------------------
Tenacity-based retry logic with Meta Marketing API error-code classification.

Meta error codes that are retryable (transient rate/throttle/server errors):
  4   — Application request limit reached
  17  — User request limit reached
  613 — Calls to this api have exceeded the rate limit
  80000–80014 — Ads Insights async errors
  Subcode 1504022 — Ads Insights: resource already exists (safe duplicate)

Non-retryable: auth errors (190), permission errors (200-299), bad request (100).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import httpx
import tenacity
from tenacity import RetryCallState

log = logging.getLogger(__name__)

# ── Error code sets ───────────────────────────────────────────────────────────
_RETRYABLE_CODES = {4, 17, 613} | set(range(80000, 80015))
_RETRYABLE_SUBCODES = {1504022}

_AUTH_CODES = {190}
_PERMISSION_CODES = set(range(200, 300))
_BAD_REQUEST_CODES = {100}


def _is_meta_error(exc: BaseException) -> tuple[bool, int | None, int | None]:
    """
    Detect Meta API error and extract (is_meta_error, code, error_subcode).
    Works with facebook-business SDK FacebookRequestError and plain dicts.
    """
    try:
        # facebook-business SDK
        if hasattr(exc, "api_error_code"):
            code = int(getattr(exc, "api_error_code")())  # noqa: B009
            subcode = getattr(exc, "api_error_subcode")()  # noqa: B009
            return True, code, subcode or None
        # httpx / raw dict errors
        body = getattr(exc, "response", None)
        if body is not None:
            data: dict[str, Any] = getattr(body, "json", dict)()
            err = data.get("error", {})
            return True, err.get("code"), err.get("error_subcode")
    except Exception:  # malformed error payload => treat as non-Meta error, never raise from classifier
        log.debug("could not classify exception as Meta error", exc_info=True)
    return False, None, None


def is_retryable(exc: BaseException) -> bool:
    """Return True if the exception represents a transient Meta error worth retrying."""
    # HTTP-level transient failures (e.g. Mixpanel 429 rate limit, 5xx, timeouts, dropped connections)
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    is_meta, code, subcode = _is_meta_error(exc)
    if not is_meta:
        # Retry generic network errors too (ConnectionError, TimeoutError)
        return isinstance(exc, (ConnectionError, TimeoutError, OSError))
    if code in _AUTH_CODES or code in _PERMISSION_CODES or code in _BAD_REQUEST_CODES:
        return False
    if code in _RETRYABLE_CODES:
        return True
    if subcode in _RETRYABLE_SUBCODES:
        return True
    return False


def _log_retry(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    log.warning(
        "Retrying after error",
        extra={
            "attempt": state.attempt_number,
            "wait_seconds": round(state.next_action.sleep, 2) if state.next_action else None,
            "error": str(exc),
        },
    )


def make_retry(
    max_attempts: int = 7,
    base_wait: float = 2.0,
    max_wait: float = 300.0,
    jitter: float = 5.0,
) -> tenacity.Retrying:
    """
    Build a Tenacity Retrying context for Meta API calls.

    Example:
        for attempt in make_retry():
            with attempt:
                result = call_meta_api(...)
    """
    return tenacity.Retrying(
        retry=tenacity.retry_if_exception(is_retryable),
        wait=tenacity.wait_exponential(multiplier=base_wait, max=max_wait)
        + tenacity.wait_random(0, jitter),
        stop=tenacity.stop_after_attempt(max_attempts),
        before_sleep=_log_retry,
        reraise=True,
    )


def retry_meta(
    max_attempts: int = 7,
    base_wait: float = 2.0,
    max_wait: float = 300.0,
) -> Callable[..., Any]:
    """
    Decorator variant:

        @retry_meta()
        def call_insights(...): ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @tenacity.retry(
            retry=tenacity.retry_if_exception(is_retryable),
            wait=tenacity.wait_exponential(multiplier=base_wait, max=max_wait)
            + tenacity.wait_random(0, 5),
            stop=tenacity.stop_after_attempt(max_attempts),
            before_sleep=_log_retry,
            reraise=True,
        )
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        return wrapper

    return decorator
