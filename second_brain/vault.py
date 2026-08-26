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
            "capture": {"enabled": True},
            "x_bookmarks": {"enabled": False},
        },
        "governance": {
            # cli = approve/reject via `second-brain approve|reject`.
            # telegram is documented in claude/README.md as a v1 Claude
            # Code-layer feature, not part of the deterministic core.
            "approval_channel": "cli",
        },
        "distribution": {
            "openlore": {
                "enabled": False,
                # A plain directory path. Second Brain writes governed
                # markdown+frontmatter here; OpenLore serves it. See
                # docs/openlore-integration.md.
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

    return path
