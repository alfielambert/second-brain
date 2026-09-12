"""
resilience.py - generic hardening primitives for connector sync steps.

One mechanism, reused by every connector - not connector-specific
try/except scattered through cli.py:

  - a hard wall-clock timeout per attempt (in-process connectors get this
    via a daemon worker thread; a connector that shells out to a real
    subprocess should use subprocess_timeout.py's process-group kill
    instead and pass hard_timeout=False here - see that module's
    docstring for why a second, overlapping timeout mechanism is worse
    than either one alone)
  - one retry after a short backoff (transient failures only get one
    extra try, not an unbounded loop)
  - an optional single fallback call if the primary approach and its
    retry are both exhausted
  - a status of "ok" / "degraded" / "failed", always returned, never
    raised - one connector's failure can never propagate and abort a run
    that's syncing several connectors in sequence

Ownership boundary: this module knows nothing about any specific
connector, and nothing about subprocesses or Claude. Callers pass in plain
zero-argument callables; connector-specific facts (what counts as a
fallback, what timeout to use, what "transient" means for this call) are
configuration the caller supplies - not branches in this file.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_RETRIES = 1
DEFAULT_BACKOFF_SECONDS = 3.0


@dataclass
class ConnectorStepResult:
    """The orchestrator's execution-status record for one connector-sync
    attempt - distinct from health.py's connector *data freshness* status
    (healthy/current_no_change/degraded/failed/stale/auth_required), which
    the connector itself sets via health.mark_checked() based on what it
    found. This result answers "did THIS RUN's attempt to execute the
    connector succeed", not "is the connector's data current" - a
    connector can finish this run needing a retry (status here: degraded)
    while its data ends up perfectly current (health.py status: healthy).
    Keep the two separate; do not collapse one into the other."""
    connector: str
    status: str                        # "ok" | "degraded" | "failed"
    elapsed_seconds: float
    attempts: int
    fallback_used: Optional[str] = None
    error: Optional[str] = None
    value: object = None               # whatever call_fn/fallback_fn returned, if it succeeded

    def as_log_dict(self) -> dict:
        return {
            "connector": self.connector,
            "status": self.status,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "attempts": self.attempts,
            "fallback_used": self.fallback_used,
            "error": self.error,
        }


class StepTimeout(Exception):
    pass


class ConnectorReportedError(Exception):
    """Raise this from call_fn to report a structured failure that the
    call itself didn't surface as a plain exception - the canonical case
    is a subprocess (or an LLM session run as one) that exits 0 but whose
    own output says an internal API call failed (a connection error, an
    expired auth token, malformed data, ...). The caller must translate
    that into one of these, carrying an explicit retry decision -
    run_step() honors `retryable` directly rather than guessing from
    exception type.

    error_type is one of: "timeout", "connection", "auth", "data",
    "logic". "timeout"/"connection" are usually retryable=True (transient).
    "auth" (a rejected credential) and "data" (malformed/unexpected
    source content) are usually retryable=False - retrying won't fix an
    expired token or bad data. "logic" (a real bug, or a reason unrelated
    to the above) is also retryable=False. Never mark a governance-layer
    failure (a Claim Store or KEP write itself failing) as retryable -
    that's an integrity problem to surface loudly, not a transient
    connector issue to paper over with a retry."""

    def __init__(self, message: str, *, error_type: str, retryable: bool):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


def _call_with_timeout(fn: Callable[[], object], timeout: float) -> object:
    """Run fn() with a hard wall-clock bound using a daemon thread. A
    daemon thread never blocks process exit even if fn() never returns -
    unlike a ThreadPoolExecutor, whose atexit handler would join a hung
    worker and block the whole process from exiting.

    This is thread-based, not process-based: it cannot forcibly kill fn()
    if fn() itself never checks back in (a genuinely hanging in-process
    call is not protected - only bounded from the caller's point of view,
    since run_step() will move on regardless). For real, guaranteed
    termination of external work, run that work as a subprocess and use
    subprocess_timeout.run_with_timeout() instead, which can actually
    SIGKILL it; pass hard_timeout=False here so the two mechanisms don't
    race each other."""
    box: dict = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread, not swallowed
            box["error"] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        raise StepTimeout(f"call exceeded {timeout}s and was abandoned")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def run_step(
    connector: str,
    call_fn: Callable[[], object],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    transient_exceptions: tuple = (),
    fallback_fn: Optional[Callable[[], object]] = None,
    fallback_name: Optional[str] = None,
    hard_timeout: bool = True,
) -> ConnectorStepResult:
    """Run one connector sync step under a hard timeout, retrying once
    after a backoff if the failure looks transient, then trying
    `fallback_fn` (if given) as a last resort. Never raises - always
    returns a ConnectorStepResult, so a caller syncing several connectors
    in sequence can always move on to the next one regardless of what
    happened here.

    `transient_exceptions` lets a caller say which of its own exception
    types are worth retrying (e.g. a connection error) - a bug in claim
    construction (KeyError, ValueError) is not transient and should fail
    straight to the fallback/failed state, not retry and waste the
    backoff. A timeout (StepTimeout, from this module - only raised when
    hard_timeout=True - or the caller's own subprocess-timeout exception
    if listed in transient_exceptions) is always treated as transient.

    A ConnectorReportedError is handled specially: its own `.retryable`
    flag decides whether this attempt is treated as transient, regardless
    of `transient_exceptions` - this is for the case call_fn's process
    exited successfully but reported a structured failure from inside.

    `hard_timeout` (default True) wraps call_fn in a daemon-thread timeout
    as a best-effort bound for a plain in-process callable. Set
    hard_timeout=False when call_fn already enforces a real timeout of
    its own (e.g. subprocess_timeout.run_with_timeout, which can actually
    terminate a subprocess) - this avoids a second, overlapping timer and
    the possibility of an abandoned thread still "running" after this
    function has already returned control to the caller.
    """
    t0 = time.monotonic()
    attempts = 0
    last_error: Optional[str] = None
    retryable_types = (StepTimeout,) + tuple(transient_exceptions)

    def _invoke(fn: Callable[[], object]) -> object:
        return _call_with_timeout(fn, timeout) if hard_timeout else fn()

    for attempt in range(retries + 1):
        attempts += 1
        try:
            value = _invoke(call_fn)
            status = "ok" if attempt == 0 else "degraded"
            return ConnectorStepResult(connector, status, time.monotonic() - t0, attempts, value=value)
        except ConnectorReportedError as e:
            last_error = f"{e.error_type}: {e}"
            if not e.retryable:
                break  # explicit non-retryable report (auth/data/logic) - straight to fallback/failed
            if attempt < retries:
                time.sleep(backoff_seconds)
        except retryable_types as e:
            last_error = str(e) or type(e).__name__
            if attempt < retries:
                time.sleep(backoff_seconds)
        except Exception as e:  # noqa: BLE001 - non-transient: no point retrying, go straight to fallback/failed
            last_error = f"{type(e).__name__}: {e}"
            break

    if fallback_fn is not None:
        attempts += 1
        try:
            value = _invoke(fallback_fn)
            return ConnectorStepResult(
                connector, "degraded", time.monotonic() - t0, attempts,
                fallback_used=fallback_name or getattr(fallback_fn, "__name__", "fallback"),
                value=value,
            )
        except StepTimeout:
            last_error = f"{last_error}; fallback also exceeded {timeout}s"
        except ConnectorReportedError as e:
            last_error = f"{last_error}; fallback reported {e.error_type}: {e}"
        except Exception as e:  # noqa: BLE001
            last_error = f"{last_error}; fallback failed: {type(e).__name__}: {e}"

    return ConnectorStepResult(connector, "failed", time.monotonic() - t0, attempts, error=last_error)
