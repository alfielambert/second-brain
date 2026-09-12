import time

import pytest

from second_brain import resilience
from second_brain.resilience import ConnectorReportedError, StepTimeout, run_step


# --- per-connector budgets (not a single global) ---

def test_connector_a_and_b_can_receive_different_session_budgets():
    """The same run_step() call, given different `timeout` values per
    connector, actually enforces different budgets - proves there is no
    hidden shared/global timeout underneath."""
    def slow_a():
        time.sleep(0.15)
        return "a-done"

    def slow_b():
        time.sleep(0.15)
        return "b-done"

    # connector "a" gets a budget too tight for its own call...
    result_a = run_step("connector-a", slow_a, timeout=0.05, retries=0)
    assert result_a.status == "failed"

    # ...while connector "b", with a wider budget, succeeds on the exact
    # same shape of call.
    result_b = run_step("connector-b", slow_b, timeout=1.0, retries=0)
    assert result_b.status == "ok"
    assert result_b.value == "b-done"


def test_a_global_default_cannot_silently_override_a_caller_supplied_timeout():
    """resilience.DEFAULT_TIMEOUT_SECONDS exists as a fallback for callers
    that pass nothing - but any caller that DOES pass timeout=, as
    cli.py's cmd_sync always does via each connector's own configured
    session_timeout_seconds, gets exactly that value, not the default."""
    assert resilience.DEFAULT_TIMEOUT_SECONDS == 120  # sanity: the fallback itself is unchanged

    def instant():
        return "ok"

    # An explicit timeout far below the module default still applies -
    # the default never silently wins over what the caller specified.
    result = run_step("x", instant, timeout=0.01, retries=0)
    assert result.status == "ok"  # instant() finishes well within even a tiny explicit budget

    def slow():
        time.sleep(0.05)
        return "late"

    # A budget explicitly tighter than the default causes a real timeout,
    # proving the default isn't quietly substituted in.
    result = run_step("x", slow, timeout=0.01, retries=0)
    assert result.status == "failed"
    assert "timeout" in (result.error or "").lower() or "exceeded" in (result.error or "").lower()


# --- structured failure semantics: retryable vs not ---

def test_connector_reported_error_retryable_true_is_retried():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectorReportedError("transient blip", error_type="connection", retryable=True)
        return "recovered"

    result = run_step("x", flaky, timeout=1.0, retries=1, backoff_seconds=0.01)
    assert result.status == "degraded"  # succeeded, but needed a retry
    assert result.value == "recovered"
    assert calls["n"] == 2


def test_connector_reported_error_retryable_false_is_not_retried():
    calls = {"n": 0}

    def bad_auth():
        calls["n"] += 1
        raise ConnectorReportedError("token rejected", error_type="auth", retryable=False)

    result = run_step("x", bad_auth, timeout=1.0, retries=3, backoff_seconds=0.01)
    assert result.status == "failed"
    assert calls["n"] == 1  # never retried - wasting a retry on a bad credential fixes nothing


def test_plain_exception_not_in_transient_list_is_not_retried():
    calls = {"n": 0}

    def buggy():
        calls["n"] += 1
        raise ValueError("a real bug in claim construction")

    result = run_step("x", buggy, timeout=1.0, retries=3)
    assert result.status == "failed"
    assert calls["n"] == 1


def test_exception_in_transient_list_is_retried():
    calls = {"n": 0}

    def flaky_network():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("dropped")
        return "ok"

    result = run_step("x", flaky_network, timeout=1.0, retries=1, backoff_seconds=0.01, transient_exceptions=(ConnectionError,))
    assert result.status == "degraded"
    assert calls["n"] == 2


# --- fallback ---

def test_fallback_used_after_retries_exhausted():
    def always_fails():
        raise ConnectionError("primary path down")

    def fallback():
        return "fallback result"

    result = run_step(
        "x", always_fails, timeout=1.0, retries=1, backoff_seconds=0.01,
        transient_exceptions=(ConnectionError,), fallback_fn=fallback, fallback_name="alt-path",
    )
    assert result.status == "degraded"
    assert result.fallback_used == "alt-path"
    assert result.value == "fallback result"


def test_no_fallback_after_exhausted_retries_is_failed():
    def always_fails():
        raise ConnectionError("down")

    result = run_step("x", always_fails, timeout=1.0, retries=1, backoff_seconds=0.01, transient_exceptions=(ConnectionError,))
    assert result.status == "failed"


# --- a hung call cannot hang the whole run ---

def test_hard_timeout_bounds_a_hanging_call():
    def hangs_forever():
        time.sleep(10)
        return "never"

    t0 = time.monotonic()
    result = run_step("x", hangs_forever, timeout=0.05, retries=0, hard_timeout=True)
    elapsed = time.monotonic() - t0

    assert result.status == "failed"
    assert elapsed < 1.0  # nowhere near the 10s the call itself would take


def test_hard_timeout_false_trusts_caller_own_timeout():
    """When hard_timeout=False, run_step does not wrap call_fn in its own
    thread timer - it trusts call_fn to enforce its own bound (e.g. via
    subprocess_timeout.run_with_timeout) and simply treats that timeout
    exception as transient if it's listed."""

    class FakeTimeout(Exception):
        pass

    def call_fn():
        raise FakeTimeout("caller's own timeout fired")

    result = run_step("x", call_fn, timeout=999, retries=0, hard_timeout=False, transient_exceptions=(FakeTimeout,))
    assert result.status == "failed"
    assert "caller's own timeout" in (result.error or "")
