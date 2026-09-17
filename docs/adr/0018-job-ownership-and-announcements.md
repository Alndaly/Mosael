# ADR 0018: Work spawned by a job belongs to that job, and only the task center announces

## Status

Accepted — 2026-09-18.

## Context

The owner reported that a single task produces "a pile of notifications". The local job table for
the previous seven days showed where they came from:

| kind | top-level | under a parent |
| --- | --- | --- |
| proxy | 45 | 0 |
| tts | 35 | 0 |
| workflow | 22 | — |
| subtitle_dub | 1 | 4 |

One translated-dubbing run had three children (transcribe, subtitle dub, export) and, in the same
time window, thirteen top-level `tts` jobs and one top-level `proxy` job. The task center toasts
every top-level job that finishes, and mirrors the toast as a desktop notification — so one run
announced itself fifteen times.

Three causes, each structural:

1. **Ownership stops one level down.** `create_job` takes its parent from a context variable that
   the workflow engine sets around each node. `dispatch_job` runs the job body on a new
   `threading.Thread`, and threads do not inherit context variables. So a job created *inside a
   job* — each line of a subtitle dub, the proxy queued when a render registers its output — was
   created with no parent.
2. **Completion was announced twice.** A few components watched their own job and toasted on
   completion, and the task center toasted the same transition.
3. **Job kinds were described by hand-written frontend tables.** The task center had three
   (labels and icons, what to refresh, where to navigate) and the child list had a fourth, already
   disagreeing with the first (proxy and tts rendered as "Task"). One entry (`scheduled`) named a kind
   the backend never creates. There was nowhere to say "this kind is not worth announcing".

## Decision

1. **A job's body runs as that job.** `dispatch_job` sets the parent context inside the thread it
   starts, so anything the body creates is its child. Two strengths:
   - *strict* — the workflow engine and scheduler: once the parent has ended, creating a child is
     refused (a cancelled workflow must not start new work);
   - *derived* — a job's own body: the child is attached even if the parent has just finished
     (a render registers its output, and the proxy for it, as its last step).
   Cancellation already cascades down `parent_job_id`, so cancelling a subtitle dub now also stops
   its per-line syntheses.
2. **Job kinds are declared once, in the backend** (`app/domain/job_catalog.py`), and served by
   `GET /api/jobs/kinds`: label, announcement policy (`always` / `failures` / `never`), the
   resources a finished job may have changed, and the page (plus payload field) that shows its
   record. The job bus stays domain-agnostic; the catalog is a separate table, like `NODE_TYPES`.
   A ratchet requires every kind passed to `create_job` to be in the catalog. Icons stay in the
   frontend (as node icons do), checked by a ratchet that every catalog kind has one.
3. **The task center is the only announcer.** It toasts, and notifies the desktop, for top-level
   jobs whose policy allows it. Components that start a job say "queued", refresh the task list,
   and never announce completion themselves. Proxy generation is maintenance nobody asked for:
   `failures` only.
4. **Resources, not query keys.** The catalog says a render affects `assets` and `sequences`; the
   frontend maps each resource to its cache keys once. The backend does not learn React Query.

## Consequences

- A translated-dubbing run announces once (the workflow), plus the summary its notify node writes
  to the bell. The per-line syntheses are visible under the dub in the job detail.
- Adding a job kind means one catalog entry and one icon; forgetting either fails a test instead of
  rendering "Task".
- Persistent notifications (the bell) are unchanged: failures of workflows and publishing, notify
  nodes, team events.
