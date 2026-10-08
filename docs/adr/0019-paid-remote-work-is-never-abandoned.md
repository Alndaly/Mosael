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

## Revision (2026-10-08): a glitch is not an ending, and a result that was paid for can always be collected

An analysis pass (with mock providers, never a real paid call) found that the decision above still lost paid
work in five ordinary situations. Each is now pinned by a regression test whose name says what it prevents.

1. **A network blip while waiting ended the wait.** Any exception inside `poll_until_ready` broke out of the
   loop: one lid-close or Wi-Fi switch longer than the GET's own retries, one 502 from the query endpoint, or a
   proxy answering 200 with an HTML page failed the job, booked it as *not billed*, and was never resumed — while
   the provider finished and charged. Now a **transient** failure (a transport error, 429 / 5xx, a body that is not
   a JSON object) is retried with backoff (doubling from the poll interval, capped at 60 s, checked for
   cancellation every second), and the job shows *"reconnecting (attempt n) — the remote task is still there"*.
   Only a **deterministic** failure (401 / 403 / 404, or the provider's own failed state) or the six-hour ceiling
   ends the wait. (`tests/test_remote_waits_survive_network_blips.py`)
2. **A paid POST was resent on gateway errors.** `RetryingClient` retried every 5xx regardless of method. A relay
   behind Cloudflare answers 524 after 100 s while the origin keeps generating and charging; a gateway 502 on an
   asynchronous submit created a second remote task that nobody tracked. A non-idempotent request is now resent
   only on the statuses that say *the request was not processed* — 429, 503, 529; 500 / 502 / 504 / 52x are
   treated like a read timeout (`http_retry.status_resend_is_safe`). Idempotent requests (polling) still retry
   on any 5xx. (`tests/test_paid_posts_are_not_resent_on_gateway_errors.py`)
3. **Waiting held a database connection.** Every poll asked "was I cancelled?" with `db.refresh(job)` on the
   runner's long session and never committed, so each waiting generation pinned one of the pool's 15
   connections for minutes to hours; fifteen concurrent videos starved every request. A synchronous paid call
   held one too (the read transaction opened before the adapter call). The runner now ends its read transaction
   before calling the adapter, and everything it does while waiting — cancellation checks, the reconnecting
   notice, a side-call booking — uses a short session or commits at once.
   (`tests/test_waiting_generations_hold_no_connection.py`) *Not changed:* a waiting generation still occupies
   one of the 16 job slots; parking it while it waits changes dispatch semantics and needs its own decision.
4. **A restart's resume re-resolved the inputs.** Resuming went through the same path as submitting, so a first
   frame deleted after submission (or a validator made stricter by an upgrade) failed the resume before the
   provider was ever asked — nothing collected, nothing booked. Resuming now builds the request without
   sources and without re-validation (the inputs were handed over at submission), and meters the submitted image
   count from the stored request. (`tests/test_resume_after_restart_ignores_deleted_inputs.py`)
5. **A dropped download lost the result for good.** The provider had finished and charged; the download of the
   finished file broke once; the job failed as *"ARK request failed: peer closed connection"* (blaming the
   provider) and nothing could collect it again. Now:
   - `media_transfer.download_to_path` resumes from where it broke (`Range`, up to five times), starts over when
     the server ignores `Range`, checks the length it was promised, and raises `MediaDownloadError` — not an
     httpx error, so adapters no longer relabel it as a provider failure. The OpenAI image adapter's result URLs
     go through it too.
   - The job says what happened: *"the provider finished (most likely charged), the download broke off — use
     Retrieve again"*; for synchronous providers, which keep no receipt, it says only a new generation can help.
   - **Retrieve again** (`POST /api/generation/jobs/{id}/retrieve`, the button on AI Studio's failure card)
     creates a **new job** on the same generation record and runs the resume path: nothing is resubmitted. The
     failed job stays failed (terminal stays terminal). It is offered only for a failed generation with a
     receipt, a resumable adapter and no output — **not** for a stopped one: stopping still means giving up that
     result (Consequences above). Who may click it is who may stop it (the session owner).
   (`tests/test_interrupted_downloads_can_be_retrieved.py`)

**Booking.** A failure *after* the receipt is no longer booked as *not billed*: with the provider's terminal
payload it is booked as the provider reported; without one (or when the payload reports nothing), it is
estimated from the request and annotated `unsettled_remote_task` (or `result_not_collected` when the provider
finished but the file was not downloaded). When Retrieve again later succeeds, the success entry **replaces**
the failed one (`billing.usage.retire_usage`; the old entry is kept verbatim in the new one's
`replaces_failed_attempt`) — it is the same provider call, and summing both would count it twice. A generation
cancelled while its outputs were being registered (the files are in the library, the provider charged) is now
booked as succeeded with `cancelled_locally`, not dropped. (`tests/test_cancelled_while_registering_is_still_billed.py`)

**Known limits.** The receipt lives on the job; clearing finished jobs from the task center also clears what
Retrieve again needs. A synchronous paid call whose response never arrives (read timeout, restart mid-call) is
still booked as not billed; telling "sent, outcome unknown" apart from "rejected on the spot" is open.

## Revision (2026-10-08, second pass): an unanswered call is not a free one, and following a stopped task costs nothing but the wait

The first revision left three gaps; each is now pinned by a regression test.

1. **"Sent, outcome unknown" is told apart from "rejected on the spot".** A non-idempotent request that reached the
   provider and got no answer — a read timeout, a connection dropped mid-answer, or a gateway's "I didn't wait"
   (502 / 504 / Cloudflare 52x; a plain 500 from the origin is not one) — is classified by
   `http_retry.sent_but_unanswered`, the other face of the rule that refuses to resend it. Such a failure is booked
   as an estimate from the request, annotated `outcome_unknown`, and the job says *"the request reached the
   provider but no answer came back; it may have finished and charged — check its console before generating
   again"* (`genErr_outcomeUnknown`). A 401 or a refused connection is still *not billed*. Synchronous paid calls
   (OpenAI images, Seedream, Qwen image edit) now wait up to 600 s for the answer instead of 120 / 180 s; connecting
   still gives up after 30 s. (`tests/test_unanswered_paid_calls_are_billed.py`)
2. **A restart in the middle of a provider call is booked.** The runner marks the job (`payload.provider_call`)
   just before it calls the adapter and removes the mark when it is done, whatever the outcome; a process that
   dies in between leaves the mark. After the restart, `generation.runner.reconcile_unsettled_charges` (registered
   in `domain/restart`, after the job reconciler) books an estimate annotated `interrupted_by_restart` (plus
   `unsettled_remote_task` when a receipt existed but the provider cannot be resumed) for each such job that the job
   reconciler failed — once; resumable ones were already picked up and are not touched.
3. **Following a stopped task to its end no longer downloads the result or holds a slot.** When a cancelled task
   cannot be withdrawn, the runner still follows it to a terminal state so the charge can be booked, but through a
   watch with `collect=False`: the shared poll loop hands over the terminal payload and stops
   (`RemoteTaskSettled`) instead of returning a URL to download. The charge is booked from that payload with
   `cancelled_locally`, as before. While following, the job yields its slot (the same mechanism as waiting on a
   child job). The job is marked `remote_task.following`; a restart in the middle resumes the follow in a
   background thread and books it (the mark is removed after the booking commits, so a second restart cannot book
   it twice — the idempotency key would refuse anyway). Stopping still means giving up the result: nothing lands
   in the library. Adapters that do not use the shared poll loop (plugin providers) still follow by collecting.
   (`tests/test_cancelled_generations_follow_without_downloading.py`)

Related: the runner's working directory (and the plugin output directory) moved from the system temp directory to
`<data dir>/tmp/<purpose>/`, cleared at startup before any job resumes, so a process killed mid-download no longer
leaves hundreds of megabytes behind. (`tests/test_scratch_left_by_a_killed_backend_is_cleared.py`)

**Still open.** A synchronous call that the *user* stops while it is in flight is still booked as not billed
(stopping aborts the connection; whether the provider finished is unknown, and the user chose to give it up).
