# ADR 0064:工作流「等人确认」—— 暂停落库、从暂停那一节点恢复

## Status

Accepted — 2026-10-16。新增节点 `await_approval`(「等人确认」)+ 一张 `workflow_run_approvals` 表 +
引擎的**可持久化暂停 / 恢复**。飞书卡片和应用内两个入口汇到同一处决定。

## Context

### 引擎此前**没有**可持久化的暂停

执行内核 `run_graph`(`backend/app/domain/workflows/engine.py`)是一轮同步跑完的:节点在各自线程里
跑,跑完写上下文、发事件、按 `waits_for` 往下派。一轮图只有两种收场:

- **取消**:每一拍重读任务状态(`is_cancelled` / `run_scope.halted`),落 `cancelled` 终态;
- **失败**:任一节点抛异常,`halt.set()`,落 `failed`。

两者都是**终态**:任务落了终态就再也回不来(`jobs._terminal_is_terminal` 是 ORM 层的硬约束,
`TERMINAL_STATUSES` 之外只有 `queued` / `running`)。引擎里 `checkpoint` / `resume` **零命中**。
唯一"跨重启接着干"的机制是任务总线上的 resumer 接缝(`jobs.register_resumer`,当时只有 `ai_generation`
用了它)—— 它做的是**重新发起**那一类活,不是从某个节点接着跑。

所以"跑到某一步停下、过几天有人在飞书里点一下、从**那一步**接着跑,而且前面跑过的节点一个都不重跑"
在这套内核上是不成立的。这就是本任务的核心工作量。

### 为什么不能"在节点里 sleep 等人点"

最省事的做法是让节点阻塞轮询(引擎已经有 `executors/common.wait_until`)。它有三个问题:

1. **重启就丢**。一次运行可能已经烧了钱(起过的浏览器会话、生成过的素材、付过的模型调用),
   进程一死,那次等待连同"前面跑到哪了"一起消失;
2. **一条线程挂 24 小时**。`JobRunner` 的派发名额可以 `parked` 让出去,但线程本身还在,而且每个
   暂停的运行各占一条;
3. **没有现场**。就算退一步说"重启之后重新跑一遍",那也要重跑前面**已经花过钱**的节点 ——
   这正是需求里明令不许的。

## Decision

### 1. 暂停 = 把一轮图拆成两半,中间那一份现场**落库**

跑到 `await_approval` 时:

1. 执行器(`executors/approval.await_approval`)在**自己的事务**里建好待批单并提交 ——
   必须比卡片先落库,否则点回来只会说"这张单不存在";
2. 它抛 `AwaitingApproval`(一个控制流信号,不是错误);
3. 引擎捕获它:**不立停的信号、不记失败事件**,等还在飞的兄弟节点各自落定(它们的产物一并进现场),
   然后把现场(`GraphResume` = 上下文 + 跑过的 + 跳过的)交回;
4. `engine._park_at_approval` 把现场写进 `WorkflowRunApprovals.checkpoint`,让任务卡说出
   「等待确认:…」并发一条 `workflow.awaiting_approval` 事件,**然后不收尾** —— 线程在这里结束,
   连接和派发名额都还回去;
5. 站内通知与飞书卡片排在**提交之后**(`after_commit`)—— 说得出去的东西必须已经落库,
   否则手快的人在检查点提交之前点了确认,那次运行会卡在一个永远唤醒不了的等待上。

任务状态**仍然是 `running`**。理由:它确实是活的(取消、重启接回来走的都是普通任务那两条路),
而新加一个非终态会同时打破 `lock_active_job` 只认 queued/running、`TERMINAL_STATUSES`、
外部 worker 认领和前端的状态表 —— 换来的是任务卡上一个更贴切的词,不值。
**在任务中心 / 运行历史里它长这样**:状态 `running` + 消息「等待确认:{标题}」+ 一枚
`workflow.awaiting_approval` 节点事件 + 运行历史面板顶上那条「这一步在等你确认」。

### 2. 恢复 = 重新进 `run_graph`,但 `done` 里的节点**直接跳过**

`run_graph(..., resume=GraphResume)` 把 `executed` / `done` / `context` 播种进去,
`schedule_ready` 对 `done` 里的节点**不派发**(`scheduled` 预置成 `done ∩ order_ids`)、不发事件、
不重新计数。于是:

- **前面跑完的节点一个都不会执行第二次** —— 上下文是原值,不是重算出来的;
- 暂停的那一个节点自己会再进一次(它不在 `done` 里),这一次它读到单上的决定,就地交出
  `decision` 那一格;
- 进度(`job.progress`)从已落定的节点数起算,不回头。

检查点存的是**整份上下文**(不是事件里那种有界快照):下游插值要用的就是完整值。
`executed` / `done` 两个集合也一起存,恢复时连"哪些是条件分支跳过的"都不用重推。

**只支持主流程**:循环体 / 子图里的暂停要往外套好几层,而落检查点的地方只有主流程
(体的执行内核 `has_job=False`)。`await_approval` 的运行前检查(`_no_nested`,借
`PreflightNode.scope`)在**开跑之前**就拦下它 —— 那些图里前面的节点可能已经花了钱。

### 3. 重启之后接着等:任务总线上登记一个 resumer

`reconcile_orphaned_jobs` 把重启时还 `running` 的任务判成"被中断、请重新发起" —— 对一个**在等人点**
的运行,那句话是错的。所以工作流域在总线上登记:

```python
jobs.register_resumer("workflow", can_resume=approvals.can_resume, resume=approvals.resume_job)
```

`can_resume` **只认手里有一张带检查点的待批单**的那种运行;其余的照旧判失败 —— 既有语义一点没变
(那次全量测试里"重启收尾把普通运行判失败"的用例仍然绿)。

### 4. 飞书与站内两条路**汇到同一处决定**

```
飞书卡片回调 handle_card_action ─┐
                                ├─→ workflow_uc.decide_run_approval(领域用例)
应用内 POST /api/run-approvals/…┘        ├─ ensure_workspace_perm(edit)   ← 同一道闸
                                         └─ approvals.decide_and_wake
                                              ├─ CAS: pending → 决定(谁先到谁算)
                                              └─ after_commit → dispatch_resume(job)
```

- **一处写决定**:`decide` 是一条 `UPDATE … WHERE status='pending'`,rowcount 决定谁赢。
  两条路同时点只有一个算数,赢的那一个才唤醒运行 —— 不会跑两遍,也不会"先点的那条没提交就不算数"。
- **一处唤醒**:`wake()` 在提交之后派发(`after_commit`,和 `jobs.dispatch_job` 同一个约定)。
- **卡片发到哪**:`integrations/feishu/approvals.route_for_approval` 先看这次运行是不是来自飞书会话
  (任务载荷里的回执指着一次 `origin="feishu"` 的智能体会话,和工具确认卡同一个取法),是就发回那个群;
  不是就看发起这次运行的人在这个工作区绑没绑飞书,绑了就当私聊发给他(`receive_id_type=open_id`)。
  两条都不成立就只发站内。
- **回执**:卡片回调允许在响应里直接返回一张新卡,飞书就地替换原卡(`cards.settled_approval_card`),
  所以不必存 `message_id`(和工具确认卡同一个取舍)。超时那一路没有回调可挂,改为**另发一条消息**。

**领域层不认识集成层**:`domain/workflows/approvals` 只暴露 `use_run_card_sender(...)`,
`app.main._wire_seams` 把 `feishu_approvals.announce_run_approval` 接上去。同理,`approvals` 不许
import `engine` —— 那会给"引擎 ⇄ 执行器"那一族添一个新环;方向反过来,引擎 import 领域并在模块末尾
`use_resume_dispatcher(continue_workflow_job)`。两条都由 `tests/test_import_layering` 守着。

### 5. 没有飞书时退化成站内,**不报错也不放行**

站内通知是**兜底**,不是补充:`notify(...)` 先写,卡片后发且一律降级。没有机器人、卡片能力没开、
网络不通,这次运行都照旧在等。应用内那一格是运行历史面板顶上的「这一步在等你确认」
(`RunApprovalNotice.tsx`)—— 和飞书点的是同一个后端用例。

### 6. 超时与失败的语义

到点由后台那一拍处理(`workers/scheduler.tick` → `approvals.expire_due`),按节点上写的办:

| `on_timeout` | 做什么 | 下游拿到什么 |
| --- | --- | --- |
| `abort`(默认) | 落 `timeout` 决定并唤醒;执行器抛出 `wfErr_awaitApprovalTimedOut`,**这次运行失败** | 没有 —— 运行停了 |
| `continue` | 落 `timeout` 决定并唤醒 | `decision = "timeout"` |
| `remind` | **不落决定**,把下一次提醒的时刻往后推一格并再通知一次 | 一直等 |

**三种都会再通知一次** —— 一个门禁悄悄过期等于没装。默认 `abort`:一个门禁的用处就是拦住
"没人看着就往下走",超时还继续等于这个门没装。
「只提醒」刻意**不是**一次性的:提醒之后 `expires_at` 往后推一格,否则每一次轮询都提醒一次。

### 7. 拒绝的语义(`on_reject`)

拒绝是**一个人真的做了决定**,和超时那种"没人做"不是一回事。按节点上的 `on_reject` 办:

| `on_reject` | 做什么 | 下游拿到什么 |
| --- | --- | --- |
| `abort`(默认) | 执行器抛出 `wfErr_awaitApprovalRejected`,**这次运行失败**,决定不交到下游 | 没有 —— 运行停了 |
| `branch` | `rejected` 当成一个决定交给下游(`decision = "rejected"`) | `decision = "rejected"` |

`abort` 和超时 + `abort` **同一个失败口径** —— 想"拒绝了就停下",用默认的 `abort` 即可;想
"拒绝了走另一条分支",就在节点上写 `on_reject = "branch"`,下游用条件节点接 `decision = "rejected"`
(和 `approved` / `timeout` 一样是三值文字,不是错误)。

> **默认由 `branch` 改成 `abort` 是 2026-10-16 拍板、有意的**:`await_approval` 节点刚上、
> 还没有旧数据,所以直接改默认、不加兼容(没有"老图上没写 on_reject 要按 branch 迁"这一档)。
> 一个门禁的用处就是拦住"没人点通过就往下走" —— 拒绝还继续往下,等于这个门没装。

取消走既有那条路(`jobs.cancel_job`),并顺带撤掉待批单(`register_cancel_listener("workflow", …)`)——
否则卡片还点得动、待批列表里还挂着一条永远没人处理的等待。

## Consequences

- **`await_approval` 是全仓第一个"会暂停的工作流节点"**。别的节点要么跑完、要么失败、要么被取消;
  暂停是第四种收场,`GraphRun.paused` 把它说出来,`run_workflow` 据此不收尾。
- 新增表 `workflow_run_approvals`(随任务级联删除),登记在 `domain/ownership.TABLE_OWNERS`、
  `tests/schema_baseline.json`、`domain/restart.NOT_ORPHANED_BY_RESTART`(理由:它在等人,
  不在等进程 —— 收尾它的是那个 resumer)。
- 暂停的运行**不占**线程、不占数据库连接、不占派发名额。一次停 24 小时的门因此是便宜的。
- 检查点存整份上下文,一行可能不小。取舍:恢复的正确性优先;真到了要压的时候,
  可以改成"存摘要 + 从 `workflow_run_outputs` 回填全文",那是另一笔。
- **未做**:循环体 / 子图里的暂停(见上,开跑前拦下);飞书卡片输入框那一格能不能把备注带回来
  取决于飞书回调的形状,`worker.card_action` 已经把 `form_value` 一起转发、`_note_from` 两种写法都读,
  但**真机尚未验证**(读不到就是空备注,决定本身照常落)。

## 验收(可复查的证据,不只是最终结果)

`backend/tests/test_await_approval_node.py`(29 条):

- **暂停落库 / 重启仍在等**:暂停后调 `reconcile_orphaned_jobs`,`failed == 0`、任务仍 `running`、
  仍是**同一张单**;恢复之后数 `project_create` 落下的 `projects` 行仍是 1、`workflow.node.started`
  里那个节点只有 1 次。
- **从暂停节点继续、前面不重跑**:批准之后 `projects` 仍为 1、`make` 的 started 为 1,
  而门自己(`gate`)是 2 次(一遍停下、一遍读决定)。
- **超时三档**:`continue` 走到 `decision:timeout`;`abort` 失败且 `error_key == wfErr_awaitApprovalTimedOut`;
  `remind` 仍是 pending 且 `expires_at` 往后推。三档都断言**多了一条超时通知**。
- **拒绝两档**:`on_reject=abort`(默认)失败且 `error_key == wfErr_awaitApprovalRejected`、决定不交到下游;
  `on_reject=branch` 走到 `decision:rejected`、下游按它分支。
- **没有飞书**:通知在、`job.status == "running"`、`feishu_bot_id` 为空、
  `GET /api/run-approvals` 列得到、`POST …/decide` 批得动。
- **飞书回调**:直接调 `handle_card_action`(和 `connections.dispatch` 同一个函数),
  卡片就地换成「已确认」,`decided_via == "feishu"`、备注落库,运行接着跑;没绑定的人点只得到 toast。
- **取消**:任务 `cancelled`、待批单一起 `cancelled`,之后再点不生效。
- **放错地方**:循环体里的 `await_approval` 被 `check_runnable` 以 `wfErr_awaitApprovalNested` 拦下。
