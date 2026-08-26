# OpenLore Integration

## Running one agent locally?

You don't need OpenLore. Everything above - Claim Store, KEP, durable
notes, compiled Context Packs - is just files on your disk, and any local
agent (Claude Code, a script, an editor plugin) can read them directly.

## Once several agents need the same knowledge

Point Claude Code at your vault, and separately give ChatGPT or another
agent a copy so it can use the same context, and you now have two copies of
your knowledge. Update one and the other goes stale silently. That's not
hypothetical - it's the exact problem that motivated this project: without
a shared distribution layer, the only working option was periodically
re-copying the vault into a second agent's storage, which is a
synchronization problem wearing a knowledge-management costume.

## What OpenLore is

[OpenLore](https://github.com/aakarim/go-openlore) is a separate,
already-open-source (MIT), agent-native knowledge server. It serves a
directory of markdown+frontmatter to authenticated agent identities over
SSH, MCP (HTTP or stdio), and a JSON REST API - with per-identity scoped
access (`ro` / `publish` / `rw`), path aliases, and CAS-protected writes.
It has no concept of claims, KEP, or this project's schema; it only
understands "here's a directory, here's who's allowed to read or write
which parts of it." Critically, **there is no ingestion pipeline** - it
serves the directory it's pointed at directly, live, on every request. That
one fact is what makes the walkthrough below work without any sync step.

## Walkthrough: from local to multiplayer

This takes a vault that already works locally (`second-brain init
--with-sample` and the rest of the README's quick start) and makes it
available to a second agent, then proves that agent sees a knowledge update
with no manual copying.

### 1. Install OpenLore

```bash
go install github.com/aakarim/go-openlore/cmd/openlore@latest
```

(Requires Go 1.26+. See the [OpenLore README](https://github.com/aakarim/go-openlore#installation) for other install methods.)

### 2. Point it at governed knowledge

Serve your vault, but exclude the ungoverned parts - `ClaimStore/` holds
raw claims and `Proposals/` holds things still awaiting your approval;
neither is durable knowledge yet, so neither should be exposed to other
agents:

```bash
cd ~/my-vault
openlore . --ignore 'ClaimStore,Proposals,.git'
```

This starts three things at once:

```
SSH:  ssh -p 2222 localhost
Web:  http://localhost:8080
MCP:  http://localhost:8080/mcp
```

### 3. Expose it via MCP to a second agent

For a client that launches a local process (e.g. Claude Desktop), use MCP
over stdio instead and add it to that agent's MCP config:

```json
{
  "mcpServers": {
    "openlore-second-brain": {
      "command": "openlore",
      "args": ["mcp", "--ignore", "ClaimStore,Proposals,.git", "/absolute/path/to/my-vault"]
    }
  }
}
```

### 4. Connect a second agent and ask a question

Restart the second agent so it picks up the new MCP server, then ask it
something the vault actually knows, e.g. with the fictional Acme dataset:

> "Using the openlore-second-brain tool, what's the current Atlas launch
> date, and who's driving the deal at Acme?"

It should `grep`/`cat` its way to `Decisions/Atlas Launch Date.md` and
`People/Daniel Osei.md` and answer from the current, governed content -
not a stale copy, because there isn't one.

### 5. Change the knowledge

Back in your Second Brain (the first agent, or the CLI directly), approve
a new claim that further updates that same decision - e.g. add a claim via
`second-brain claims`/`route`, or use the Claude Code `/daily-sync` layer,
then:

```bash
second-brain approve <new_claim_id>
```

This writes directly to `Decisions/Atlas Launch Date.md` in the vault
OpenLore is already serving.

### 6. Prove the second agent sees the update

Ask the second agent the same question again, in a new turn:

> "Check the Atlas launch date again - has anything changed?"

Because OpenLore has no cache or ingestion step, it re-reads the file from
disk on this request. The second agent sees the new decision immediately -
no re-publish, no re-sync, no second copy to keep consistent.

## Adopting OpenLore is not a paywall

Second Brain governs knowledge. OpenLore distributes it. Both are open
source, and adopting OpenLore is an infrastructure decision (do I need
multiple agents to see the same current knowledge, without maintaining
copies?), not a feature unlock. If your Second Brain only ever talks to one
agent on one machine, there's nothing above to add.
