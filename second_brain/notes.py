"""
Safe-write utility for durable knowledge notes.

A "durable write" is the one place the deterministic core actually mutates
vault markdown (everything else - claims, events - is append-only JSONL).
Writing is intentionally dumb: it does not try to merge prose. It creates
the note if missing, or appends a dated `## Update` block if the note
already exists. Anything that needs real merging (contradiction resolution,
prose synthesis) happens upstream, as a governance decision recorded in the
event log - by the time notes.write_note() runs, the decision is already
made and approved.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def write_note(vault_root: Path, target_note: str, content: str, frontmatter: dict) -> Path:
    path = vault_root / target_note
    path.parent.mkdir(parents=True, exist_ok=True)

    fm_lines = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not path.exists():
        path.write_text(f"---\n{fm_lines}\n---\n\n{content}\n", encoding="utf-8")
    else:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n## Update ({stamp})\n\n{content}\n")

    return path


def mark_superseded(vault_root: Path, target_note: str, reason: str) -> None:
    path = vault_root / target_note
    if not path.exists():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n## Superseded ({stamp})\n\n{reason}\n")
