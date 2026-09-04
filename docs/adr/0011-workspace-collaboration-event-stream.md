# ADR 0011: Workspace collaboration uses one audit projection

## Status

Accepted — 2026-09-04

## Context

Mosael already records actors on workflow revisions, sequence operations and jobs, but those facts
are presented in separate surfaces. Infinite-canvas writes also lacked a concurrency token, so a
stale full-canvas autosave could overwrite another actor's edit or an asynchronous result. Comments,
mentions and reviews need a common identity and permission boundary rather than three isolated UI
features.

## Decision

1. A Board has a monotonic `revision`. Interactive writes may carry `base_revision`; current clients
   always do so. A conditional update accepts exactly one matching projection and returns HTTP 409 on
   conflict. Identical content is a no-op and does not advance the revision.
2. `ActivityEvent` is an immutable, workspace-scoped audit projection with actor, action and generic
   subject identity. Domain histories remain authoritative for replay/undo. Their actor-bearing rows
   are projected into Activity with stable source identities, and new operations publish through one
   collaboration Interface in the same transaction as the business write.
3. Comments and Reviews use the same `(workspace, subject type, subject id)` identity. Mentions are
   persisted relations derived from explicit recipients or `@username`; notifications deliver them
   but do not own their state. Review decisions are authorized in the backend and have an explicit
   state machine.

## Consequences

- The Team surface can show one actor-resolved activity feed across products.
- Board clients detect contention instead of relying on last-write-wins.
- Collaboration can expand to new subject types without adding product-specific comment tables.
- Activity is intentionally a projection: deleting a subject does not delete its audit trail, while
  deleting a domain revision or operation remains governed by that domain's own retention rules.
