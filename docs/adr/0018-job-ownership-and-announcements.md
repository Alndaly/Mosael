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

## 修订:取消要真的停下,任务的状态只经总线写(2026-10-08)

决定 1 说「取消沿着 `parent_job_id` 级联」。全项目分析时实测,级联到的那一行确实改成了「已取消」,但活没停、结果也没作废:

- **排队时被取消的会被复活。** 代理、配音、播客、截取、从链接导入这几个执行体一上来直接 `job.status = "running"`:
  在等转码 / 合成名额、派发器满着的时候被取消(工作流取消级联下来的那一批正是这样),轮到它时被写回「在跑」、
  照跑到底、最后记成成功;落终态之后的收拾和回执跑两遍。付费的配音、播客照样调用。
- **跑到一半被取消,子进程不停、名额不放、产出照样落。** 任务里经 `run_logged` 起的 ffmpeg / Demucs、常驻的识别 /
  合成进程没登记在任务的取消开关上:Demucs 照跑最长一小时,占着导出、分离共用的 RENDER_SLOTS;跑完之后照样登记进素材库、
  把时间线上的片段换掉、覆盖旧逐字稿。
- **执行体在自己的 try 之前抛了,任务停在进行中。** `run_job_guarded` 要每个执行体自己记得套,生成、工作流、字幕配音、
  画板、从链接导入、资产库画图七个没套 —— 连接池等满、库被锁的那一下,任务一直转圈到下次重启。

决定(在原来四条之外):

5. **状态只经总线写。** 起步 `jobs.start_job`、收尾 `jobs.finish_job`,都先确认这一行还活着,返回 False 时执行体停手。
   ORM 上守着「终态不回头」:把落了终态的任务写回排队 / 在跑,当场抛 `JobStateError`。终态之间的改写不归它管 ——
   发布器卡住被回收成「失败」之后又回报了成功(视频确实发出去了),照实记成功;那是 `publish/worker._sync_job` 自己的判断。
   生成那边「失败但回执在」的记账路径不改任务状态,不受影响。
6. **取消停得下进程。** `run_logged` 在任务里跑时自成一组、登记在任务的取消开关(`core/abort`)上,开关一拉停下整棵进程树;
   常驻的识别 / 合成进程同样登记,停下的代价是下一次重新加载权重。名额随执行体退出放掉。
7. **副作用之前问一句。** 登记产出、改时间线、写逐字稿之前,执行体经 `jobs.ensure_wanted()` 问「这件活还有人要吗」
   (先看开关 —— 取消在提交之前就拉下它;再读库里那一份;认的是上下文里正在跑的那个任务,所以工作流节点调分离、降噪时
   认的是工作流)。不要了就抛 `JobCancelled`,产出不落。只改库的那一步(片段声音处理换片段、转写写逐字稿)先拿住任务、
   在同一个事务里写、再落成功,中间插不进取消。
8. **兜底由派发处套。** `dispatch_job` 替每个执行体套 `run_job_guarded`;它认得 `JobCancelled`,把取消没能提交的那种
   收成「已取消」而不是「出错」。失败那一句里的任务种类名是文案片段,按读的人的语言翻。

后果:取消一个排队中的配音不再花钱;取消分离、降噪、转 GIF、转写、代理,子进程一两秒内停下、名额放出来,素材库、时间线、
逐字稿保持取消前的样子。代理被取消时那份代理记成「没有」(可以手动重试),不再停在「生成中」—— 否则下次启动的补齐扫描
会把用户的取消撤销。守着这几条的测试:`test_cancelled_work_stops_and_stays_cancelled`、`test_dispatched_bodies_are_guarded`,
以及只减不增的 `test_job_status_goes_through_finish_job`(剩下的只有发布那两处终态之间的改写)。

## 修订:重启收尾一次提交;任务的维护分批做(2026-10-08)

**重启收尾是一次用例、一个事务**(`domain/restart.settle_previous_run`,lifespan 只调它)。此前任务那一步(`reconcile_orphaned_jobs`)
自己提交,提交钩子当场就跑:孤儿任务的回执在空闲的对话里起了一轮,紧接着「把卡住的会话拨回 idle」把这一轮当成重启前的孤儿
拨回去、补一句「上一轮对话因后端重启而中断」—— 而那一轮正在跑,用户再发一句就是同一个会话两轮并发;重启前正卡着的会话,
回执落成「待送」后再没有一轮来捞。现在几个收尾函数都只改对象、不提交(任务、插件调用、智能体会话三处的 `commit` 去掉了;浏览器那一项此前自己开事务,
和外层攥着写锁的事务抢锁会让启动失败,也改用同一个会话),全部收完一起提交;落终态之后的收拾、回执、接着干远端任务(`_RESUMERS`)都登记在提交之后。中途任何一步失败,整段回滚、谁都不叫醒。

**任务的维护不把任务读成 ORM 对象,删按批、一批一个事务。** 任务事件的保留清理(调度线程启动后第一拍、之后每 6 小时)和任务中心的
「清空已结束」此前都是先整行读出任务、再逐个 ORM 删;ORM 的 DELETE 每次都把身份映射过一遍,任务越多越是平方级(维护者库副本放大
到 1.2 万个任务:清理 11.6 秒、「清空已结束」41.5 秒;3.2 万个:清理 67 秒),全程一个事务攥着写锁,另一个连接的写入 5 秒后
`database is locked`。现在挑出要删的只是 id(集合式查询,读,不占写锁),删按 `PRUNE_BATCH` / `DELETE_JOBS_BATCH` 一批一个事务;
「清空已结束」因此不再走请求的 `Tx`(清理是幂等的:中途失败,删掉的那几批就是删掉了)。同样放大到 3.2 万个任务,期间另一个连接
每 50 毫秒写一次,最长等 2 秒、一次都没失败(机器负载 50 以上时量的)。
