---
description: Compile durable knowledge into a task-scoped Context Pack
argument-hint: [target]
---

# Compile

Build a Context Pack for the target named in `$ARGUMENTS` (e.g. `founder`,
`sales`, `meeting-prep`).

1. Gather durable knowledge: notes under `People/`, `Companies/`,
   `Meetings/`, `Decisions/`, `Insights/` whose `status` is not `archived`,
   plus any claim currently `auto_applied` or `approved`
   (`second-brain claims`). Exclude anything still `pending`/`propose` and,
   by default, exclude `Hypotheses/` entirely - a pack should represent
   what's actually known, not what's being tested.

2. Resolve conflicts by authority: a `Decision` note beats a `Hypothesis`
   or raw `Observation` on the same topic; a high-confidence `Insight`
   beats a low-confidence one; the most recent non-superseded claim on a
   `target_note` beats an earlier one. Never average conflicting claims
   into a single vague statement - pick the higher-authority one and note
   the disagreement existed.

3. Write real prose (not just a bulleted claim dump) to `Packs/<target>.md`,
   organized by what the target actually needs - a `founder` pack cares
   about company/people/decisions context; a `meeting` pack cares about the
   specific people and prior decisions relevant to the next meeting.

4. Always end with two sections, non-negotiable:
   - **Known Unknowns** - open questions, low-confidence hypotheses
     excluded above, anything explicitly not yet resolved.
   - **Compile Report** - what was included, what was excluded and why,
     and any contradiction you had to resolve. This is what makes a
     compiled pack trustworthy instead of just a plausible-sounding
     summary - never omit it, even if it makes the pack longer.

This produces a richer pack than `second-brain compile` (the deterministic
core's list-based version) while keeping the same underlying discipline:
only durable knowledge goes in, and every exclusion is stated, not hidden.
