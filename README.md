# Second Brain

Most second brains store information.

This one decides what deserves to become knowledge.

It turns evidence from the tools you already use into **claims**, routes
every claim through a **deterministic governance protocol** instead of
vibes, and only then lets something become durable knowledge an AI agent
can actually trust. Then it compiles the right slice of that knowledge into
task-scoped context - always showing you what it left out and why.

```
Evidence -> Claims -> Governance (KEP) -> Durable Knowledge -> Compiled Context
```

This is not a RAG pipeline, a vector database, an Obsidian template, or a
prompt collection. There's no embedding search here at all - retrieval is
"which durable, approved notes match this task," not "which chunks are
semantically similar." The interesting part isn't storage; it's the
governance step in the middle that decides what's allowed to become
knowledge in the first place.

## Try it in about two minutes

```bash
git clone https://github.com/alfielambert/second-brain.git
cd second-brain
pip install -e .

second-brain init ~/my-vault --with-sample
cd ~/my-vault

second-brain claims                    # 9 claims from a fictional company (Acme)
second-brain route                     # KEP decides: auto-apply, propose, or signal
second-brain claims                    # 1 auto-applied, 7 need approval, 1 weak signal
second-brain approve --all-pending     # approve everything (real usage: review each one)
second-brain compile --target founder
cat Packs/founder.md                   # a compiled context pack, with a Compile Report
```

No API keys required for this loop - it's the deterministic core end to
end, using a fictional dataset (a company called Acme, evaluating a
product called Atlas) that deliberately includes a contradiction: an
early "launch in September" decision gets **superseded** by a later one
once you approve it, and you can watch `Decisions/Atlas Launch Date.md`
record exactly why.

## Why governance, not just storage

Any tool can save a note. The hard part is deciding what should become
knowledge an agent is allowed to act on. This project's answer is **KEP**
(Knowledge Evolution Protocol) - a deterministic lookup table, not a model
call, that decides whether a new claim gets written automatically, held for
your approval, or logged as a weak signal that doesn't yet earn a place in
the vault:

| the claim is... | KEP does... |
|---|---|
| a high-confidence update to something that already exists | auto-applies it |
| a new entity, a contradiction, a decision change, anything structural | always asks you first |
| weak or low-confidence | logs it as a signal, never proposes it |

Nothing is ever silently overwritten. Claims are append-only; a claim's
current status is derived by replaying its governance events, not by
mutating the record - so you can always answer "why does the vault say
this" by walking the chain back to the original evidence. See
[`docs/claim-store-and-kep.md`](docs/claim-store-and-kep.md).

## Architecture

**Local mode** - everything on your machine, nothing required beyond this repo:

```
Sources -> Connectors -> Claim Store -> KEP -> Governed Knowledge -> Local AI
```

**Multiplayer mode** - once more than one agent needs the same knowledge:

```
Sources -> Connectors -> Claim Store -> KEP -> Governed Knowledge -> OpenLore -> Multiple AI agents
```

[OpenLore](https://github.com/aakarim/go-openlore) is a separate,
already open-source knowledge server - not a proprietary add-on bolted on
here. Running one agent locally? You don't need it. Once Claude Code,
ChatGPT, and whatever else you use all need the *same current* knowledge,
copying your vault into each one creates a new problem: stale, divergent
copies. OpenLore is the layer that solves that - see
[`docs/openlore-integration.md`](docs/openlore-integration.md).

Full diagram and the local-core/Claude-Code-runtime split:
[`docs/architecture.md`](docs/architecture.md).

## Two runtimes, one honest boundary

The deterministic core (`second_brain/` - Claim Store, KEP, connector
state, locking, safe writes) is plain Python with no model dependency at
all. **The automated reasoning layer - deciding what a bookmark or email
actually means, orchestrating a daily sync, writing real prose into a
compiled pack - is Claude Code-native in v1.** That's a stated design
choice, not a hidden limitation: see
[`claude/README.md`](claude/README.md) for exactly where that line is and
what a future non-Claude runtime would need to implement.

## Connectors

- **`x_bookmarks`** (flagship) - real OAuth 2.0 PKCE against the live X
  API, incremental sync, no MCP dependency. Works with your own X developer
  app.
- **`capture`** - the simplest connector: drop a `.md`/`.txt` file in
  `ClaimStore/captures/inbox/`, get a claim.
- Gmail, Calendar, Notion patterns are documented (not shipped as code)
  in [`docs/connector-contract.md`](docs/connector-contract.md) - they
  depend on your own MCP account grants, so shipping "working" code for
  them would only really work for one person.

Writing your own: [`docs/connector-contract.md`](docs/connector-contract.md).

## Getting started for real

1. `second-brain init ~/my-vault` (no `--with-sample` this time)
2. Enable `capture` (already on by default) and drop a real note in
   `ClaimStore/captures/inbox/`
3. `second-brain sync --connector capture && second-brain route`
4. When you're ready for something automated: set up `x_bookmarks`
   ([`docs/connector-contract.md`](docs/connector-contract.md)), then the
   Claude Code layer for real judgement-based extraction
   ([`claude/README.md`](claude/README.md)), then scheduling
   ([`launchd/README.md`](launchd/README.md))
5. Multiple agents that need the same current knowledge? See
   [`docs/openlore-integration.md`](docs/openlore-integration.md)

## License

MIT. See [`LICENSE`](LICENSE).
