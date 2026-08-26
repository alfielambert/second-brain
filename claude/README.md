# The Claude Code runtime layer

The deterministic core (`second_brain/`) can store, route, and compile
knowledge, but it can't read your inbox and decide what matters - that's a
judgement call, not a lookup table. In v1, that judgement is done by a
headless Claude Code session following the specs in this folder.

**This is a v1 runtime choice, not an architectural dependency.** Nothing
in `second_brain/` imports or assumes Claude Code. The boundary is:

```
second_brain/            <- portable, no model dependency
  claimstore.py, kep.py, health.py, lock.py, notes.py, connectors/

claude/                  <- Claude Code-native, v1 only
  commands/daily-sync.md, commands/compile.md
```

## The contract a future runtime would need to implement

Anything that wants to replace this layer (a Codex-based runner, a custom
agent loop, whatever) needs to do exactly two things, both already fully
specified by the deterministic core:

1. **Produce claims.** Call `second_brain.claimstore.append_claim(...)`
   (or shell out to a connector following docs/connector-contract.md) with
   real judgement about `claim_type`, `operation`, `confidence`, and
   `entities` - not just the `weak_inference`/`signal` default the shipped
   connectors use.
2. **Synthesize a Context Pack.** `second-brain compile` already assembles
   durable claims into sections with a Known Unknowns list and a Compile
   Report; a richer runtime can instead read the same durable claims/notes
   and write actual prose to `Packs/<target>.md`, as long as it keeps the
   Compile Report's honesty (what was included, what was excluded, and why)
   - that transparency is the whole point, not an implementation detail.

Nothing about KEP, the Claim Store, or the schema needs to change for a
different runtime to implement these two things. See docs/roadmap.md.

## What's here today

- `commands/daily-sync.md` - a Claude Code slash command (`/daily-sync`)
  that walks through each enabled connector, decides claims with real
  judgement (not just the weak-signal default), and runs
  `second-brain route` to let KEP take over.
- `commands/compile.md` - the `/compile` command: gathers durable
  knowledge, resolves conflicts by an explicit authority ranking (a
  Decision beats a Hypothesis; a high-confidence Insight beats a raw
  Observation), and writes real synthesized prose to a Context Pack -
  richer than the deterministic core's list-based compiler, but following
  the same Known-Unknowns-and-Compile-Report discipline.

Install these as Claude Code project commands (copy `claude/commands/` into
your vault's `.claude/commands/`), or invoke them as one-off prompts.
