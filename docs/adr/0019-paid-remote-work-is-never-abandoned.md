# ADR 0019: Paid remote work ends only when the provider finishes it or the user cancels it

## Status

Accepted — 2026-09-19.

## Context

The owner ran the *topic → full video* template: six shots, the per-shot loop set to run three at a
time, each shot a Seedance 2.0 video. The workflow failed with "iteration 1/6 failed: Generation
timed out". The provider's bill showed the videos had been generated and charged — about ¥20.

The job table and the provider's task list gave the exact sequence (local time):

| time | what happened |
| --- | --- |
| 20:34:35 | three video tasks submitted (iterations 1–3) |
| 20:39:36–38 | all three marked `Generation timed out` on our side, at exactly 300 s |
| 20:39:38 | a **fourth** task submitted (iteration 4) — after the loop had already failed |
| 20:40–20:45 | the provider finished all four (5 min 40 s to 7 min each) and charged for them |
| 20:44:39 | the fourth marked timed out as well |

Nothing was wrong with the provider. Four structural causes, each of which alone loses money:

1. **"Timed out" was our impatience, not the provider's state.** `poll_until_ready` gave up after
   300 s (Evolink had its own 600 s). Giving up does not stop a remote task; it keeps generating and
   the provider still charges.
2. **The receipt lived in a local variable.** Every adapter held the provider's task id in a local
   variable between submit and poll. Once polling was abandoned the id was gone, and nothing in the
   app could ever collect the finished video. (The four videos were recovered by hand from the
   provider's task list before their download links expired.)
3. **A restart failed paid work.** `reconcile_orphaned_jobs` marked every job left running by a
   restart as "interrupted, please start again". Doing what it says pays twice. The development
   backend runs with `--reload`, so every code edit is a restart.
4. **The loop kept starting paid iterations after it had failed.** Fail-fast cancelled queued
   iterations *after* `wait(FIRST_EXCEPTION)` returned — but the moment a failing iteration's thread
   became free, the pool had already picked up the next queued iteration. The error then reported
   only the lowest-numbered failure, so the other two failed shots looked fine.

The workflow layer repeated cause 1 one level up: `wait_for_job` abandoned a child job after
15 minutes while the child kept running.

## Decision

Once paid remote work is submitted, it ends in exactly two ways: **the provider reports a terminal
state, or the user cancels**. "We waited long enough" is not one of them.

1. **The receipt is persisted the moment waiting starts.** `poll_until_ready` is the one loop every
   asynchronous adapter passes through, so it reports the poll path to a `RemoteTaskWatch` that the
   generation runner installs (a context variable, not a parameter — seven adapters each remembering
   to report is seven chances to forget). The runner writes it to `Job.payload.remote_task`
   immediately.
2. **Submit and collect are separate steps.** Each asynchronous adapter implements
   `resume(poll_path, …)` — the half of `generate` after submission — and declares
   `supports_resume = True`. `generate` is *submit + resume*. A ratchet fails if an adapter calls
   `poll_until_ready` without being resumable.
3. **A restart resumes instead of failing.** The job bus gains `register_resumer(kind, can_resume,
   resume)`. On startup, a running `ai_generation` job that has a receipt and a resumable adapter is
   picked up again — polling continues, nothing is resubmitted — instead of being failed.
4. **The poll ceiling guards against a provider that never answers, not against our patience.**
   It is six hours (the provider's own expiry is 48 h). If it is ever reached, the error names the
   remote task so it can be found in the provider console. Cancellation is checked between polls.
5. **Waiting on a child job has no deadline of its own.** Cancelling a workflow cascades to its
   descendants, which then reach a terminal state, so the wait still ends.
6. **A failed loop starts nothing new, and reports every failure.** The stop signal is raised in
   the failing iteration's own thread before it returns, and every iteration checks it before it
   starts. The error lists all failed iterations and how many were not started.

## Consequences

- A workflow node can now wait as long as the provider takes. That is the honest duration of the
  work; the task center shows it running, and the user can cancel it.
- If the backend restarts mid-workflow, the workflow run itself is still interrupted (resuming a
  graph mid-execution is out of scope), but the paid generation it started is collected and lands in
  the asset library.
- Local engines (ComfyUI) keep their own deadline: they are not billed, and a stuck local queue is
  better surfaced than waited on.
- Cancelling a job stops *our* waiting. Most providers cannot stop a task that is already
  generating; the user is choosing to give up that result.
