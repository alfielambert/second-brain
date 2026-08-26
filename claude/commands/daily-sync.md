---
description: Run a governed sync across all enabled connectors
---

# Daily Sync

Read `second-brain.yml` in the current vault to see which connectors are
enabled. For each enabled connector:

1. **Gmail / Calendar / Notion** (if you have MCP tools connected for
   these): fetch anything new since the connector's last cursor
   (`second-brain status` shows `last_checked` per connector). For each
   item that represents real information - a decision, a fact about a
   person or company, an intention, a contradiction of something already
   in the vault - call:

   ```
   python -m second_brain.claimstore append-claim <<'JSON'
   {"connector": "gmail", "source": {"id": "<stable-thread-id>", "type": "email", "occurred_at": "...", "title": "...", "url": null},
    "claim_type": "fact", "entities": [...], "content": "...", "evidence": [...],
    "confidence": "high", "operation": "enrich_existing", "target_note": "People/Jane Smith.md"}
   JSON
   ```

   Use a **stable source ID** (Gmail thread ID, Notion page ID, calendar
   event ID) - never a title/date guess, so re-running never double-counts.
   Judge `confidence` and `operation` honestly: if you're not sure whether
   something is a fact or an inference, say `confidence: medium` or `low`
   and let KEP route it to human review rather than guessing high.

2. **X Bookmarks / capture** (no judgement needed): run
   `second-brain sync --connector x_bookmarks` (or `capture`) directly -
   these already emit safe weak-signal claims deterministically.

3. Once every connector has run, execute `second-brain route` to let KEP
   process everything newly appended.

4. Report a short digest: how many claims were auto-applied, how many
   proposals now need review (`second-brain claims --status propose`), and
   any connector that came back unhealthy (`second-brain status`).

Never write directly to a note in `People/`, `Companies/`, `Meetings/`,
`Decisions/`, `Hypotheses/`, or `Insights/` from this command - always go
through `append-claim` so KEP's routing table is the only thing deciding
what becomes durable.
