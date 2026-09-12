from pathlib import Path

import pytest

from second_brain import reports
from second_brain.reports import HistoryConflictError, write_report
from second_brain.vault import init_vault


@pytest.fixture
def vault(tmp_path) -> Path:
    return init_vault(tmp_path / "vault")


# Fictional sample data only - a weekly Atlas adoption metrics report,
# consistent with the Acme/Atlas demo dataset used elsewhere.
def _body(mentions: int, note: str = "") -> str:
    return f"## Adoption Signals\n\n- Atlas mentions this week: {mentions}\n{note}"


# --- canonical write + forward-only ---

def test_first_write_creates_both_canonical_and_history(vault):
    result = write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))

    assert result["canonical"] == "written"
    assert result["history"] == "written"
    assert (vault / "Reports" / "Atlas Adoption.md").exists()
    assert (vault / "Reports" / "History" / "Atlas Adoption" / "2026-08-01.md").exists()


def test_canonical_moves_forward_on_a_newer_run(vault):
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))
    result = write_report(vault, subject="Atlas Adoption", run_date="2026-08-08", body=_body(9))

    assert result["canonical"] == "written"
    canonical_text = (vault / "Reports" / "Atlas Adoption.md").read_text()
    assert "run-date: 2026-08-08" in canonical_text
    assert "Atlas mentions this week: 9" in canonical_text


def test_canonical_never_regresses_to_an_older_run(vault):
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-08", body=_body(9))
    result = write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))

    assert result["canonical"] == "skipped_older_or_same"
    canonical_text = (vault / "Reports" / "Atlas Adoption.md").read_text()
    assert "run-date: 2026-08-08" in canonical_text  # still the newer run, untouched
    assert "Atlas mentions this week: 9" in canonical_text


def test_reprocessing_the_same_run_is_a_safe_no_op(vault):
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))
    result = write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))

    assert result["canonical"] == "skipped_older_or_same"
    assert result["history"] == "skipped_exists"


# --- immutable history ---

def test_history_snapshot_is_never_overwritten_with_different_content(vault):
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))

    with pytest.raises(HistoryConflictError):
        write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(999, note="tampered"))

    # the original content is untouched
    history_text = (vault / "Reports" / "History" / "Atlas Adoption" / "2026-08-01.md").read_text()
    assert "Atlas mentions this week: 4" in history_text
    assert "999" not in history_text


def test_history_stays_immutable_across_multiple_runs(vault):
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-08", body=_body(9))
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-15", body=_body(12))

    history_dir = vault / "Reports" / "History" / "Atlas Adoption"
    assert sorted(p.name for p in history_dir.glob("*.md")) == ["2026-08-01.md", "2026-08-08.md", "2026-08-15.md"]
    assert "Atlas mentions this week: 4" in (history_dir / "2026-08-01.md").read_text()
    assert "Atlas mentions this week: 9" in (history_dir / "2026-08-08.md").read_text()
    assert "Atlas mentions this week: 12" in (history_dir / "2026-08-15.md").read_text()


def test_previous_report_link_is_recorded_on_the_new_canonical(vault):
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-08", body=_body(9))

    canonical_text = (vault / "Reports" / "Atlas Adoption.md").read_text()
    assert "Reports/History/Atlas Adoption/2026-08-01" in canonical_text


def test_multiple_subjects_do_not_interfere(vault):
    write_report(vault, subject="Atlas Adoption", run_date="2026-08-01", body=_body(4))
    write_report(vault, subject="Atlas Retention", run_date="2026-08-01", body=_body(2))

    assert (vault / "Reports" / "Atlas Adoption.md").exists()
    assert (vault / "Reports" / "Atlas Retention.md").exists()
    assert "Atlas mentions this week: 4" in (vault / "Reports" / "Atlas Adoption.md").read_text()
    assert "Atlas mentions this week: 2" in (vault / "Reports" / "Atlas Retention.md").read_text()
