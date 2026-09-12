"""
watchdog.py - independent stale-sync detection.

The whole point of this module is that it does NOT run as a step inside
`second-brain sync` or any other part of the sync process. If sync itself
stops running (a broken cron job, a crashed launchd agent, a dependency
that stopped resolving), a staleness check *bundled inside* sync would
never fire - the exact failure mode it exists to catch is the one that
would silence it too. Schedule this as its own separate job (its own cron
line, its own launchd plist - see launchd/README.md), on its own cadence,
independent of whether a sync run happened at all.

It only reads state (health.stale_connectors(), which is itself already
read-only) and optionally sends one alert - it never writes to the Claim
Store or touches connector state itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from second_brain import health
from second_brain.outbox import Notifier
from second_brain.vault import find_vault_root, load_config


def check(vault_root: Optional[Path] = None) -> dict:
    """Read-only. Returns which connectors are stale (never succeeded, or
    last succeeded longer ago than this vault's configured
    watchdog.stale_after_hours) and a summary count."""
    root = vault_root or find_vault_root()
    config = load_config(root)
    max_age_hours = config.get("watchdog", {}).get("stale_after_hours", 36)

    all_states = health.all_states(vault_root=root)
    stale = health.stale_connectors(max_age_hours=max_age_hours, vault_root=root)

    return {
        "stale": stale,
        "stale_after_hours": max_age_hours,
        "total_connectors": len(all_states),
        "healthy_count": len(all_states) - len(stale),
    }


def _render_alert(result: dict) -> str:
    lines = [f"Second Brain: {len(result['stale'])} connector(s) stale (threshold {result['stale_after_hours']}h)"]
    for s in result["stale"]:
        age = f"{s['age_hours']}h ago" if s["age_hours"] is not None else "never succeeded"
        lines.append(f"  - {s['connector']}: {s['reason']} ({age})")
    return "\n".join(lines)


def run(vault_root: Optional[Path] = None, notifier: Optional[Notifier] = None) -> dict:
    """Run one check, optionally alerting via `notifier` if anything is
    stale. Does not track "have I already alerted about this" the way a
    fuller implementation might - each run either finds staleness (and
    alerts, if a notifier is given) or doesn't; deduplicating repeat
    alerts across runs is a reasonable follow-on, not required for the
    core guarantee this module exists to provide (independent detection),
    so kept out of v0.2.0 rather than added speculatively."""
    result = check(vault_root)
    if result["stale"] and notifier is not None:
        try:
            notifier.send_text(_render_alert(result))
        except Exception as e:  # noqa: BLE001 - a failed alert must not crash the watchdog run itself
            result["alert_error"] = f"{type(e).__name__}: {e}"
    return result


def main() -> None:
    config = load_config()
    notifier = None
    if config.get("notifications", {}).get("enabled") and config.get("notifications", {}).get("channel") == "telegram":
        from second_brain.outbox import TelegramNotifier
        notifier = TelegramNotifier.from_config(config)

    result = run(notifier=notifier)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["stale"] else 0)


if __name__ == "__main__":
    main()
