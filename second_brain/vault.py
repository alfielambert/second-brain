"""
Vault root resolution and scaffolding.

A "vault" is just a directory with a second-brain.yml config file and a
ClaimStore/ subfolder. There is nothing hardcoded about its location -
resolution order is:

  1. explicit `vault_root` argument, if the caller passed one
  2. $SECOND_BRAIN_VAULT environment variable
  3. walking up from the current directory looking for second-brain.yml

This is the one module every other part of the deterministic core depends
on for "where is my data" - keeping that logic in one place is what lets a
vault live anywhere, not just relative to this package's install location.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

CONFIG_NAME = "second-brain.yml"

VAULT_FOLDERS = [
    "ClaimStore/claims",
    "ClaimStore/events",
    "ClaimStore/state",
    "ClaimStore/captures",
    "People",
    "Companies",
    "Meetings",
    "Hypotheses",
    "Insights",
    "Decisions",
    "Sources",
    "Proposals",
    "Packs",
]


class VaultNotFoundError(RuntimeError):
    pass


def find_vault_root(start: Optional[Path] = None) -> Path:
    env = os.environ.get("SECOND_BRAIN_VAULT")
    if env:
        return Path(env).expanduser().resolve()

    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / CONFIG_NAME).exists():
            return candidate

    raise VaultNotFoundError(
        "No Second Brain vault found. Run 'second-brain init' to create one, "
        "set SECOND_BRAIN_VAULT to an existing vault's path, or cd into one."
    )


def default_config() -> dict:
    return {
        "vault": ".",
        "connectors": {
            # session_timeout_seconds bounds resilience.run_step()'s whole
            # sync attempt for this connector (discover+fetch+normalise+
            # extract_claims+update_cursor), not any one network call
            # inside it - see resilience.py's module docstring for why
            # that distinction matters. These are illustrative starting
            # points for connectors that make a handful of network calls,
            # not measured optima - widen a connector's budget if it
            # legitimately needs to process more items per run than these
            # assume, the same way you'd size any timeout: from your own
            # connector's real behaviour, not a number copied from here.
            "capture": {"enabled": True, "session_timeout_seconds": 60},
            "x_bookmarks": {"enabled": False, "session_timeout_seconds": 180},
        },
        "governance": {
            # cli = approve/reject via `second-brain approve|reject`.
            "approval_channel": "cli",
        },
        "notifications": {
            # Deterministic outbox (second_brain/outbox.py): a connector
            # sync step only ever durably creates a proposal; delivery to
            # a notification channel happens afterwards, in a separate,
            # idempotent step, so a retried sync can never re-send a
            # proposal that already went out. See docs/architecture.md.
            "enabled": False,
            "channel": None,  # e.g. "telegram" - see outbox.TelegramNotifier
            "telegram": {
                # Never put a real token in this file. Both are read from
                # environment variables at send time.
                "bot_token_env": "SECOND_BRAIN_TELEGRAM_BOT_TOKEN",
                "chat_id_env": "SECOND_BRAIN_TELEGRAM_CHAT_ID",
            },
        },
        "watchdog": {
            # Independent of whether sync itself is running - see
            # second_brain/watchdog.py's module docstring for why that
            # independence is the entire point.
            "stale_after_hours": 36,
        },
        "distribution": {
            "openlore": {
                "enabled": False,
                # A plain directory path. Second Brain writes governed
                # markdown+frontmatter here; OpenLore serves it live,
                # directly, with no separate publish/ingestion step - see
                # docs/openlore-integration.md. This is a genuinely
                # different (simpler) distribution model than a
                # publish-then-verify pipeline, not an unfinished version
                # of one.
                "publish_path": None,
            },
        },
    }


def load_config(vault_root: Optional[Path] = None) -> dict:
    root = vault_root or find_vault_root()
    config_path = root / CONFIG_NAME
    if not config_path.exists():
        return default_config()
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or default_config()


def init_vault(path: Path, with_sample: bool = False) -> Path:
    path = path.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)

    for folder in VAULT_FOLDERS:
        (path / folder).mkdir(parents=True, exist_ok=True)

    config_path = path / CONFIG_NAME
    if not config_path.exists():
        config_path.write_text(yaml.safe_dump(default_config(), sort_keys=False))

    if with_sample:
        from second_brain.examples import acme

        acme.seed(path)
        acme.seed_reports(path)

    return path
