"""
outbox.py - deterministic delivery of proposals to a notification channel.

A connector sync step, or `second-brain route`, only ever durably creates
a proposal (a `proposal-created` event plus a Proposals/*.md file) - it
never sends a notification itself. Delivery happens here, in a plain,
non-model, non-retried-alongside-everything-else step:

    proposal-created (unsent) -> notifier.send_proposal() -> proposal-sent event

Every call to deliver_pending_proposals() re-scans for claims with a
proposal-created event but no proposal-sent event yet, so calling it again
(right after a failed send, in a later `second-brain sync` run, from a cron
job) only ever sends what's still unsent. This is what makes "a retried
sync must never cause the same proposal to be sent twice" a real, testable
guarantee, rather than something a retried connector step has to remember
not to do itself - see resilience.py's module docstring for the matching
principle on the ingestion side.

Notifier is a minimal protocol (one method: send_proposal(dict)) so this
module has zero hard dependency on any specific channel. TelegramNotifier
below is one concrete, working reference implementation - Telegram's API
itself isn't secret, only the bot token is, which is read from an
environment variable at send time and never written to config or code.
Write your own Notifier for any other channel; deliver_pending_proposals()
doesn't care which one you pass it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Protocol

from second_brain import claimstore
from second_brain.vault import find_vault_root

TELEGRAM_MAX_MESSAGE_CHARS = 3900  # Telegram's real cap is 4096 UTF-16 code
                                    # units; this is a safe, simple margin,
                                    # not an exact accounting of it.


class Notifier(Protocol):
    def send_proposal(self, proposal: dict) -> None:
        """Raise on failure. deliver_pending_proposals() catches per-item,
        so raising here marks just this one proposal as still-pending -
        it does not stop the rest of the batch."""
        ...

    def send_text(self, text: str) -> None:
        """Plain free-text alert - used by watchdog.py, not by the
        proposal outbox. A separate method from send_proposal because the
        two are genuinely different message shapes (structured governance
        item vs. a one-line operational alert), not because they need
        different delivery mechanics."""
        ...


class TelegramNotifier:
    """Reference Notifier. Stdlib-only (urllib), no extra dependency.
    Token and chat ID must be passed in explicitly - use from_config() to
    load them from the environment variables named in vault config,
    rather than ever hardcoding a real token."""

    def __init__(self, bot_token: str, chat_id: str):
        if not bot_token or not chat_id:
            raise ValueError("TelegramNotifier requires a non-empty bot_token and chat_id")
        self._bot_token = bot_token
        self._chat_id = chat_id

    @classmethod
    def from_config(cls, config: dict) -> "TelegramNotifier":
        tg = config.get("notifications", {}).get("telegram", {})
        token_env = tg.get("bot_token_env", "SECOND_BRAIN_TELEGRAM_BOT_TOKEN")
        chat_env = tg.get("chat_id_env", "SECOND_BRAIN_TELEGRAM_CHAT_ID")
        return cls(os.environ.get(token_env, ""), os.environ.get(chat_env, ""))

    def send_proposal(self, proposal: dict) -> None:
        self._call("sendMessage", {
            "chat_id": self._chat_id,
            "text": render_proposal_text(proposal),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })

    def send_text(self, text: str) -> None:
        body = escape_html(text)
        if len(body) > TELEGRAM_MAX_MESSAGE_CHARS:
            body = body[:TELEGRAM_MAX_MESSAGE_CHARS] + "\n... (truncated)"
        self._call("sendMessage", {"chat_id": self._chat_id, "text": body, "parse_mode": "HTML"})

    def _call(self, method: str, payload: dict) -> dict:
        url = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Telegram API error {e.code}: {e.read().decode(errors='replace')}") from e
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API error: {body}")
        return body


def escape_html(text: object) -> str:
    """Escape for Telegram's HTML parse_mode - the only three characters
    that mean anything to it. Deliberately not using Telegram's legacy
    Markdown mode: real proposal content routinely contains characters
    (underscores, asterisks, brackets) that break that parser."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_proposal_text(proposal: dict) -> str:
    lines = [
        f"<b>New proposal</b> - confidence: {escape_html(proposal.get('confidence', ''))}",
        "",
        escape_html(proposal.get("proposed_change", ""))[:2000],
    ]
    reasoning = proposal.get("reasoning")
    if reasoning:
        lines += ["", f"<i>{escape_html(reasoning)[:500]}</i>"]
    lines += ["", f"claim_id: <code>{escape_html(proposal.get('proposal_id', ''))}</code>"]

    text = "\n".join(lines)
    if len(text) > TELEGRAM_MAX_MESSAGE_CHARS:
        text = text[:TELEGRAM_MAX_MESSAGE_CHARS] + "\n... (truncated)"
    return text


def _pending_unsent_proposals(vault_root: Optional[Path] = None) -> list[dict]:
    out = []
    for claim in claimstore.iter_all_claims(vault_root=vault_root):
        claim_id = claim["claim_id"]
        events = claimstore.get_events_for_claim(claim_id, vault_root=vault_root)
        created = next((e for e in events if e["event_type"] == "proposal-created"), None)
        if created is None:
            continue
        if any(e["event_type"] == "proposal-sent" for e in events):
            continue
        out.append({"claim": claim, "proposal_created": created})
    return out


def _extract_section(text: str, heading: str) -> str:
    if heading not in text:
        return ""
    after = text.split(heading, 1)[1]
    return after.split("##", 1)[0].strip()


def _load_proposal_dict(vault_root: Path, claim: dict, proposal_created_event: dict) -> dict:
    """Reconstruct what a Notifier needs from the claim record plus the
    human-readable Proposal file (see cli.py's _create_proposal for the
    format) - the file is the source of truth for the "why" prose."""
    claim_id = claim["claim_id"]
    proposal_path = vault_root / "Proposals" / f"{claim_id}.md"
    reasoning = ""
    if proposal_path.exists():
        reasoning = _extract_section(proposal_path.read_text(encoding="utf-8"), "## Why this needs review")
    return {
        "proposal_id": claim_id,
        "proposed_change": claim.get("content", ""),
        "reasoning": reasoning or proposal_created_event["payload"].get("reason", ""),
        "confidence": claim.get("confidence", ""),
    }


def deliver_pending_proposals(notifier: Notifier, vault_root: Optional[Path] = None) -> dict:
    """Send every not-yet-sent proposal through `notifier`, exactly once
    each. Never raises for an individual proposal's send failure -
    records it in the returned summary and continues, so one bad proposal
    (malformed content, a transient API error) can't block delivery of the
    rest; that proposal simply stays pending (still has proposal-created,
    still lacks proposal-sent) for the next call to retry. Idempotent
    across repeated calls: a proposal already marked proposal-sent is
    always skipped on re-scan, so calling this again - this run, or a
    later one - cannot re-send anything already delivered."""
    root = vault_root or find_vault_root()
    sent = 0
    failed = 0
    details: list[dict] = []

    for item in _pending_unsent_proposals(vault_root=root):
        claim = item["claim"]
        claim_id = claim["claim_id"]
        try:
            proposal = _load_proposal_dict(root, claim, item["proposal_created"])
            notifier.send_proposal(proposal)
            claimstore.append_event(
                vault_root=root, event_type="proposal-sent", actor="outbox", claim_id=claim_id, payload={},
            )
            sent += 1
            details.append({"claim_id": claim_id, "sent": True})
        except Exception as e:  # noqa: BLE001 - one bad proposal must not block the rest of the outbox
            failed += 1
            details.append({"claim_id": claim_id, "sent": False, "error": f"{type(e).__name__}: {e}"})

    return {"sent": sent, "failed": failed, "details": details}
