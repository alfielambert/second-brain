from pathlib import Path

import pytest

from second_brain import health, watchdog
from second_brain.vault import init_vault


@pytest.fixture
def vault(tmp_path) -> Path:
    return init_vault(tmp_path / "vault")


class FakeNotifier:
    def __init__(self):
        self.texts: list[str] = []

    def send_proposal(self, proposal: dict) -> None:
        raise NotImplementedError  # watchdog never calls this

    def send_text(self, text: str) -> None:
        self.texts.append(text)


def test_no_connectors_no_staleness(vault):
    result = watchdog.check(vault_root=vault)
    assert result["stale"] == []
    assert result["total_connectors"] == 0


def test_a_never_succeeded_connector_is_stale(vault):
    # Recorded but never actually succeeded (e.g. only ever "failed").
    health.mark_checked("capture", "failed", vault_root=vault, error="boom")
    result = watchdog.check(vault_root=vault)
    assert len(result["stale"]) == 1
    assert result["stale"][0]["reason"] == "never succeeded"


def test_a_recently_healthy_connector_is_not_stale(vault):
    health.mark_checked("capture", "healthy", vault_root=vault)
    result = watchdog.check(vault_root=vault)
    assert result["stale"] == []
    assert result["healthy_count"] == 1


def test_current_no_change_counts_as_healthy_for_staleness_purposes(vault):
    """A connector that legitimately has nothing new every day must never
    be reported stale just because it never emits claims - see
    test_health.py's matching test for the same principle at the
    health.py layer; this proves watchdog inherits it correctly."""
    health.mark_checked("capture", "current_no_change", vault_root=vault)
    result = watchdog.check(vault_root=vault)
    assert result["stale"] == []


# --- independence: watchdog only reads, and alerting failure doesn't crash it ---

def test_watchdog_run_does_not_write_any_connector_state(vault):
    health.mark_checked("capture", "failed", vault_root=vault, error="boom")
    before = health.all_states(vault_root=vault)

    watchdog.run(vault_root=vault)

    after = health.all_states(vault_root=vault)
    assert before == after  # watchdog is read-only with respect to connector state


def test_alert_is_sent_only_when_something_is_stale(vault):
    notifier = FakeNotifier()
    health.mark_checked("capture", "healthy", vault_root=vault)
    watchdog.run(vault_root=vault, notifier=notifier)
    assert notifier.texts == []

    health.mark_checked("gmail", "failed", vault_root=vault, error="boom")
    watchdog.run(vault_root=vault, notifier=notifier)
    assert len(notifier.texts) == 1
    assert "gmail" in notifier.texts[0]


def test_a_failed_alert_does_not_crash_the_watchdog_run(vault):
    class BrokenNotifier:
        def send_proposal(self, proposal):
            raise NotImplementedError

        def send_text(self, text):
            raise RuntimeError("notification service down")

    health.mark_checked("capture", "failed", vault_root=vault, error="boom")
    result = watchdog.run(vault_root=vault, notifier=BrokenNotifier())  # must not raise
    assert result["stale"]
    assert "alert_error" in result
