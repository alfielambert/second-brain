# Architecture

## The core idea

Most "AI memory" tools store information and hope retrieval finds the right
thing later. Second Brain does something different: it decides what
deserves to become knowledge in the first place, and keeps a permanent,
replayable record of why.

```
Evidence -> Claims -> Governance (KEP) -> Durable Knowledge -> Compiled Context
```

Every piece of evidence a connector sees becomes a **claim** - an
append-only, immutable record of "here's what I observed, here's how
confident I am, here's what kind of change it represents." Claims are never
edited. **KEP** (Knowledge Evolution Protocol) is a deterministic lookup
table, not a model call, that decides what happens to a claim next: written
automatically, held for human review as a proposal, or logged as a weak
signal that doesn't yet earn a place in the vault. Only after that
governance step does anything become **durable knowledge** - a markdown
note you or an agent can actually trust. The **compiler** then assembles
durable knowledge into a **Context Pack** scoped to a specific task, always
showing what it excluded and why (its "Known Unknowns").

## Local mode

```
Sources -> Connectors -> Claim Store -> KEP -> Governed Knowledge -> Local AI
```

Everything above runs on your machine, in your own vault directory, with no
network dependency beyond whatever a connector needs to reach its source
(e.g. the X API). Nothing here requires OpenLore.

## Multiplayer mode

```
Sources -> Connectors -> Claim Store -> KEP -> Governed Knowledge -> OpenLore -> Multiple AI agents
```

The only thing that changes is the last step. OpenLore
(https://github.com/aakarim/go-openlore) is a separate, already
open-source, MIT-licensed knowledge server - not a proprietary add-on. It
knows nothing about claims, KEP, or this schema; it just serves a directory
of markdown+frontmatter over SSH/MCP/HTTP to authenticated identities.
There is no separate publish/ingestion/sync step between Second Brain and
OpenLore - OpenLore is pointed at the vault's governed-knowledge directory
and serves it live, directly, on every request. Second Brain never pushes
to it and OpenLore never pulls a copy; there is exactly one copy of the
knowledge on disk. See docs/openlore-integration.md for exactly how the
two connect.

This is the core principle worth stating explicitly: **Second Brain
creates and governs knowledge. OpenLore distributes governed knowledge to
agents.** The two are cleanly separable - you do not need OpenLore to
build or use the Second Brain locally, and everything through "Governed
Knowledge" above works identically whether or not OpenLore is ever
configured.

## Reliability: surviving unattended operation

A Second Brain that only runs when you're watching it isn't very useful -
the whole point is a scheduled sync that runs unattended, night after
night, and is still trustworthy when nobody checked the exit code. Four
mechanisms make that possible, all in the connector-agnostic core
(`second_brain/`), independent of any particular connector or runtime:

**Bounded, independent connector sessions.** Every connector's full sync
attempt (discover → fetch → normalise → extract_claims → update_cursor)
runs inside `resilience.run_step()`, which enforces one connector's own
configured `session_timeout_seconds` and returns a `ConnectorStepResult`
(`ok` / `degraded` / `failed`) - it never raises. Budgets are per
connector, not global: a connector that legitimately does more work per
run (say, a large mailbox scan) can be given more time without changing
what a fast connector is allowed. A connector that wants to report a
failure it detected itself (an auth error, a malformed response) raises
`ConnectorReportedError` with an explicit `error_type` and `retryable`
flag, rather than an ordinary exception - that distinction is what lets
the orchestrator decide whether retrying later is even worth attempting.
`second_brain/subprocess_timeout.py` provides the same guarantee for a
connector that shells out to an external process: on timeout it signals
the whole process group, not just the immediate child, so a subprocess's
own children can never be orphaned running past their budget.

**Retries are safe because writes are idempotent, not because failures
are rare.** Every claim carries a `dedupe_key` (default
`connector:source.id:operation`); re-emitting the same claim after a
crash and retry is a no-op, not a duplicate. Routing, proposal creation,
and applying a claim each check their own completion marker
(`claim_needs_kep_routing`, `get_kep_decision`, `has_event`) before doing
anything durable, so a process that dies halfway through - after routing
but before applying, say - resumes correctly on the next run instead of
either repeating the side effect or silently skipping the claim forever.
See docs/claim-store-and-kep.md for the exact guard checks.

**Two status vocabularies that are never collapsed into one.** A
connector's *data-freshness* status (`healthy` / `current_no_change` /
`degraded` / `failed` / `stale` / `auth_required`, in `second_brain/health.py`)
answers "is this connector's data up to date," and is set by the
connector itself. The orchestrator's *execution* status (`ok` /
`degraded` / `failed`, from `resilience.run_step()`) answers "did this
run's attempt complete," and is set externally, by whatever called the
connector. A connector can execute successfully and correctly report
`current_no_change` (nothing new to ingest); a connector can also fail to
execute at all, which is a `health.py` `failed` regardless of what its
own internal logic thinks. Conflating these two produces exactly the
false alarm a watchdog exists to avoid: alerting on "nothing changed"
as if it were "something broke."

**A deterministic outbox for notifications.** A sync step only ever
durably creates a proposal (a `proposal-created` governance event);
delivering that proposal to a human-facing channel (Telegram, or any
`Notifier` implementation) happens afterwards, in a separate, idempotent
step - `outbox.deliver_pending_proposals()` - that scans for proposals
without a matching `proposal-sent` event and sends exactly those. A
retried sync can never re-send a proposal that already went out, and a
notification failure can never block or corrupt the knowledge the sync
step already wrote. `second_brain/outbox.py` ships a stdlib-only
`TelegramNotifier` as a reference implementation of the `Notifier`
protocol; writing your own for another channel means implementing two
methods (`send_proposal`, `send_text`).

**An independent, read-only watchdog.** `second_brain/watchdog.py` checks
which connectors have gone stale (never succeeded, or no success within
`watchdog.stale_after_hours`) and, if any have, sends one alert. It never
writes connector state itself - it only reads what `health.py` already
recorded - and it's meant to run as its own separately scheduled job, not
as a step inside `sync`, precisely so a broken sync process can't also
take down the thing that's supposed to notice it broke.

## Recurring reports: Current + History + Sources

Some evidence arrives on a schedule rather than once - a weekly metrics
report, a recurring scan result. `second_brain/reports.py` gives that
shape a dedicated, three-tier pattern, deliberately separate from the
Claim Store:

```
Sources/<connector>/...      raw evidence, immutable, never rewritten
Reports/<subject>.md         CURRENT: latest governed state - moves forward only
Reports/History/<subject>/
    YYYY-MM-DD.md             one immutable snapshot per run
```

An agent reads `Reports/<subject>.md` first for the concise current
truth, and only drills into `History/` or `Sources/` when it specifically
needs to see what changed or re-derive something from the original
evidence. The write contract (`write_report()`) is idempotent in both
directions: writing the same run twice with identical content is a safe
no-op; writing the same run with *different* content raises
`HistoryConflictError` rather than silently picking a winner, because
that situation - the same historical run regenerating differently - is a
genuine data-integrity problem that deserves a human's attention, not an
automatic resolution. The canonical file only ever moves forward:
writing an older run than what's already current is also a no-op, so
there's no code path through this API that can regress current state to
something stale.

Report notes are never source material for a claim - they summarise
already-governed state. If a report reveals something that should become
a claim, that's extracted as a claim explicitly and separately, the same
way any other evidence would be.

## Two runtimes, one deterministic core

A meaningful part of "the intelligence" here - deciding a bookmark is
actually a Decision and not just an Observation, orchestrating a daily sync
across several connectors, synthesizing prose for a Context Pack - is a
genuine judgement call. Rather than fake that with brittle heuristics, v1
draws an explicit line:

```
Portable deterministic core              Claude Code runtime (v1)
├── Claim Store                          ├── source interpretation
├── KEP routing                          ├── claim extraction requiring
├── governance events                    │   real judgement
├── health / connector state             ├── Daily Sync orchestration
├── locking                              └── richer context compilation
├── safe note writes
├── connector contract
└── OpenLore publishing contract (a file/frontmatter format, not code)
```

The deterministic core (`second_brain/`) has zero dependency on Claude Code
or any particular model provider - it's plain Python, and you can inspect,
test, and run the entire governance loop (`second-brain init --with-sample`
through `second-brain compile`) without it, as the flagship demo shows.

The Claude Code-native layer (`claude/`) is what turns this from "a Claim
Store you feed by hand" into an automated Second Brain that reads your
Gmail, meetings, and bookmarks and decides what matters. **v1 requires
Claude Code for that layer.** It is not agent-agnostic today - see
docs/roadmap.md for the planned adapter that would let another tool-calling
agent implement the same contract.

## Entity model

People, Companies, Meetings, Hypotheses, Insights, Decisions, and Sources
are markdown notes with YAML frontmatter, cross-linked as a hub-and-spoke
graph (a Person note accumulates links to every Meeting, Decision, and
Insight that references them). See docs/knowledge-schema.md for the full
field-by-field schema.
