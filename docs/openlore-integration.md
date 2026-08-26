# OpenLore Integration

## Running one agent locally?

You don't need OpenLore. Everything above - Claim Store, KEP, durable
notes, compiled Context Packs - is just files on your disk, and any local
agent (Claude Code, a script, an editor plugin) can read them directly.

## Once several agents need the same knowledge

Point Claude Code at your vault, and separately give ChatGPT or another
agent a copy so it can use the same context, and you now have two copies of
your knowledge. Update one and the other goes stale silently. That's not a
hypothetical - it's the exact problem this project's own author hit running
a personal Second Brain: without a shared distribution layer, the only
working option was periodically re-copying the vault into a second agent's
storage, which is a synchronization problem wearing a knowledge-management
costume.

## What OpenLore is

[OpenLore](https://github.com/aakarim/go-openlore) is a separate,
already-open-source (MIT), agent-native knowledge server. It serves a
directory of markdown+frontmatter to authenticated agent identities over
SSH, MCP-over-HTTP, and a JSON REST API - with per-identity scoped access
(`ro` / `publish` / `rw`), path aliases, and CAS-protected writes. It has no
concept of claims, KEP, or this project's schema; it only understands
"here's a directory, here's who's allowed to read or write which parts of
it."

## The integration point is a file format, not a library

Second Brain writes governed markdown+frontmatter into a directory.
OpenLore serves that directory to whichever agents you've granted access
to. There is no shared Go/Python library, no tight coupling, and no
OpenLore-specific code inside `second_brain/` - just a `distribution.openlore`
block in `second-brain.yml` naming a publish path:

```yaml
distribution:
  openlore:
    enabled: true
    publish_path: ~/openlore-served/second-brain
```

This is deliberate: it keeps the deterministic core honestly independent of
OpenLore (or any other distribution layer someone might build), and it
keeps OpenLore itself a generic server that doesn't need to know anything
about this project to be useful.

## Adopting OpenLore is not a paywall

Second Brain governs knowledge. OpenLore distributes it. Both are open
source, and adopting OpenLore is an infrastructure decision (do I need
multiple agents to see the same current knowledge, without maintaining
copies?) - not a feature unlock. If your Second Brain only ever talks to
one agent on one machine, there's nothing to add.
