# Changelog

## v0.2.0 - Reliable unattended sync

v0.1 showed how to turn evidence into governed knowledge. v0.2 focuses on
making that process survive unattended operation: per-connector execution
budgets, safe retries, idempotent recovery, connector health, deterministic
outbox delivery, and failure-safe knowledge distribution.

### Added

- `second_brain/resilience.py` - `run_step()` bounds a connector's full
  sync attempt with its own configured budget and returns a structured
  `ConnectorStepResult` instead of raising; `ConnectorReportedError` lets a
  connector report a self-detected failure with an explicit `error_type`
  and `retryable` flag.
- `second_brain/subprocess_timeout.py` - process-group-wide timeout
  enforcement for connectors that shell out to an external process, so a
  timed-out subprocess's own children are never orphaned.
- `second_brain/outbox.py` - a deterministic outbox for proposal delivery
  (`deliver_pending_proposals()`), plus a stdlib-only `TelegramNotifier`
  reference implementation of the `Notifier` protocol. A retried sync can
  never re-send a proposal that already went out.
- `second_brain/watchdog.py` - an independent, read-only check for
  connector staleness, meant to run as its own scheduled job separate from
  `sync`.
- `second_brain/reports.py` - the Current + History + Sources pattern for
  recurring, scheduled evidence, with create-only immutable per-run
  history snapshots and forward-only canonical state.
- Per-connector `session_timeout_seconds` in `second-brain.yml`, replacing
  a single global sync timeout.
- `python -m second_brain.health mark-checked` - a CLI surface for
  reporting connector health/cursor state from an external process, for
  connector shapes that can't call `health.py` directly as a library.

### Changed

- `claimstore.append_claim()` now accepts an explicit `dedupe_key` and
  returns whether the record is newly created, so callers can safely
  count/act on fresh work without re-deriving idempotency logic.
- `cli.py`'s routing, proposal-creation, and claim-apply steps each check
  their own completion marker before doing anything durable, so a crash
  partway through a run resumes correctly instead of repeating or
  permanently skipping the interrupted claim.
- `cmd_sync()` wraps each connector's full cycle in `resilience.run_step()`
  and records a `failed` execution as a `health.py` `failed` status,
  keeping the two status vocabularies (data-freshness vs. execution)
  distinct.

### Documentation

- `docs/architecture.md` - new Reliability section, the Current + History
  + Sources pattern, and an explicit statement of the OpenLore live-serve
  model and the "Second Brain governs, OpenLore distributes" boundary.
- `docs/connector-contract.md` - guidance for bounding a connector's
  execution time and reporting structured failures.
- `docs/roadmap.md` - moved shipped reliability items out of known gaps.

## v0.1.0

Initial release: deterministic governance core (Claim Store, KEP,
connector health/cursor state, locking, safe note writes), two working
connectors (`capture`, `x_bookmarks`), a CLI covering the full loop, a
Claude Code-native runtime layer, and a fictional demo dataset.
