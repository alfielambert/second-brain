# Second Brain

An open-source second brain that turns evidence into governed knowledge for AI agents. OpenLore makes it multiplayer.

Most second brains help you save things.

This one asks a harder question:

> **What deserves to become knowledge?**

Second Brain collects evidence, turns it into structured claims, preserves where those claims came from, and governs what is allowed to become durable knowledge.

When you want more than one AI agent to use that knowledge, [OpenLore](https://github.com/alfielambert/OpenLore) makes it multiplayer.

**Second Brain governs the knowledge. OpenLore makes it multiplayer.**

---

## Why build a second brain this way?

Imagine somebody says this in a meeting:

> “We’ll probably launch in September.”

Should your AI now believe the launch date is September?

Probably not.

That statement could be:

* an intention
* a guess
* an outdated plan
* contradicted tomorrow
* superseded by a later decision

Simply putting the transcript into a vector database does not solve that problem.

Neither does giving an agent more memory.

A useful knowledge system needs to distinguish between what was **observed**, what was **claimed**, what was **inferred**, and what should actually be treated as **current knowledge**.

That is the problem Second Brain is designed around.

---

## The core idea

The architecture separates three jobs:

> **Evidence is collected.
> Knowledge is governed.
> Context is compiled.**

```text
┌──────────────────── SOURCES ─────────────────────┐
│                                                 │
│   Meetings   Email   Notes   X   Captures       │
│                                                 │
└───────────────────────┬─────────────────────────┘
                        │
                        ▼
                  ┌────────────┐
                  │ Connectors │
                  └─────┬──────┘
                        │
                        ▼
                  ┌─────────────┐
                  │ Claim Store │
                  └─────┬───────┘
                        │
                        ▼
             ┌───────────────────────┐
             │ Knowledge Evolution   │
             │ Protocol (KEP)        │
             └───────────┬───────────┘
                         │
           ┌─────────────┼─────────────┐
           │             │             │
           ▼             ▼             ▼
      Auto apply      Proposal       Signal
           │             │             │
           │             ▼             │
           │       Human judgement     │
           │             │             │
           └─────────────┼─────────────┘
                         │
                         ▼
                Governed knowledge
                         │
                ┌────────┴────────┐
                │                 │
                ▼                 ▼
         Context compiler      OpenLore
                │                 │
                ▼                 ▼
           Local AI        Multiple agents
```

---

## What makes this different?

### Evidence is not automatically knowledge

A bookmark, email, meeting transcript or note is evidence.

It does not become a fact simply because an AI has seen it.

Second Brain first turns source material into **claims**.

Those claims then pass through governance before they are allowed to change durable knowledge.

---

### Claims keep their provenance

Claims are stored in an append-only JSONL Claim Store.

A simplified claim might look like this:

```json
{
  "claim_id": "claim_123",
  "connector": "meeting",
  "claim_type": "intention",
  "content": "Atlas is likely to launch in September",
  "confidence": "medium",
  "entities": ["Project Atlas"],
  "evidence": [
    {
      "speaker": "Maya",
      "text": "We're probably aiming for September."
    }
  ]
}
```

The important part is not the JSON.

It is that the evidence stays attached.

If the knowledge changes later, you can still understand where the earlier belief came from.

---

## The Claim Store

The Claim Store uses two append-only JSONL streams:

```text
ClaimStore/
├── claims/
│   └── YYYY-MM-DD.jsonl
└── events/
    └── YYYY-MM-DD.jsonl
```

Claims are immutable.

Governance decisions are recorded as separate events.

That means a claim is never quietly rewritten to make history look cleaner than it was.

Its current state is derived from the events that happened to it.

This gives you an auditable history of:

```text
evidence
↓
claim
↓
routing decision
↓
human or automated decision
↓
knowledge change
```

---

## Knowledge Evolution Protocol

The Knowledge Evolution Protocol, or **KEP**, decides where claims go.

In v0.1 this routing is deterministic code, not another LLM judgement call.

A connector determines what kind of claim it has extracted.

KEP determines what is allowed to happen next.

```text
Claim
  │
  ├──► Auto apply
  │
  ├──► Proposal
  │
  ├──► Signal
  │
  └──► Ignore
```

The basic rule is:

> **High-confidence, low-consequence, reversible changes can happen automatically. Important changes require judgement.**

Examples of changes that should not silently rewrite your knowledge include:

* creating a new person or company
* resolving a contradiction
* promoting a hypothesis into an insight
* merging entities
* superseding important knowledge
* structural changes

Weak inferences stay weak.

They do not quietly become facts because an LLM sounded confident.

---

## Knowledge evolves instead of being overwritten

Suppose the system learns:

```text
Atlas launch target: September
```

A month later, a new source says:

```text
Atlas launch moved to October
```

The correct result is not to erase September.

Instead:

```text
September
status: superseded
        │
        ▼
October
status: current
```

The old evidence remains part of the history.

The current knowledge changes.

This lets an agent answer both:

> When is Atlas launching?

and:

> Why did the launch date change?

That is much more useful than a folder full of disconnected notes.

---

## Durable knowledge stays simple

Governed knowledge is stored as Markdown with YAML frontmatter.

For example:

```text
People/
Companies/
Projects/
Meetings/
Decisions/
Concepts/
Hypotheses/
Experiments/
Insights/
```

You can inspect it with normal filesystem tools.

You can open it in Obsidian.

You can version it.

You can grep it.

You are not required to query a proprietary database just to find out what your second brain believes.

---

## Quick start

### Requirements

* Python 3.10+
* Git

Clone the repository:

```bash
git clone https://github.com/alfielambert/second-brain.git
cd second-brain
```

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install:

```bash
pip install -e .
```

Now initialise a Second Brain using the fictional sample dataset:

```bash
second-brain init --with-sample
```

The sample data uses a fictional company, people and project so you can explore the architecture without configuring any external services.

---

## Try the governance loop

List the claims:

```bash
second-brain claims
```

Route pending claims through KEP:

```bash
second-brain route
```

Inspect them again:

```bash
second-brain claims
```

Approve a proposed claim:

```bash
second-brain approve CLAIM_ID
```

Or reject one:

```bash
second-brain reject CLAIM_ID --reason "Not enough evidence"
```

Check system state:

```bash
second-brain status
```

Compile useful context:

```bash
second-brain compile
```

This demonstrates the core loop:

```text
Evidence
↓
Claim Store
↓
KEP
↓
Governance
↓
Durable knowledge
↓
Compiled context
```

No API keys are required for the sample.

---

## The fictional demo

The included sample data uses a fictional logistics SaaS company and project.

It is designed to demonstrate things such as:

* entity creation
* safe enrichment
* signals
* hypotheses
* decisions
* approval
* rejection
* knowledge evolution
* compiled context

Nothing in the example vault comes from the author's real Second Brain.

---

## Connectors

Connectors are responsible for detecting source changes and turning new evidence into claims.

They do **not** decide what becomes durable knowledge.

That boundary is deliberate.

Conceptually, a connector does this:

```text
discover()
↓
fetch()
↓
normalise()
↓
extract claims
↓
update cursor
↓
report health
```

KEP handles governance afterwards.

This keeps source ingestion separate from knowledge policy.

---

## Simple capture

The easiest connector is local capture.

A captured thought enters the system as weak evidence rather than instantly becoming knowledge.

That means you can write something like:

```text
Security reviews might be slowing enterprise adoption.
```

without the system immediately turning:

> “might be”

into:

> “is”.

Capture first.

Govern later.

---

## X Bookmarks

Second Brain also includes an X Bookmarks connector.

It uses the official X API and OAuth 2.0 PKCE to incrementally read new bookmarks.

The connector remembers what it has already processed, so running it repeatedly does not keep ingesting the same tweets.

The flow is:

```text
X bookmark
↓
X API
↓
Incremental sync
↓
Claim Store
↓
KEP
↓
Signal / governed knowledge
```

A bookmark starts as a weak signal.

Bookmarking somebody else's opinion should not automatically make that opinion part of your own knowledge.

That distinction is intentional.

To use the connector you will need your own X developer credentials.

Never commit access tokens or refresh tokens to the repository.

---

## Why not just use RAG?

RAG is useful.

It solves a different problem.

Retrieval typically asks:

> Which stored chunks are relevant to this query?

Second Brain asks questions before retrieval:

> Where did this information come from?

> Is it observation or inference?

> How confident are we?

> Does it contradict existing knowledge?

> Is it still current?

> Does this change require human judgement?

> What did this knowledge supersede?

You can still use retrieval over the resulting knowledge.

The difference is that the material being retrieved has already passed through a governance process.

---

## Why not just give the AI memory?

Because remembering something does not make it true.

```text
Memory
↓
Evidence
↓
Claim
↓
Governance
↓
Knowledge
```

Memory is useful input.

It should not automatically be the final knowledge layer.

---

## Why Markdown and JSONL?

Because boring infrastructure is often good infrastructure.

The core formats are intentionally simple.

### Markdown

Useful because it is:

* human-readable
* agent-readable
* portable
* versionable
* inspectable
* easy to back up

### JSONL

Useful because it is:

* append-friendly
* easy to stream
* easy to audit
* easy to process from Python
* capable of representing structured evidence
* simple enough to inspect with normal tools

The goal is not to build a database platform.

The goal is to maintain trustworthy knowledge.

---

## Local mode

You do not need OpenLore to use Second Brain.

For one local AI workflow, the architecture can stop here:

```text
Sources
↓
Claims
↓
KEP
↓
Governed knowledge
↓
Context
↓
Local AI
```

That is a complete and useful system on its own.

---

# Making it multiplayer

Things become harder when several agents need the same knowledge.

You might have:

```text
Claude Code
ChatGPT
Research agent
Coding agent
Telegram agent
```

One solution is to give every agent its own copy of your knowledge.

That eventually creates a new problem.

The copies diverge.

```text
Agent A → yesterday's knowledge
Agent B → last week's knowledge
Agent C → a completely different copy
```

You have recreated the memory problem one agent at a time.

This is where [OpenLore](https://github.com/alfielambert/OpenLore) comes in.

---

## OpenLore

OpenLore is an open-source knowledge server for AI agents.

Second Brain and OpenLore solve different parts of the problem.

### Second Brain answers:

> **What should we know?**

It handles:

* evidence
* claims
* provenance
* governance
* knowledge evolution
* human judgement
* context compilation

### OpenLore answers:

> **How do multiple agents access what we know?**

The integration is deliberately thin.

Second Brain produces governed Markdown and frontmatter.

OpenLore distributes that knowledge to agent consumers.

```text
                         ┌──► Claude
                         │
Governed knowledge ─► OpenLore ──► ChatGPT
                         │
                         ├──► research agent
                         │
                         └──► coding agent
```

You do not need OpenLore to run Second Brain locally.

Once several agents need access to the same evolving knowledge, OpenLore becomes the multiplayer layer.

**Second Brain governs the knowledge. OpenLore makes it multiplayer.**

[Explore OpenLore →](https://github.com/alfielambert/OpenLore)

---

## Claude Code and the reasoning layer

The deterministic core of Second Brain is normal Python.

That includes things such as:

* Claim Store
* KEP routing
* governance events
* state and health tracking
* locking
* vault handling
* connector contracts

Some workflows require semantic interpretation that deterministic code cannot provide.

The original system uses Claude Code for those reasoning and orchestration tasks.

The intended boundary is:

```text
Portable deterministic core
├── Claim Store
├── KEP
├── governance
├── state
├── connectors
└── knowledge files

Reasoning runtime
├── source interpretation
├── claim extraction
├── orchestration
└── context synthesis
```

v1 is being built around Claude Code because that is the runtime the original system has been proven against.

The underlying knowledge architecture is deliberately kept separate so other agent runtimes can implement the same contracts later.

---

## Safety model

There are a few rules behind the architecture.

### Weak inference does not become fact

Low-confidence inference stays a signal until stronger evidence exists.

### Connectors cannot bypass governance

A connector may create claims.

It should not directly decide what your knowledge base believes.

### Claims are immutable

History is preserved through events rather than quietly rewriting earlier claims.

### Important changes require judgement

Automation handles routine maintenance.

Humans handle consequential decisions.

### Knowledge has provenance

You should be able to answer:

> Why does the system believe this?

---

## Project structure

```text
second-brain/
├── second_brain/
│   ├── claimstore.py
│   ├── kep.py
│   ├── health.py
│   ├── lock.py
│   ├── vault.py
│   ├── notes.py
│   ├── cli.py
│   ├── schema/
│   ├── connectors/
│   │   ├── capture.py
│   │   └── x_bookmarks.py
│   └── examples/
│
├── docs/
│   ├── architecture.md
│   ├── claim-store-and-kep.md
│   ├── knowledge-schema.md
│   └── ...
│
├── tests/
├── launchd/
├── README.md
├── CONTRIBUTING.md
├── pyproject.toml
└── LICENSE
```

---

## Philosophy

### Your second brain should do work

A second brain should not become another inbox you have to remember to maintain.

### AI should earn the right to remember things

Seeing information is not the same as knowing it.

### Knowledge should evolve

The world changes.

Your knowledge system should be able to change without destroying the history of how it got there.

### Humans should maintain exceptions, not databases

Routine maintenance should happen automatically.

Human attention should be reserved for things that require judgement.

### Agents should share knowledge, not stale copies

Once several agents are working with you, they need a shared understanding of the world.

That is the multiplayer problem OpenLore is designed to solve.

---

## Status

Second Brain is an open-source extraction of a system originally built for real day-to-day use.

The public repository intentionally contains:

* portable core code
* fictional sample data
* documented schemas
* reproducible examples
* no private vault content
* no real meeting transcripts
* no customer data
* no credentials

The project is early.

Expect the architecture and developer experience to keep improving.

---

## Roadmap

Near-term areas include:

* richer context compilation
* Claude Code-native Daily Sync
* additional connector examples
* approval workflows
* automated scheduling
* health monitoring
* OpenLore publishing
* multi-agent demonstrations
* runtime adapters beyond Claude Code

Features should only be marked complete when they are actually shipped and tested.

---

## Contributing

Contributions are welcome.

Good areas to help with include:

* connectors
* tests
* sample workflows
* documentation
* knowledge schemas
* runtime adapters

If you are adding a connector, keep the central architectural rule in mind:

> **Connectors produce evidence and claims. They do not decide what becomes knowledge.**

See `CONTRIBUTING.md` and `docs/connector-contract.md` for more.

---

## OpenLore

Building one local brain for one agent?

Start here.

Building one governed brain for several agents?

Take a look at [OpenLore](https://github.com/alfielambert/OpenLore).

**Second Brain governs the knowledge. OpenLore makes it multiplayer.**

---

## License

MIT
