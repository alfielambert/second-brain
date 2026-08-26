"""
Claim Store - the append-only, permanent audit/replay layer for the Second
Brain.

Two JSONL streams, one file per UTC day:
  ClaimStore/claims/YYYY-MM-DD.jsonl   - extracted claims (immutable once written)
  ClaimStore/events/YYYY-MM-DD.jsonl   - governance events (state transitions, human decisions)

Design rules (do not violate these when editing this file):
  - Claims are never rewritten or deleted. A claim's current state is derived
    by replaying events against it, not by mutating the claim record.
  - Every write is a single atomic write() of one JSON line, under an flock,
    so concurrent writers (a sync run, an approval command, a watchdog)
    never interleave or corrupt a line.
  - No external dependencies beyond the stdlib. This module has zero
    knowledge of connectors, KEP, or the vault's markdown notes - it only
    knows how to append and replay JSON lines.
"""

from __future__ import annotations

import fcntl
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from second_brain.vault import find_vault_root

SCHEMA_VERSION = 1

VALID_CLAIM_TYPES = {
    "observation", "fact", "entity_update", "relationship", "intention",
    "decision", "hypothesis", "experiment", "insight", "contradiction",
    "open_question", "published_content", "signal",
}

VALID_KEP_ACTIONS = {
    "auto_apply", "propose", "signal", "ignore", "contradiction",
    "merge_candidate", "supersede_candidate", "promotion_candidate",
}

VALID_EVENT_TYPES = {
    "kep-decision", "proposal-created", "proposal-decision", "auto-applied",
    "durable-write", "superseded", "merged", "split", "archived",
    "openlore-published", "connector-run", "capture-received",
}

VALID_OPERATIONS = {
    "enrich_existing",   # timestamp/signal/evidence append to something that already exists
    "create_entity",     # new Person/Company note
    "promote",           # hypothesis -> insight, or confidence-tier promotion
    "contradiction",     # conflicts with existing vault knowledge
    "supersede",         # a fact/decision that replaces an earlier one
    "merge",              # two entities should become one
    "split",              # one entity should become two
    "reclassify",         # changes a note's type/status with semantic impact
    "structural",         # new folder, new frontmatter field, schema change
    "weak_inference",     # not enough evidence to act on yet
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _claim_store_dirs(vault_root: Optional[Path] = None) -> tuple[Path, Path]:
    root = vault_root or find_vault_root()
    claim_store = root / "ClaimStore"
    return claim_store / "claims", claim_store / "events"


def _atomic_append_line(path: Path, obj: dict) -> None:
    """Append one JSON object as a single line, under an exclusive lock.

    A single write() of a line under PIPE_BUF-ish size is atomic on local
    filesystems; the flock additionally serializes cross-process writers so
    no two writers can ever race on the file open/seek-to-end/write sequence.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def append_claim(
    *,
    connector: str,
    source: dict,
    claim_type: str,
    entities: list[dict],
    content: str,
    evidence: list[dict],
    confidence: str,
    operation: str,
    target_note: Optional[str] = None,
    trace_id: Optional[str] = None,
    vault_root: Optional[Path] = None,
) -> dict:
    """Write one immutable claim record. Returns the full record written.

    `operation` is the extracting connector's classification of what kind of
    change this claim represents (see VALID_OPERATIONS) - KEP's routing
    decision (kep.classify_claim) is a deterministic function of this field
    plus claim_type/confidence, not a second judgement call.
    """
    if claim_type not in VALID_CLAIM_TYPES:
        raise ValueError(f"claim_type {claim_type!r} not in {sorted(VALID_CLAIM_TYPES)}")
    if confidence not in {"low", "medium", "high"}:
        raise ValueError(f"confidence must be low/medium/high, got {confidence!r}")
    if operation not in VALID_OPERATIONS:
        raise ValueError(f"operation {operation!r} not in {sorted(VALID_OPERATIONS)}")

    record = {
        "schema_version": SCHEMA_VERSION,
        "claim_id": _new_id("claim"),
        "trace_id": trace_id or _new_id("trace"),
        "ingested_at": _now_iso(),
        "connector": connector,
        "source": source,
        "claim_type": claim_type,
        "entities": entities,
        "content": content,
        "evidence": evidence,
        "confidence": confidence,
        "operation": operation,
        "target_note": target_note,
        "kep_state": "pending",
        "output_refs": [],
        "lifecycle_status": "active",
    }
    claims_dir, _ = _claim_store_dirs(vault_root)
    _atomic_append_line(claims_dir / f"{_today_str()}.jsonl", record)
    return record


def append_event(
    *,
    event_type: str,
    actor: str,
    payload: dict,
    claim_id: Optional[str] = None,
    channel: Optional[str] = None,
    vault_root: Optional[Path] = None,
) -> dict:
    """Write one governance event. Events are how claim/proposal state
    evolves over time without ever rewriting the original claim record."""
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"event_type {event_type!r} not in {sorted(VALID_EVENT_TYPES)}")

    record = {
        "schema_version": SCHEMA_VERSION,
        "event_id": _new_id("evt"),
        "claim_id": claim_id,
        "event_type": event_type,
        "occurred_at": _now_iso(),
        "actor": actor,
        "payload": payload,
    }
    if channel:
        record["channel"] = channel
    _, events_dir = _claim_store_dirs(vault_root)
    _atomic_append_line(events_dir / f"{_today_str()}.jsonl", record)
    return record


def iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_all_claims(since_date: Optional[str] = None, vault_root: Optional[Path] = None) -> Iterator[dict]:
    """Yield every claim across all daily shard files, optionally only
    files dated >= since_date (YYYY-MM-DD, string-sortable)."""
    claims_dir, _ = _claim_store_dirs(vault_root)
    for path in sorted(claims_dir.glob("*.jsonl")):
        if since_date and path.stem < since_date:
            continue
        yield from iter_jsonl(path)


def iter_all_events(since_date: Optional[str] = None, vault_root: Optional[Path] = None) -> Iterator[dict]:
    _, events_dir = _claim_store_dirs(vault_root)
    for path in sorted(events_dir.glob("*.jsonl")):
        if since_date and path.stem < since_date:
            continue
        yield from iter_jsonl(path)


def get_claim(claim_id: str, vault_root: Optional[Path] = None) -> Optional[dict]:
    for claim in iter_all_claims(vault_root=vault_root):
        if claim["claim_id"] == claim_id:
            return claim
    return None


def get_events_for_claim(claim_id: str, vault_root: Optional[Path] = None) -> list[dict]:
    return [e for e in iter_all_events(vault_root=vault_root) if e.get("claim_id") == claim_id]


def current_status(claim_id: str, vault_root: Optional[Path] = None) -> str:
    """Replay events for a claim to derive its current status. Never trust
    a mutated field on the claim itself - the claim is immutable."""
    events = get_events_for_claim(claim_id, vault_root=vault_root)
    status = "pending"
    for e in sorted(events, key=lambda e: e["occurred_at"]):
        t = e["event_type"]
        if t == "kep-decision":
            status = e["payload"].get("action", status)
        elif t == "proposal-decision":
            status = e["payload"].get("decision", status)
        elif t == "auto-applied":
            status = "auto_applied"
        elif t == "superseded":
            status = "superseded"
        elif t == "archived":
            status = "archived"
    return status


def pending_proposals(stale_after_days: int = 30, vault_root: Optional[Path] = None) -> list[dict]:
    """Claims currently sitting in propose state with no terminal decision
    yet, annotated with age_days and is_stale."""
    out = []
    now = datetime.now(timezone.utc)
    for claim in iter_all_claims(vault_root=vault_root):
        status = current_status(claim["claim_id"], vault_root=vault_root)
        if status not in ("propose", "pending"):
            continue
        events = get_events_for_claim(claim["claim_id"], vault_root=vault_root)
        proposal_events = [e for e in events if e["event_type"] == "proposal-created"]
        if not proposal_events:
            continue
        created_at = datetime.strptime(
            proposal_events[0]["occurred_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        age_days = (now - created_at).days
        out.append({**claim, "status": status, "age_days": age_days, "is_stale": age_days >= stale_after_days})
    return out


def _cli_status(args: list[str]) -> None:
    if not args:
        print("usage: python -m second_brain.claimstore status <claim_id>", file=sys.stderr)
        sys.exit(2)
    print(current_status(args[0]))


def _cli_pending(args: list[str]) -> None:
    stale_after = int(args[0]) if args else 30
    for p in pending_proposals(stale_after_days=stale_after):
        print(json.dumps({
            "claim_id": p["claim_id"], "content": p["content"],
            "age_days": p["age_days"], "is_stale": p["is_stale"],
        }))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m second_brain.claimstore <status|pending> [args]", file=sys.stderr)
        sys.exit(2)
    cmd, rest = sys.argv[1], sys.argv[2:]
    {"status": _cli_status, "pending": _cli_pending}.get(
        cmd, lambda _a: (_ for _ in ()).throw(SystemExit(f"unknown command {cmd!r}"))
    )(rest)
