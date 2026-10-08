# ADR 0049:「已取消」是任务自己的终态,不是一种失败

## Status

Accepted — 2026-10-09,已实现(见文末「实现记录」)。2026-10-08 后端架构那一路起草(来源:UC-02 后端那一半、BA-01);
文末待拍板 1–10 和用词那一条由维护者 2026-10-09 **全部照推荐拍板**(拍板页 D16–D26,对照见「拍板记录」)。

## Context

### 此前怎么记「取消」

任务(`jobs` 表)只有四个状态:`queued` / `running` / `succeeded` / `failed`。**被人取消记成 `failed` + `error_key = jobErr_cancelled`**
(`backend/app/domain/jobs.py` 的 `_cancel_job_row`,`error` 写「已取消」,消息 `jobMsg_cancelled`)。要把「我自己停掉的」和「跑挂了」
分开说的地方各自去认这个 key:`jobs.was_cancelled`(给 webhook 的回报、画板格子的回执)、生成记录抄下同一个 key(`generation.runner`)、
文档解析和模型库 / 工作流库的几处(`documents/extraction`、`plugin_parse`、`model_library`、`workflow_library`、`workflows/engine`)。

**没认的地方就把取消当成失败**,而这样的地方是大多数:

| 哪里 | 现在的样子 |
| --- | --- |
| 任务中心(`frontend/src/components/jobs/TaskCenter.tsx`) | `terminal = succeeded \|\| failed`,`failed` 一律红色 `toast.error`「· 失败」,桌面版再发一条系统通知「失败」 —— UC-02:AI Studio 里点「停止」,原位卡片写「已停止 · 未扣费」,同一刻右下角弹红色「AI 生成 · 失败 / 已取消」 |
| 任务详情(`JobDetailDialog.tsx`) | `failed` 的那一行标成危险色 |
| 「只有失败才说」的任务种类(`jobKinds.tsx` 的 `announce === "failures"`,比如预览代理) | 用户取消一个代理也会弹「失败」 |
| 仪表盘 / 管理页的成功失败数(`domain/dashboard.py` 两处 `status == "failed"`) | 取消算进失败率 |
| 定时任务的运行记录(`scheduler/executors.sync_run_states` 把任务的终态抄过去) | 运行记录也是 `failed`,定时任务页显示失败 |
| 工作流等子任务(`workflows/executors/common.wait_until` 的 `settled`) | 子任务 `failed` → 节点报「子任务失败:已取消」 |
| 智能体的回执(`agent/receipts._summarize`) | 「「成片」失败了:已取消。」 |
| 智能体经接口查任务(`GET /api/jobs/{id}`) | `status: failed`,要自己去读 `error` 才知道是取消 |

前端其实已经备好了这个词:`frontend/src/components/jobs/runStatus.ts` 的状态表里有 `cancelled → runStatus_cancelled`,只是后端从来
不发这个值。

### 第一批修复之后多了两个约束

- **终态不回头**(ADR 0018 修订决定 5,`jobs._terminal_is_terminal`):把落了终态的任务写回 `queued` / `running` 当场抛 `JobStateError`;
  终态之间的改写不拦(发布器回收成「失败」之后又回报了成功,照实记成功)。`TERMINAL_STATUSES` 是这个守卫和「先拿住任务再写」
  (`lock_active_job`:`status in ("queued", "running")`)共同的判据。
- **取消的代理在素材上记「没有代理」**(`media_info.proxy_status = "failed"`,不停在 `pending`,否则下次启动的补齐扫描会再排一次)。
  那是素材上的状态,不是任务的状态,和本篇无关,但读的人容易把两个 failed 混在一起。

### 维护者库里有多少(2026-10-08,只读查的)

`jobs` 里 82 条 `failed`,其中 1 条是取消(`ai_generation`);`scheduled_task_runs` 5 条 `failed`、2 条 `succeeded`;`generation_jobs`
1 条记着 `jobErr_cancelled`。量很小 —— 迁移便宜;但取消这个动作在第一批修复之后才真正「停得下来」,往后会多起来
(AI Studio 的「停止」、画板格子的停止、工作流停止都会级联出一串取消)。

## Decision

1. **`cancelled` 是任务的第五个状态,也是终态。** `TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")`;取消(`_cancel_job_row`,
   含级联到的后代)写 `status = "cancelled"`、消息 `jobMsg_cancelled`,`error` / `error_key` 留空 —— 取消不是一个错误,没有原因可说。
   谁取消的、是不是从父任务级联下来的,记在那一条 `job.cancelled` 事件的 payload 里(已经有这条事件)。
   `was_cancelled(job)` 变成 `job.status == "cancelled"`,调用它的地方不用改;`CANCELLED_ERROR_KEY` 只留给迁移用,之后删。
2. **`cancelled` 是吸收态:进去之后什么都改不了**,包括改成别的终态。守卫在 `_terminal_is_terminal` 上加一条
   「旧值是 cancelled、新值不同就抛」。理由:取消是人的决定,迟到的「成功」也不该推翻它 —— 第一批已经让取消停得下进程、产出不落,
   一个迟到的成功只能是「没停住的那一下」,该查的是为什么没停住。发布那条「失败 → 成功」的改写不受影响(它从 failed 出发)。
   租约过期(`expire_worker_leases`)、重启中断(`reconcile_orphaned_jobs`)、父任务失败照旧是 `failed` —— 那不是人的决定。
3. **一条迁移,一次改完老数据**(不写兼容分支):
   - `jobs`:`status = 'failed' AND error_key = 'jobErr_cancelled'` → `status = 'cancelled'`,`error` / `error_key` / `error_params` 清空,
     `message_key` 置成 `jobMsg_cancelled`;
   - `scheduled_task_runs`:它的任务已经是 `cancelled` 的(按 `job_id` 连上去)→ `status = 'cancelled'`,`error` 清空;
   - 生成记录(`generation_jobs`)**形状不动**:它显示「已停止」靠的是自己抄下的 `error_key`,照旧;只把抄的那一处
     (`generation.runner.record_failure`)改成看 `status == "cancelled"`。
   - 是一次性迁移,`DATABASE_SCHEMA_VERSION` 跟着加一(BA-09 那条棘轮会要求);老版本因此拒绝打开迁过的库 —— 老版本不认识
     `cancelled`,让它照常跑反而会把这些任务当成「既没成功也没失败」一直挂着。
4. **后端各处按新状态说话:**
   - 智能体回执:「「成片」已取消。」—— 仍然送(智能体提交了它,应该知道它不会有结果了);智能体自己经确认卡 / 工具取消的那种
     已经看到了结果(`acknowledge_seen` 的同一个判据),不送。
   - 工作流等子任务:子任务 `cancelled`、而这一轮自己没在停(用户在任务中心单独取消了某个子任务)→ 节点失败,文案
     「子任务已被取消」(新 key,不再是「子任务失败:已取消」);整轮在停时照旧整轮 `cancelled`(工作流任务本身也是被取消的那一个)。
   - 定时任务运行记录同步时抄 `cancelled`;webhook 回报直接给 `job.status`(不再拿 `was_cancelled` 翻译一次)。
   - 仪表盘 / 管理页:`cancelled` 不进失败率,单列「已停止」数。
   - 外部执行器协议(`/api/jobs/worker/report`)**不新增**可回报的 `cancelled`:取消只由 Mosael 发起;执行器下一次回报 / 心跳时
     读到终态就停(和现在一样)。
5. **前端跟着同一个版本改**(API 的 `status` 本来就是字符串,打包版前后端一起发,没有新旧混跑的问题):
   - 任务中心:`cancelled` 算终态;**不弹红色错误、不发系统通知**(停止是用户自己的动作,原位已经说了「已停止」);面板上的
     那一行用中性色、写「已停止」;「×N 收拢」按种类 + 状态 + 主体分组,已停止的和失败的分开。
   - 任务详情、子任务清单、定时任务页、工作流执行历史:`runStatus_cancelled` 已经在表里,只要不再按 `failed` 上色。
   - `announce === "failures"` 的种类(预览代理):取消不算失败,不说。
   - UC-02 前端那一路现在按 `error_key === "jobErr_cancelled"` 判的那几处,随这篇落地改回只看 `status`。
6. **守着它的测试**:取消 → `cancelled`、级联的后代也是;`cancelled` 改不动(写回进行中、改成别的终态都抛);迁移(老形状进、新形状出,
   在维护者库副本上试跑);任务中心对 `cancelled` 不弹错误;仪表盘不把它算进失败;一条棘轮扫后端里写死 `("succeeded", "failed")`
   的终态列表,要求用 `TERMINAL_STATUSES`(dashboard.py 里现在就有两处)。

## 否掉的备选

- **只在前端按 `error_key` 判(UC-02 的最小修法)**:能止住红色 toast,但「取消」仍然有两种说法 —— `status` 说失败、`error_key` 说取消。
  每一个新加的消费方(统计、导出报表、智能体、插件看任务)都要记得去认那个 key,而漏掉的那一处不会报错,只会把取消说成失败。
  这正是现在的局面:后端已经有七八处各自去认它。可以作为本篇落地之前的止血,不作为终点。
- **把取消原因写在 `error` 里、`status` 用 `cancelled`**:「已取消」不是一个原因;原因(谁、从哪级联)是事件该记的,而 `error`
  在界面上是红字。
- **`cancelled` 允许改成 `succeeded`(迟到的成功覆盖取消)**:看起来更「如实」,但第一批修复之后取消会真的停下进程、丢弃产出;
  一个迟到的成功意味着这些都没生效,而那时产出已经被丢了 —— 记成成功反而指向一个不存在的结果。
- **生成记录也加一个 `cancelled` 列 / 状态**:它是创作历史,显示「已停止」已经靠抄下的 key 做到了;动它的形状没有收益。

## Consequences

- 用户点「停止」不再收到红色的「失败」和系统通知;任务中心、定时任务页、工作流历史上取消和失败分得开;失败率不再被取消污染。
- 智能体查任务看到的是 `cancelled`,回执说「已取消」,不会把用户的取消当成一次需要重试的失败。
- 一次性迁移 + 版本号加一:老版本拒绝打开迁过的库(这是有意的)。
- `TERMINAL_STATUSES` 多一个值:所有用它的地方(终态守卫、`lock_active_job`、清空已结束、等子任务、重启收尾)自动认得;写死
  `("succeeded", "failed")` 的地方要逐个改(棘轮会列出来)。
- 不做的代价:UC-02 的前端补丁留在原地,「取消」长期有两种说法;新的消费方继续默认把取消当失败;仪表盘的失败率随着「停止」
  按钮用得越多越失真。

## 分步

一步做完(后端、迁移、前端同一个版本发):先后端(状态、守卫、迁移、各消费方、棘轮),再前端几处显示,最后删掉 UC-02 的
`error_key` 判断和 `CANCELLED_ERROR_KEY`。规模 M(后端半天 + 前端半天 + 维护者库副本试跑)。

## 拍板记录(2026-10-09,维护者照推荐)

| 拍板页 | 本篇 | 定了什么 |
| --- | --- | --- |
| D16 | 待拍板 1 | 要一个真正的 `cancelled` 终态。 |
| D17 | 待拍板 2 | `cancelled` 进去就出不来,改成别的终态也不行;发布那条「失败 → 成功」不受影响。 |
| D18 | 待拍板 3 | 取消的任务清掉 `error` / `error_key` / `error_params`;谁取消的、从哪一级联下来的记在 `job.cancelled` 事件里。 |
| D19 | 待拍板 4 | 级联取消的后代也记 `cancelled`;租约过期、重启中断仍记 `failed`。 |
| D20 | 待拍板 5 | 给智能体送回执,说「已取消」;智能体自己已经看到结果的不送。 |
| D21 | 待拍板 6 | 不进失败率;统计页和管理页单列「已停止」。 |
| D22 | 待拍板 7 | 定时任务的运行记录在同一条迁移里也迁成 `cancelled`。 |
| D23 | 待拍板 8 | 单独取消工作流里的一个子任务:那个节点算失败,写「子任务已被取消」;整轮取消时整轮 `cancelled`。 |
| D24 | 待拍板 9 | 外部执行器不能回报 `cancelled`,取消只由 Mosael 发起。 |
| D25 | 待拍板 10 | 任务中心对 `cancelled` 不弹提示、不发系统通知;面板上用中性色。 |
| D26 | (拍板时新加) | 用词随按钮:用户按的是「停止」的地方写「已停止」,任务中心的「取消任务」对应「已取消」;都用中性色。 |

待拍板 11(取消的预览代理在素材上仍记 `proxy_status = failed`)不在拍板页上单列,照推荐不改:素材上要表达的是「现在没有代理、
可以手动重试」,和任务为什么停无关。

## 实现记录(2026-10-09,分支 feat/adr-0049-cancelled)

**后端**
- `jobs.CANCELLED` / `TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")`;`was_cancelled` 只看 `status`。`_cancel_job_row`
  写 `cancelled`、清空原因、`job.cancelled` 事件的 payload 是 `{"by": 用户 id 或 null, "cascaded_from": 级联来源任务 id 或 null}`;
  `cancel_job(db, job, *, by)` 必须说出是谁(任务中心是点的那个人,webhook、Mosael 自己停的是 null)。执行体发现自己没人要了
  (`run_job_guarded` 接住 `JobCancelled`)也落 `cancelled`。租约过期的任务照旧 `failed`,它的后代落 `cancelled`。
- `_terminal_is_terminal` 加一条:旧值是 `cancelled`、新值不同就抛 `JobStateError`。
- `CANCELLED_ERROR_KEY`(「已取消」那句)**没删**:执行体自己抛的 `JobCancelled`、工作流节点事件里「这一步被停下」、生成记录上
  抄下的「已停止」(`generation.runner.record_failure` 在任务落 `cancelled` 时写它,`GenerationJobOut.stopped` 照旧认它)还用它。
  草稿里「之后删」的那半句不成立:生成记录活得比任务久,它得自己记得是被停下的。
- 消费方:webhook 的运行状态直接给 `job.status`;`JobOut` 去掉 UC-02 的 `cancelled` 计算字段,`status` 收成五个值的 Literal;
  定时任务的运行记录照抄 `cancelled`;智能体回执「「x」已取消。」;统计页 `daily[].cancelled` / `jobs_cancelled`、管理页
  `jobs_by_day[].cancelled`,都不算进 failed;工作流等子任务时子任务 `cancelled` → 这一轮在停就整轮停,没在停就
  `wfErr_childCancelled`;字幕配音等逐句合成、`ensure_wanted`、父任务结束后不再派生、重启后接着跟远端的生成,都认得 `cancelled`。
  外部执行器协议本来就只收 running / succeeded / failed,没改。
- 迁移 `migrate-cancelled-jobs-get-their-own-status`(`DATABASE_SCHEMA_VERSION` 11 → 12):`jobs` 里 `failed` + `jobErr_cancelled`
  → `cancelled`,原因清空、消息换成 jobMsg_cancelled;连着这些任务、记着 `failed` 的定时任务运行记录 → `cancelled`、`error` 清空。
  生成记录不动。维护者库 2026-10-08 只读查过:受影响的是 1 条任务(`ai_generation`)、0 条运行记录。
- 棘轮:`app/` 里不许再写死 `("succeeded", "failed")` 这一对当终态表(此前 dashboard.py 有一处)。

**前端**
- `runStatus.jobDisplayStatus` 删掉,各处直接看 `status`;「结束了没有」统一问 `runStatus.jobSettled`(棘轮扫 `src/`,不许再写
  「成功或失败」两种当结束 —— 漏一处,被停下的任务会被当成还在跑、一直轮询)。改到的:任务中心、`useWatchedJob`、导出、
  逐字稿、浏览器视频下载、AI Studio。
- 任务中心:被停下的不弹提示、不发系统通知,改动的数据照样刷新;行上用中性色和 `Ban` 图标,写「已取消」(按钮是「取消任务」)。
- 用词随按钮(D26):工作流执行历史(按钮「停止运行」)写「已停止」;AI Studio 照旧「已停止」(任务刚落 `cancelled`、记录还没抄下的
  那一下也算停下);工作台照旧「停了」;任务详情、子任务清单、定时任务页按任务状态表写「已取消」;浏览器视频下载「已取消下载」改成
  中性色;装节点的那一条写「x 的安装已取消」,此前落到「正在装」。
- 统计页的活动图多一段中性色的「已停止」,读数写「n 失败 · n 已停止」;管理页的图同样分出来,概览一句加上「已停止 n」。
