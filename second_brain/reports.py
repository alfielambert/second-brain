"""
reports.py - the Current + History + Sources pattern for recurring,
structured evidence (a weekly metrics report, a scan result, anything a
connector produces on a schedule rather than once).

Three tiers, each with a different job:

    Sources/<connector>/...              raw evidence, exactly as it arrived,
                                          immutable, never rewritten
                                              |
                                              v
    Reports/<subject>.md                 CURRENT: concise governed state,
                                          always the latest run, safe to
                                          overwrite - but only forward
                                              |
                                              v
    Reports/History/<subject>/
        YYYY-MM-DD.md                    one immutable snapshot per run

Agents should read Reports/<subject>.md first - it's the concise current
truth - and only drill into History/ or Sources/ when they specifically
need to see what changed or re-derive something from the original
evidence. See docs/architecture.md for where this fits relative to the
Claim Store: a report produced this way is an authoritative artifact in
its own right (Rule: report notes are never source material for a claim -
they summarise governed state, they don't create new claims themselves;
if a report reveals something that should become a claim, extract that
claim explicitly and separately, the same way any other evidence would be
turned into one).

Idempotency contract (the whole point of this module):
  - History is create-only. Writing the same run_date twice with the same
    content is a safe no-op. Writing the same run_date with DIFFERENT
    content raises HistoryConflictError - this is a genuine data-integrity
    problem (something regenerated the same historical run differently)
    and must never be resolved by silently picking a winner.
  - The canonical file only ever moves forward: writing an older run_date
    than what's already there is a no-op, never a regression. There is no
    way to accidentally overwrite current state with stale state through
    this API.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Optional

from second_brain.vault import find_vault_root


class HistoryConflictError(Exception):
    """A history snapshot already exists at this (subject, run_date) with
    different content than what's being written now. Never resolved
    automatically in either direction - surfacing this to a human/caller
    is the correct behaviour, not picking a winner."""

    def __init__(self, subject: str, run_date: str, existing_hash: str, new_hash: str):
        super().__init__(
            f"History/{subject}/{run_date}.md already exists with different content "
            f"(existing sha256={existing_hash[:12]}..., new sha256={new_hash[:12]}...) - "
            f"refusing to overwrite immutable history."
        )
        self.subject = subject
        self.run_date = run_date
        self.existing_hash = existing_hash
        self.new_hash = new_hash


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)  # atomic on the same filesystem
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def canonical_path(vault_root: Path, subject: str) -> Path:
    return vault_root / "Reports" / f"{subject}.md"


def history_path(vault_root: Path, subject: str, run_date: str) -> Path:
    return vault_root / "Reports" / "History" / subject / f"{run_date}.md"


def _read_frontmatter_field(path: Path, field: str) -> Optional[str]:
    if not path.exists():
        return None
    import re
    m = re.search(rf"^{field}:\s*(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return m.group(1).strip() if m else None


def render(*, subject: str, run_date: str, status: str, body: str, previous_report: Optional[str] = None) -> str:
    """Render one report's frontmatter + body. `body` is caller-rendered
    markdown (this module has no opinion on report content/format, only
    on the write contract around it) - never invent fields the caller
    didn't provide; an empty/omitted value should stay empty, not be
    guessed at."""
    lines = [
        "---",
        "type: report",
        f"subject: {subject}",
        f"run-date: {run_date}",
        f"status: {status}",
        f"previous-report: {previous_report or 'null'}",
        "---",
        "",
        body.rstrip(),
        "",
    ]
    return "\n".join(lines)


def write_report(
    vault_root: Optional[Path],
    *,
    subject: str,
    run_date: str,
    body: str,
) -> dict:
    """Idempotently write one run's report to both the canonical and
    history locations. `body` is the rendered markdown content shared by
    both (history is a frozen copy of exactly what the canonical view
    showed at that run - not a separately-summarised version).

    Returns {"canonical": "written"|"skipped_older_or_same", "history":
    "written"|"skipped_exists", "canonical_path": ..., "history_path": ...}.
    Raises HistoryConflictError if a history snapshot already exists for
    this run_date with different content - this is the one case this
    function does NOT silently resolve; every other case is a safe no-op.
    """
    root = vault_root or find_vault_root()
    hist_path = history_path(root, subject, run_date)
    can_path = canonical_path(root, subject)
    result: dict = {"canonical_path": str(can_path), "history_path": str(hist_path)}

    # Compare the FULL rendered content on both sides (what's already on
    # disk vs. what we'd write now) - render() is a pure function of its
    # inputs, so the same (subject, run_date, body) always renders
    # byte-identically, and comparing anything less than the full
    # rendered content (e.g. just the raw body) would be an apples-to-
    # oranges comparison against what's actually on disk.
    history_content = render(subject=subject, run_date=run_date, status="history", body=body)
    new_hash = _sha256(history_content)

    if hist_path.exists():
        existing_hash = _sha256(hist_path.read_text(encoding="utf-8"))
        if existing_hash != new_hash:
            raise HistoryConflictError(subject, run_date, existing_hash, new_hash)
        result["history"] = "skipped_exists"
    else:
        _atomic_write_text(hist_path, history_content)
        result["history"] = "written"

    existing_run_date = _read_frontmatter_field(can_path, "run-date")
    if existing_run_date and existing_run_date >= run_date:
        result["canonical"] = "skipped_older_or_same"
    else:
        previous = f"[[Reports/History/{subject}/{existing_run_date}]]" if existing_run_date else None
        canonical_content = render(subject=subject, run_date=run_date, status="current", body=body, previous_report=previous)
        _atomic_write_text(can_path, canonical_content)
        result["canonical"] = "written"

    return result
