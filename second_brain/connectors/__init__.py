"""
Connector contract.

A connector's job stops at "here is evidence and my best guess at what kind
of claim it is" - it never decides where that claim ends up in the vault.
That's KEP's job (second_brain/kep.py), acting on the `operation` and
`confidence` a connector assigns.

Six methods, matching docs/connector-contract.md:

    discover(state)          -> list of raw source records not yet seen,
                                 using a stable source ID (never title/date
                                 guessing - see docs/connector-contract.md
                                 on idempotency)
    fetch(item)               -> full content for one discovered item
                                 (a no-op passthrough if discover() already
                                 returned full content)
    normalise(raw)             -> {"source": {...}, "text": ...} in a
                                 connector-agnostic shape
    extract_claims(normalised) -> list of kwargs dicts for
                                 claimstore.append_claim() (everything
                                 except vault_root)
    update_cursor(vault_root, item) -> persist that this item is now seen,
                                 via second_brain.health.update_state
    health(vault_root)         -> a second_brain.health status block

This is intentionally not an enforced abstract base class or plugin
registry - six documented methods are enough to make a new connector
understandable without a framework to learn first. See
second_brain/connectors/x_bookmarks.py for a full worked example, and
second_brain/connectors/capture.py for the simplest possible one.
"""

from __future__ import annotations

from typing import Protocol


class Connector(Protocol):
    name: str

    def discover(self, state: dict) -> list[dict]: ...
    def fetch(self, item: dict) -> dict: ...
    def normalise(self, raw: dict) -> dict: ...
    def extract_claims(self, normalised: dict) -> list[dict]: ...
    def update_cursor(self, vault_root, item: dict) -> None: ...
    def health(self, vault_root) -> dict: ...
