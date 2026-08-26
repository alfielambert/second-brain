"""
capture - the simplest possible connector, and the recommended first one to
enable (see docs/architecture.md, Level 2 of the onboarding path).

Drop a .md, .txt, or .url file into ClaimStore/captures/inbox/ and running
`second-brain sync --connector capture` turns each one into a single weak
claim: claim_type=signal, operation=weak_inference, confidence=low. That's
deliberate, not a placeholder - a captured note is evidence that a topic
matters, not yet an asserted fact about the world. KEP (second_brain/kep.py)
always routes weak_inference/low-confidence claims to "signal", never to a
proposal, so capturing something is always safe and never spams you with
approvals. It becomes durable knowledge only once a pattern repeats or you
promote it yourself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from second_brain import health

NAME = "capture"
INBOX_SUBDIR = "ClaimStore/captures/inbox"
PROCESSED_SUBDIR = "ClaimStore/captures/processed"


def discover(vault_root: Path) -> list[dict]:
    inbox = vault_root / INBOX_SUBDIR
    inbox.mkdir(parents=True, exist_ok=True)
    return [
        {"path": str(p), "name": p.name}
        for p in sorted(inbox.iterdir())
        if p.is_file() and p.suffix.lower() in {".md", ".txt", ".url"}
    ]


def fetch(item: dict) -> dict:
    text = Path(item["path"]).read_text(encoding="utf-8", errors="replace")
    return {**item, "text": text}


def normalise(raw: dict) -> dict:
    return {
        "source": {
            "id": raw["path"],
            "type": "capture",
            "occurred_at": None,
            "title": raw["name"],
            "url": None,
        },
        "text": raw["text"].strip(),
    }


def extract_claims(normalised: dict) -> list[dict]:
    if not normalised["text"]:
        return []
    return [{
        "connector": NAME,
        "source": normalised["source"],
        "claim_type": "signal",
        "entities": [],
        "content": normalised["text"][:500],
        "evidence": [{"text": normalised["text"][:2000], "speaker": None, "location": None}],
        "confidence": "low",
        "operation": "weak_inference",
    }]


def update_cursor(vault_root: Path, item: dict) -> None:
    src = Path(item["path"])
    processed_dir = vault_root / PROCESSED_SUBDIR
    processed_dir.mkdir(parents=True, exist_ok=True)
    src.rename(processed_dir / src.name)


def get_health(vault_root: Path) -> dict:
    return health.get_state(NAME, vault_root=vault_root)
