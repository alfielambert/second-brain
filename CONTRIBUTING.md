# Contributing

## Setup

```
git clone https://github.com/alfielambert/second-brain.git
cd second-brain
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Adding a connector

Read `docs/connector-contract.md` first. Implement the six functions
(`discover`, `fetch`, `normalise`, `extract_claims`, `update_cursor`,
`health`) in a new module under `second_brain/connectors/`, following
`x_bookmarks.py` as the reference. Default to `claim_type=signal,
operation=weak_inference, confidence=low` unless your connector has a
genuine, deterministic reason to claim higher confidence - KEP is what
keeps that safe, but only if connectors are honest about uncertainty.

## Scope

This repo is the deterministic governance core plus the Claude Code-native
runtime layer that ships with it - not a general agent framework. Changes
to `second_brain/claimstore.py` or `second_brain/kep.py` (the two files
everything else depends on for correctness) should come with a test in
`tests/` and a clear explanation of why the existing behavior was wrong,
not just different.

## Pull requests

Keep them scoped to one connector, one doc, or one bug fix. Run `pytest`
before opening.
