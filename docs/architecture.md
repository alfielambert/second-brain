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
of markdown+frontmatter over SSH/MCP/HTTP to authenticated identities. See
docs/openlore-integration.md for exactly how the two connect.

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
