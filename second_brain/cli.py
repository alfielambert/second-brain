"""
second-brain - CLI for the deterministic core.

    second-brain init [PATH] [--with-sample]
    second-brain claims [--status STATUS]
    second-brain route
    second-brain approve CLAIM_ID [--all-pending]
    second-brain reject CLAIM_ID [--reason TEXT]
    second-brain sync --connector NAME
    second-brain status
    second-brain compile [--target NAME]

This CLI is the portable deterministic core only. It does not call any LLM
and does not require Claude Code. The Claude Code-native runtime layer
(source interpretation, richer claim extraction, Daily Sync orchestration,
context synthesis) lives in claude/ and is documented separately - see
claude/README.md and docs/architecture.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from second_brain import claimstore, health, kep, notes
from second_brain.vault import find_vault_root, init_vault, load_config, VaultNotFoundError

DURABLE_STATUSES = {"auto_applied", "approved"}


def cmd_init(args: argparse.Namespace) -> None:
    path = Path(args.path)
    root = init_vault(path, with_sample=args.with_sample)
    print(f"Initialized vault at {root}")
    if args.with_sample:
        n = len(list(claimstore.iter_all_claims(vault_root=root)))
        print(f"Seeded {n} sample claims (fictional Acme dataset).")
    print("\nNext:")
    print(f"  cd {path}")
    print("  second-brain claims          # see what was captured")
    print("  second-brain route           # run KEP, create proposals")
    print("  second-brain approve --all-pending   # approve everything (demo speed)")
    print("  second-brain compile --target founder")


def cmd_claims(args: argparse.Namespace) -> None:
    root = find_vault_root()
    for claim in claimstore.iter_all_claims(vault_root=root):
        status = claimstore.current_status(claim["claim_id"], vault_root=root)
        if args.status and status != args.status:
            continue
        print(f"{claim['claim_id']}  [{status:15}]  {claim['operation']:10}  {claim['content'][:70]}")


def cmd_route(args: argparse.Namespace) -> None:
    root = find_vault_root()
    routed = 0
    for claim in claimstore.iter_all_claims(vault_root=root):
        existing = claimstore.get_events_for_claim(claim["claim_id"], vault_root=root)
        if any(e["event_type"] == "kep-decision" for e in existing):
            continue  # already routed

        decision = kep.classify_claim(claim)
        claimstore.append_event(
            vault_root=root, event_type="kep-decision", actor="kep", claim_id=claim["claim_id"],
            payload={"action": decision.action, "reason": decision.reason},
        )
        routed += 1

        if decision.action == "auto_apply":
            claimstore.append_event(
                vault_root=root, event_type="auto-applied", actor="kep", claim_id=claim["claim_id"], payload={},
            )
            _apply_claim(root, claim, actor="kep")
        elif decision.action == "signal":
            pass  # logged as a claim only; never proposed, never written
        else:
            _create_proposal(root, claim, decision)

    print(f"Routed {routed} new claim(s) through KEP.")


def _create_proposal(root: Path, claim: dict, decision) -> None:
    claimstore.append_event(
        vault_root=root, event_type="proposal-created", actor="kep", claim_id=claim["claim_id"],
        payload={"action": decision.action, "reason": decision.reason},
    )
    proposal_path = root / "Proposals" / f"{claim['claim_id']}.md"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        f"---\nclaim_id: {claim['claim_id']}\noperation: {claim['operation']}\n"
        f"action: {decision.action}\nstatus: pending\ntarget_note: {claim['target_note']}\n---\n\n"
        f"## Content\n\n{claim['content']}\n\n## Why this needs review\n\n{decision.reason}\n\n"
        f"## Evidence\n\n" + "\n".join(f"- {e['text']}" for e in claim["evidence"]) + "\n"
    )


def _apply_claim(root: Path, claim: dict, actor: str) -> None:
    if claim["operation"] == "supersede" and claim["target_note"]:
        for prior in claimstore.iter_all_claims(vault_root=root):
            if prior["claim_id"] == claim["claim_id"] or prior["target_note"] != claim["target_note"]:
                continue
            if claimstore.current_status(prior["claim_id"], vault_root=root) in DURABLE_STATUSES:
                notes.mark_superseded(root, claim["target_note"], reason=f"Superseded by claim {claim['claim_id']}: {claim['content']}")
                claimstore.append_event(
                    vault_root=root, event_type="superseded", actor=actor, claim_id=prior["claim_id"],
                    payload={"superseded_by": claim["claim_id"]},
                )

    if claim["target_note"]:
        frontmatter = {
            "type": claim["claim_type"],
            "status": "active",
            "source-connector": claim["connector"],
            "confidence": claim["confidence"],
        }
        notes.write_note(root, claim["target_note"], claim["content"], frontmatter)

    claimstore.append_event(
        vault_root=root, event_type="durable-write", actor=actor, claim_id=claim["claim_id"],
        payload={"target_note": claim["target_note"]},
    )


def cmd_approve(args: argparse.Namespace) -> None:
    root = find_vault_root()
    targets = [args.claim_id] if args.claim_id else None

    if args.all_pending:
        targets = [
            c["claim_id"] for c in claimstore.iter_all_claims(vault_root=root)
            if claimstore.current_status(c["claim_id"], vault_root=root) in (
                "propose", "supersede_candidate", "promotion_candidate", "merge_candidate", "contradiction",
            )
        ]

    if not targets:
        print("Nothing to approve. Pass a claim_id or --all-pending.", file=sys.stderr)
        sys.exit(2)

    for claim_id in targets:
        claim = claimstore.get_claim(claim_id, vault_root=root)
        if not claim:
            print(f"Unknown claim_id: {claim_id}", file=sys.stderr)
            continue
        claimstore.append_event(
            vault_root=root, event_type="proposal-decision", actor=args.actor, claim_id=claim_id,
            channel="cli", payload={"decision": "approved"},
        )
        _apply_claim(root, claim, actor=args.actor)
        print(f"Approved {claim_id} -> {claim['target_note'] or '(no vault write)'}")


def cmd_reject(args: argparse.Namespace) -> None:
    root = find_vault_root()
    claimstore.append_event(
        vault_root=root, event_type="proposal-decision", actor=args.actor, claim_id=args.claim_id,
        channel="cli", payload={"decision": "rejected", "reason": args.reason},
    )
    print(f"Rejected {args.claim_id}. No vault write.")


def cmd_sync(args: argparse.Namespace) -> None:
    root = find_vault_root()
    if args.connector == "capture":
        from second_brain.connectors import capture as conn
        items = conn.discover(root)
    elif args.connector == "x_bookmarks":
        from second_brain.connectors import x_bookmarks as conn
        items = conn.discover(root, limit=args.limit)
    else:
        print(f"Unknown connector: {args.connector}", file=sys.stderr)
        sys.exit(2)

    emitted = 0
    for item in items:
        raw = conn.fetch(item)
        normalised = conn.normalise(raw)
        for claim_kwargs in conn.extract_claims(normalised):
            claimstore.append_claim(vault_root=root, **claim_kwargs)
            emitted += 1
        conn.update_cursor(root, item)

    health.mark_checked(args.connector, "current_no_change" if emitted == 0 else "healthy", vault_root=root, claims_emitted=emitted)
    claimstore.append_event(
        vault_root=root, event_type="connector-run", actor=args.connector,
        payload={"items_discovered": len(items), "claims_emitted": emitted},
    )
    print(f"{args.connector}: {len(items)} item(s) discovered, {emitted} claim(s) emitted. Run 'second-brain route' next.")


def cmd_status(args: argparse.Namespace) -> None:
    root = find_vault_root()
    states = health.all_states(vault_root=root)
    if not states:
        print("No connectors have run yet.")
    for name, block in states.items():
        print(f"{name:15} status={block.get('status', 'unknown'):18} last_checked={block.get('last_checked', '-')}")
    stale = health.stale_connectors(vault_root=root)
    if stale:
        print("\nStale connectors:")
        for s in stale:
            print(f"  {s['connector']}: {s['reason']}")
    pending = claimstore.pending_proposals(vault_root=root)
    print(f"\n{len(pending)} pending proposal(s).")


def cmd_compile(args: argparse.Namespace) -> None:
    root = find_vault_root()
    durable = [
        c for c in claimstore.iter_all_claims(vault_root=root)
        if claimstore.current_status(c["claim_id"], vault_root=root) in DURABLE_STATUSES
    ]
    excluded_pending = [
        c for c in claimstore.iter_all_claims(vault_root=root)
        if claimstore.current_status(c["claim_id"], vault_root=root) not in DURABLE_STATUSES | {"rejected", "superseded"}
    ]

    by_type: dict[str, list[dict]] = {}
    for c in durable:
        by_type.setdefault(c["claim_type"], []).append(c)

    lines = [f"# {args.target.title()} Context Pack\n", f"_Compiled {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}_\n"]
    for claim_type, claims in sorted(by_type.items()):
        lines.append(f"\n## {claim_type.replace('_', ' ').title()}\n")
        for c in claims:
            lines.append(f"- {c['content']}")

    lines.append("\n## Known Unknowns\n")
    if excluded_pending:
        for c in excluded_pending:
            lines.append(f"- Not yet governed knowledge (status pending review): {c['content'][:100]}")
    else:
        lines.append("- None outstanding.")

    lines.append("\n## Compile Report\n")
    lines.append(f"- Included: {len(durable)} durable claim(s)")
    lines.append(f"- Excluded (not yet governed): {len(excluded_pending)}")
    lines.append(f"- Target: {args.target}")

    out_path = root / "Packs" / f"{args.target}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Compiled {out_path} ({len(durable)} durable claims included)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="second-brain")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a new vault")
    p_init.add_argument("path", nargs="?", default=".")
    p_init.add_argument("--with-sample", action="store_true", help="Seed the fictional Acme demo dataset")
    p_init.set_defaults(func=cmd_init)

    p_claims = sub.add_parser("claims", help="List claims and their current status")
    p_claims.add_argument("--status", default=None)
    p_claims.set_defaults(func=cmd_claims)

    p_route = sub.add_parser("route", help="Run KEP over any un-routed claims")
    p_route.set_defaults(func=cmd_route)

    p_approve = sub.add_parser("approve", help="Approve a proposal")
    p_approve.add_argument("claim_id", nargs="?", default=None)
    p_approve.add_argument("--all-pending", action="store_true")
    p_approve.add_argument("--actor", default="local-user")
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject", help="Reject a proposal")
    p_reject.add_argument("claim_id")
    p_reject.add_argument("--reason", default=None)
    p_reject.add_argument("--actor", default="local-user")
    p_reject.set_defaults(func=cmd_reject)

    p_sync = sub.add_parser("sync", help="Run a connector's discover/fetch/normalise/extract_claims cycle")
    p_sync.add_argument("--connector", required=True, choices=["capture", "x_bookmarks"])
    p_sync.add_argument("--limit", type=int, default=None)
    p_sync.set_defaults(func=cmd_sync)

    p_status = sub.add_parser("status", help="Connector health and pending-proposal summary")
    p_status.set_defaults(func=cmd_status)

    p_compile = sub.add_parser("compile", help="Compile durable knowledge into a Context Pack")
    p_compile.add_argument("--target", default="founder")
    p_compile.set_defaults(func=cmd_compile)

    args = parser.parse_args()
    try:
        args.func(args)
    except (VaultNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
