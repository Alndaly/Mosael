# 进程边界审计:后端之外那些跑着的东西,和它们之间的约定

> 日期:2026-09-21 · 基准:`e58190f2` 之后的干净工作区 · 版本 1.4.2
> 范围:`electron/`(主进程 / preload / system / 发布执行器 / 浏览器执行器)、`agent-sidecar/`、
> `browser-extension/`、`plugins/` 与 `domain/plugins`、`domain/blender`、`backend/mcp_server.py`、
> `website/`(只看它与主仓库的耦合点)。**不含**后端领域内部逻辑、AI 供应商层、前端页面内部。
> 方法同 [链条审计](2026-09-21-chain-audit.md):沿链条走,每条给 `文件:行号`。
> 本文**只读**,没有改动任何代码。

---

## 0. 结论先写

链条审计的结论在进程边界上**同样成立,而且更锋利**:

> 一个值在链条的 N-1 环都在,最后一环没接上,两边都不报错。

区别在于,进程边界上这件事有一个额外的放大器:**两侧是两种语言、两个运行时、两套测试**,
所以「两边都不报错」不只是没人检查,而是**结构上没有任何一处能同时看见两侧**。仓库里已经有
对付这件事的机器(`contracts/` 的 11 份语料、`test_agent_workflow_parity.py`、
`test_executor_outputs_are_declared.py`),但它们钉住的是**数据形状**;本次找到的问题里,
最贵的三条钉的都不是形状,而是**回执、时限、和身份**——这三样恰好都没有语料覆盖。

另一个反复出现的形状:**同一课,学过一遍,没推广到隔壁那条道。**
发布执行器的多执行器围栏写了一整页注释加一份专门的测试(`test_two_publish_workers.py`),
而**并排的浏览器执行器一条都没有**;Python 常驻 worker 有 `getppid()` 看门狗和专门的测试
(`test_workers_do_not_outlive_the_backend.py`),而**花钱又写库的 pi sidecar 没有**。

---

## 1. 关键链条逐条结论

| # | 链条 | 结论 |
| --- | --- | --- |
| 1.1 | 后端 → sidecar 的 JSONL 帧形状 | **形状成立,回执断了**(§2.1)。请求/事件两侧的字段一一对得上;但 sidecar 专门为「太晚了」造的那条回执,后端整个事件循环里没有分支读它 |
| 1.2 | sidecar → 后端的凭据租约写回 | **断在最后一环**(§2.2)。后端区分了两种 409,HTTP 也带着 detail,sidecar 把两种都当成同一种,只写 stderr |
| 1.3 | 后端 → 发布执行器(claim/report) | **成立**。worker 身份跨重启稳定、`claimed_by` 记在任务上、回收判据分了「只有认领者能说」和「全局兜底」两条,并有专门测试 |
| 1.4 | 后端 → 浏览器执行器(claim/report) | **整条没有落 ADR-0002**(§2.3)。形状抄了(claim/report/heartbeat),实质一样没有:没有租约、`worker` 收了就丢、心跳写进一个没人读的字典 |
| 1.5 | 后端 → 通用 job worker | **成立**。`lease_token` / `lease_expires_at` / 心跳带 claims / `renewed` 回列表,与 ADR-0002 逐条对上 |
| 1.6 | 后端 → Blender(worker.py 跑在别人的进程里) | **边界成立,预算不成立**(§2.6)。源码不拼 Python 语句、不 import 主应用;但它借用了插件那条 60 秒的通用预算 |
| 1.7 | 后端 → 插件子进程 / MCP | **成立**。进程隔离、最小环境、output/state 分开、产出走暂存目录 |
| 1.8 | 扩展 → 后端 REST | **两处语义错位**(§2.7、§2.8):`X-Mosael-Client` 在两侧是两个意思;`Accept-Language` 写死中文 |
| 1.9 | 「只有一个后端进程」这个假设 | **成立,但没有任何一处守着它**(§2.5 尾)。全仓只有一处 `uvicorn`,无 `--workers`;Electron 有单实例锁且注释点名了两个 worker 抢任务这个后果 |
| 1.10 | 重启恢复 | **四条有,两条没有**(§2.9)。job / agent session / browser / 素材有 reconcile;`PluginInvocation` 和 Blender 的 `transfer.json` 没有 |
| 1.11 | 开发态 / 打包态 | 主要差异都是**有意的且写了理由**;两处小的不对称在 §2.12、§2.13 |
| 1.12 | 官网版本号耦合 | **自动校验覆盖两项,漏三项**(§2.11) |

---

## 2. 问题清单(按严重度)

### 2.1 【高】sidecar 说了「这条没接住」,后端从不读那句话 —— 消息被静默吞掉

**现象。** 用户对一条排队消息点「插入当前轮」。后端回 `{"steered": true}`,界面按成功处理,
而那条消息**既没有进正在跑的那一轮,也不会再被排队执行**——它从队列里消失了。

链条:

1. `agent-sidecar/src/index.ts:177-188` —— 收到 `steer` 时,若那一轮刚好结束、`active` 里已经
   没有 Agent,**专门发一条** `queued{pending:false}`,注释写得很清楚:

   > The turn finished between the user typing and this frame arriving. **Saying so lets the
   > backend send it as an ordinary next turn instead of dropping it.**

2. `agent-sidecar/src/protocol.ts:221` —— 事件类型里有它:`{type:"queued"; mode; pending: boolean}`。
3. `backend/app/ai/sidecar/adapters.py:400-446` —— `_run_pi` 的事件循环:`text_delta` /
   `thinking_*` / `tool_*` / `turn_done` / `error` / `aborted`。**没有 `queued` 分支**,落进
   `elif` 链的末尾,什么也不做。
4. `backend/app/ai/sidecar/adapters.py:214-229`(`_LiveTurn.send`)/ `:246-252`(`steer_turn`)——
   返回值是**管道写入是否成功**,不是「对面接住了吗」。
5. `backend/app/domain/agent/host.py:890-903` —— `steer_queued_message` 把那个布尔当成
   「插进去了」,为真就 `_unqueue(db, message)` + `commit`:`queued` 标被摘掉。
   而 `_drain_queue_locked`(`host.py:726-760`)只捞带 `queued` 标的消息。**消息就此蒸发。**
6. `backend/app/domain/agent/host.py:382` —— 直发那条路同一个形状(`steer_if_running and
   steer_turn(...)` 为真就落一条不带 `queued` 标的消息)。

**为什么看不出来。** 这条链上**每一环都写对了**:
`frontend/src/features/ai-studio/ChatWorkspace.tsx:239-240` 有 `chatSteerTooLate` 的提示,
注释还写着「`"steered"` would be a lie about what the agent is doing」;
`host.steer_queued_message` 的 docstring 写着「Returns False when there was no live turn」;
sidecar 专门为这件事发了一条事件。**唯独中间那一跳把问题换了**——
从「对面接住了吗」换成「字节写出去了吗」。而这两个问题在 99% 的情况下答案相同,
所以它一直看着是对的。竞态窗口本身很窄(sidecar 在 `send(turn_done)` 之后立刻
`active.delete`,而后端要等读到 `turn_done` 才 `live.close()`),但窄不等于没有,而且**命中时
用户丢的是自己刚打的一句话**。

**为什么是架构问题。** 这是链条审计 §1.3 的同一个形状,只是跨了进程:
**一侧产出的信息,在另一侧的解析器里没有落点。** 区别在于,§1.3 那次靠 AST 静态对一遍就能拦住
(执行器返回的键 vs 声明的 outputs);而这里两侧是 Python 和 TypeScript,
没有任何一处同时看得见 `protocol.ts` 的 `Event` 联合与 `adapters.py` 的 `elif` 链。
**`Event` 的每一个成员都该有一个消费者,而今天没有任何东西在问这个问题。**

**顺带:`abort` 连回执都没有。**
`agent-sidecar/src/index.ts:205-206` —— `active.get(msg.turnId)?.abort()`,拿不到就**一声不吭**。
而 `active` 是在 `onAgentReady` 时才写进去的(`index.ts:56`),它发生在
`buildAllTools(...)`(`index.ts:42`,要打一次 HTTP 拉工具清单)之后。
所以**一轮刚开始那几百毫秒里按停止,按了等于没按**:`stop_turn`(`host.py`)→ `abort_turn`
→ 管道写成功 → 返回 `true`,界面显示已停止,而那一轮继续跑到底。

**建议修法。**
1. `_run_pi` 的循环补 `queued` 分支,把 `pending` 存进 `_LiveTurn`;`steer_turn` 改成
   「等一个回执或超时」而不是「写成功即真」。`abort` 同样补一条 `aborted_ack{accepted}`
   ——今天的 `aborted` 事件只在 Agent 真的中止后才发,回答不了「你收到了吗」。
2. 上一条**同形的棘轮**:静态断言 `protocol.ts` 的 `Event` 联合里每一个 `type` 字面量,
   都在 `adapters.py` / `domain/agent/login.py` 的某个分支里出现过。它和链条审计建议的
   「领域返回的键 → 接口 schema 字段」是同一类检查,只是换到了进程边界上。
   现成的反例可以拿 `history`(见 §2.10)当第一条测试用例。

---

### 2.2 【高】凭据租约:后端分了两种 409,sidecar 把两种当成同一种 —— 下一轮被登出

**现象。** 订阅计划(Claude Pro / Kimi Code 等)偶发「刚用着好好的,下一轮突然要重新登录」。

链条:

1. `backend/app/domain/provider_auth.py:91-97` —— `_check_lease` 抛 `CredentialLeaseError` 有
   **两个不同的原因**,消息也不同:
   - `held.token != token` → 「租约已失效(**超时或被顶替**)」= 别人抢走并已经写了新凭据;
   - `held.expires_at <= now` → 「租约已超时」= **没有别人**,只是我自己慢了。
2. `backend/app/api/routes/agent_credentials.py:81-84` —— 两种都翻成 `409`,`detail=str(exc)`。
   信息**还在响应体里**。
3. `agent-sidecar/src/credentials.ts:93-98` —— 最后一环:

   ```ts
   const res = await this.post("/commit", { lease: lease.lease, credential: next });
   if (!res.ok) {
     // 409 = 租约超时被顶替,库里已是别人刷出来的新凭据。
     log(`credential commit rejected (${res.status}); 本轮继续使用内存中的凭据`);
   }
   this.seeded = next;
   ```

   `detail` 没读,两种原因合并成一种,只往 stderr 写一行。

**为什么看不出来。** 对**第一种**原因,这个处理是**完全正确**的:别人刚写了新凭据,我这份该丢。
对**第二种**却是**破坏性**的:订阅制的 refresh token 是**一次性、换出即轮换**的
(`provider_auth.py:1-11` 用整段开头讲的就是这件事),我手上这份 `next` 是刚换出来的**唯一有效**
凭据,丢掉它等于库里留着一个**已经被供应商作废**的 refresh token。下一轮 `invalid_grant`,
用户被登出。而这正是**整套租约机制存在的全部理由**——它在自己的收尾分支上被重新引入了。

触发条件不罕见:`LEASE_TTL_SECONDS = 30.0`(`provider_auth.py:31`),而租约期间要做的是
**一次跨境 OAuth 刷新 HTTP,而且走用户配的出网代理**(`adapters.py:proxy_env`)。代理慢一点、
供应商抖一下,30 秒就过去了。

**顺带:两侧的等待预算互相不知道对方。**
`agent-sidecar/src/credentials.ts:20-22` 的注释写「409 = 另一次刷新正在进行。**它几秒内会结束**」,
于是退避 400/800/1200ms 重试 3 次(合计 2.4 秒)。但后端的 `acquire_lease`
(`provider_auth.py:66-79`)**自己就先阻塞了 `ACQUIRE_TIMEOUT_SECONDS = 20` 秒**才返回 409。
所以每收到一个 409,都意味着**已经等过 20 秒**;再重试 3 次 = 这一轮对话在凭据上最多站住 80 秒,
而 sidecar 这边以为自己总共只等了 2.4 秒。

**建议修法。**
1. `commit` 的 409 分两种回:`code: "superseded"`(丢弃是对的)与 `code: "expired"`
   (**必须重试一次整个 acquire→refresh→commit**,或者至少把这份凭据强制写回并记一条可见的告警)。
   和 `error` 事件已经有的 `code: "output_limit"`(`protocol.ts:241`)同一个做法。
2. `LEASE_TTL_SECONDS` 要么显著放宽(刷新是一次跨境 HTTP,30 秒不宽裕),要么让 sidecar
   在 `fn()` 期间续租。
3. 两侧的等待预算写进 `contracts/shared-constants.json`(见 §2.5)。

---

### 2.3 【高】浏览器执行器:第三条 claim/report 通道,ADR-0002 一条都没落

**现象。** 没有单一的可见现象——这条通道今天在单执行器下工作正常。问题是它**没有任何东西
能在多执行器或执行器崩溃时保证正确**,而仓库里另外两条通道都有。

`docs/adr/0002-claim-report-worker-protocol.md` 开篇:

> **任何**跨进程执行的任务(今天的发布,将来的渲染/转写)都走同一个拉取式契约

并规定:认领带**持久化的** `lease_token` + `lease_expires_at`(60 秒),worker 必须在 `report`
里原样带回,并至少每 20 秒心跳一次 `{"worker":..., "claims":[{job_id, lease_token}]}`,
心跳返回 `renewed` 列表,未续上的执行应停止。

三条通道的实际状况:

| 通道 | 租约 | worker 身份 | 心跳 | ADR 提到了吗 |
| --- | --- | --- | --- | --- |
| `/api/jobs/worker/*` | ✅ `job_worker.py:41-49, 63-64, 93` | ✅ | ✅ 带 claims、返 `renewed` | 是,它就是主角 |
| `/api/publish/worker/*` | ❌(另一套)| ✅ `claimed_by`,跨重启稳定 | ⚠️ 只报在线 | 是,**明写为历史契约例外** |
| `/api/browser/worker/*` | ❌ | ❌ | ❌ | **ADR 里一个字都没有** |

逐条证据(浏览器那条):

- `backend/app/api/routes/browser_worker.py:24-25` —— `ClaimRequest.worker` 收下了;
  `backend/app/domain/browser/__init__.py:273-295` —— `claim_next_action(db, *, worker="")`
  的函数体里**一次都没用过 `worker`**。`BrowserAction` 上也没有 `claimed_by` 这一列。
- `electron/publish/browserBackend.ts:51,56` —— 客户端发的是**字面量** `"browser"`,
  不是身份。对比同文件 `:82-117` 为发布执行器的 `workerId` 写的整整一页:
  「**必须跨重启稳定**:重启后第一拍要认出自己那些没跑完的任务并收回来,那是这条判据存在的
  全部理由。」——同一个文件里,同一课,隔壁那条道没学。
- `backend/app/api/routes/browser_worker.py:21,64` —— `_HEARTBEATS: dict[str, float]`
  **写进去,全仓没有任何一处读它**(`job_worker.py:23,92` 的那份同样是只写)。
  所以「这个执行器还在吗」这个问题,在浏览器通道上没有答案。
- `backend/app/domain/browser/__init__.py:331-346` —— `reconcile_browser_state()` 只在
  **后端**启动时跑(`main.py:105`)。而这条链上真正会单独重启的是 **Electron**:它一重启,
  内嵌视图全没了,而库里的 `BrowserSession.status` 还是 `open`、`partition` 指着一个不存在的视图,
  **没有任何一处收尾**。下一条动作会在一个刚建出来的空白视图上执行——智能体以为自己还在
  上一个页面上。

唯一兜住的是调用方那侧的超时:`domain/browser/__init__.py:260-267`,等不到就把动作落 `failed`。
那是**兜底**,不是围栏——它只保证「不会永远挂着」,不保证「没有两个人同时在做」。

**为什么看不出来。** 这条通道是**后加的**,而且是照着发布那条的**形状**加的:
路由文件的开头(`browser_worker.py:1-5`)写着「与发布/通用 job worker **同一信任边界**」——
鉴权那一半确实同一条,于是读的人很自然地认为另一半也同。而 ADR-0002 是一份文档,
**没有任何测试在问「新加的 claim/report 通道落契约了吗」**。

**为什么是架构问题。** ADR 说的是「**任何**跨进程执行的任务」,这是一条**封闭的**断言;
一条没落契约的通道存在,这条断言就不再成立,而后面每一个读 ADR 的人(和每一个照着它写
第四条通道的人)都会继续相信它成立。这不是浏览器执行器少了个功能,是**架构决策失去了强制力**。

**建议修法。**
1. `BrowserAction` 加 `claimed_by` / `lease_token` / `lease_expires_at`,`claim` 记身份,
   `report` 校验 token,心跳带 claims 并返回 `renewed`——直接复用 `domain/jobs` 里已经写好的
   `renew_worker_leases`。
2. `reconcile_browser_state` 改成**按租约过期**收尾,而不是按「后端重启」。那样 Electron 单独
   重启也能被收拾,而不需要后端也跟着重启。
3. **一条棘轮**:静态扫 `backend/app/api/routes/*_worker.py`,每条 claim/report 通道要么带
   `lease_token`,要么在一份 `NOT_A_LEASED_CHANNEL` 清单里写明原因——形状和
   `test_agent_workflow_parity.py` 的 `NOT_A_TOOL` 完全一致,那条棘轮已经证明它管用。
   publish 那条正好是第一个合法豁免(ADR 里写了)。

---

### 2.4 【中高】`finish()` 先关掉看门狗,再无限期等 —— 停止一轮会把会话永久卡在「思考中」

**现象。** 用户按「停止」结束一轮;这一轮里模型派发过后台子智能体。界面上那个会话**永远**停在
「思考中」,之后每一条消息都被排进一个再也不会被 drain 的队列。

链条:

1. `backend/app/core/child_process.py:160-166`:

   ```python
   def finish(self, limit=2000) -> str:
       if self._killer is not None:
           self._killer.cancel()     # ← 超时看门狗先关掉
       self._process.wait()          # ← 然后无限期等
   ```

2. `backend/app/ai/sidecar/adapters.py:446-456` —— `_run_pi` 的 `finally` 里
   `live.close()`(关 stdin)之后调 `child.finish()`。
3. `agent-sidecar/src/index.ts:232` —— stdin 关了,`main()` 返回,**但没有 `process.exit()`**。
   Node 要等事件循环空了才退。
4. `agent-sidecar/src/pi.ts:652-663` —— 收尾清算那个循环:

   ```ts
   for (;;) {
     if (agent.signal?.aborted) break;      // ← 中止时直接跳出
     const settled = await subagents.drain();
     ...
   }
   ```

   **正常结束**会 `drain()` 等干净所有后台子智能体(这是对的,注释讲了为什么);
   **被中止**时直接 break,而 `SubagentManager.dispatch`(`subagent.ts:177-180`)里那些
   `void promise.then(...)` 仍然挂着。子智能体是一整个 agent 循环,没有自己的时限。

于是:Node 不退 → `wait()` 不返回 → `_run_turn_thread` 的 `finally`(把会话拨回 idle 的那一段)
**永远执行不到**。而超时看门狗在第 1 步已经被 cancel 了,**没有任何东西能打破它**。

**为什么看不出来。** 这个症状和仓库里已经记录过的一个 bug **一模一样**——
`backend/tests/test_sidecar_backpressure.py` 的开头写着:

> The visible damage was not the hang itself: the session stayed marked running, so every later
> message in that chat was refused with "a turn is already in flight", with no error shown.

那次的成因是 stderr 管道死锁,已经修了并上了测试;**这次是另一条通往同一个症状的路**,
而那条测试测的是 `ChildProcess` 的排空行为,碰不到 `finish()` 里「先 cancel 再 wait」这一对。

**为什么是架构问题。** `ChildProcess` 这个类的存在理由就写在文件开头:
「A deadline only has teeth if something kills the child」。而 `finish()` 是这个类**唯一的收尾出口**,
它自己做的第一件事是**拔掉那颗牙**。这不是某一个调用点的 bug,是这个抽象在它最后一步上
违反了自己的契约——任何一个未来的调用方,只要子进程可能不自己退出,都会踩同一个坑。

**顺带:sidecar 没有 `getppid()` 看门狗。**
`backend/tests/test_workers_do_not_outlive_the_backend.py` 是一条明确的规矩,开头写着现场抓到的
孤儿进程,并给了两条措施:stdin 关闭 + `getppid()` 看门狗。它覆盖的是
`app/ai/runtime/workers/tts.py`。**pi sidecar 一条都没有**(`agent-sidecar/src/` 全文无 `ppid`、
无 `process.exit` 除 fatal 外)。而 sidecar 比那些 worker 更该有:
后端被 SIGKILL / 热重载(开发时每改一次文件)时,它会**继续向供应商发请求(花钱)**,
并继续拿着服务令牌**回写 Mosael 的库**,而没有任何一个进程在读它的输出。

**建议修法。**
1. `finish()` 改成 `wait(timeout=...)`,超时即 `kill()`;或者至少把看门狗的 cancel 挪到
   `wait()` 成功之后。
2. `pi.ts` 中止路径上也要 `drain()`(或给子智能体一个中止信号并等它们真的停下),
   不能把 promise 留在事件循环里。
3. sidecar 加 `getppid()` 看门狗,并把 `test_workers_do_not_outlive_the_backend.py`
   扩成覆盖**所有**常驻/长命子进程,而不只是 Python 那几个。

---

### 2.5 【中】跨进程的时间预算,一条都不在契约里

仓库里已经有专门对付「两个运行时都要认、而谁也不拥有」的东西:
`contracts/shared-constants.json` + `backend/tests/test_shared_constants_parity.py`。
它自己的 description 写得非常准:

> 少数几个「两个运行时都要认、而谁也不拥有」的常量。**不一致时没有任何报错 —— 只是行为悄悄
> 错开**,所以每一条都写清了错开之后用户会看到什么。

里面有 3 条:发布分区前缀、内嵌视图顶栏高度、笔记追加分隔符——**全是视觉和存储**。
而下面这些**完全符合同一条判据**的时间预算,一条都不在里面:

| 一侧 | 另一侧 | 错开之后 |
| --- | --- | --- |
| `TURN_TIMEOUT_SECONDS = 600`(`adapters.py:21`)| `MOSAEL_CARD_WAIT_MS ‖ 590_000`(`tools.ts:136`)| 确认卡的等待超过整轮时限 → 卡还亮着,而那一轮已经被判超时 |
| `PLUGIN_TIMEOUT_SECONDS = 60`(`runtime.py:42`)/ `MCP_TIMEOUT_SECONDS = 60`(`mcp_bridge.py:39`)| `TOOL_CALL_TIMEOUT_MS = 180_000`(`tools.ts:36`)| 顺序对,但没人钉住 |
| `LEASE_TTL_SECONDS = 30` / `ACQUIRE_TIMEOUT_SECONDS = 20`(`provider_auth.py:31,33`)| `ACQUIRE_RETRIES=3` / `ACQUIRE_RETRY_MS=400`(`credentials.ts:21-22`)| 见 §2.2:sidecar 以为自己等了 2.4 秒,实际 80 秒 |
| ADR-0002:租约 60 秒 / 心跳 20 秒 | 外部 worker 的实现(不在本仓库)| 外部 GPU 机器的执行被误判失联 |

`tools.ts:123` 那条注释已经把关系写清楚了(「590s,**压在后端 TURN_TIMEOUT_SECONDS(600s)底下**」)
——**写清楚了,但只写在注释里**。改 Python 那个 600 的人没有任何理由去读 TypeScript 的注释。

**建议修法。** 把这几对搬进 `shared-constants.json`(它已经支持多 runtime 的 implementations 列表),
让 `test_shared_constants_parity.py` 顺带校验「A 必须小于 B」这类关系,而不只是相等。

---

### 2.6 【中】Blender 是应用功能,却借用插件那条 60 秒的通用预算

**现象。** 大一点的场景「发送到 Blender」会以 502「Blender 未响应」失败;重试还是失败;
而 Blender 那边其实**正在好好地跑**。

- `backend/app/domain/plugins/mcp_bridge.py:38-39,109` —— `MCP_TIMEOUT_SECONDS = 60`,
  注释写「连接 + 握手 + 一次调用的总预算。**和进程类插件的 60s 对齐**」。
- `backend/app/domain/blender/bridge.py:163-177` —— `execute()` → `call()` → `tools.invoke`,
  全程走这条预算,没有任何覆盖入口。
- 这 60 秒里要装下:
  1. `uvx --python 3.11 blender-mcp==1.9.1` **起一个子进程**
     (`plugins/examples/blender/mosael.plugin.json`),而 `mcp_bridge.py:20-22` 明写
     **每次调用都重连、不常驻**(理由是「MCP 的握手成本在本地是毫秒级」——对 `npx`/`uvx`
     冷启动来说这句话不成立);
  2. MCP 握手;
  3. `worker.py:40-62` 的 `add_camera`:每个镜头 `ceil(duration*30)` 帧,**每帧**对 4 条
     data path 做 `keyframe_insert`;
  4. `worker.py:88-110` 的 `attach_models`:每个模型一次 `bpy.ops.import_scene.gltf`;
  5. `export_glb` 导出,材质失败还要**再导一遍**(`worker.py:66-90` 的降级梯子)。

**为什么看不出来。** 失败消息是 `BlenderUnavailable`(502)「Blender 未响应,请检查 Add-on 连接」
——它把「我等得不够久」说成了「对面坏了」,于是排查方向直接指向 Add-on。

**更坏的一半:超时之后没人告诉 Blender 停。**
`bridge.send` 的 `finally`(`bridge.py:281-282`)把记录写成 `failed`,`exclusive()`
(`bridge.py:92-101`)的锁**当场释放**,而 Blender 那边的脚本跑在它自己的主线程上、
**还在继续**。用户看到失败就重试 → 第二次 `send` 排在还没跑完的第一次后面 → 又是 60 秒 → 又超时。
`exclusive()` 这把锁只保护了**后端这一侧**的临界区,它以为自己保护的是「那台 Blender」。

**为什么是架构问题。** `MCP_TIMEOUT_SECONDS` 是**传输层**的常量,写的时候对标的是
「一个插件工具调用该跑多久」。而 Blender 互通不是一个插件工具——它是一条产品功能,
只是**借道**插件运行时。借道本身是对的(不该为它再造一条通道),但**借道不应该继承
调用者预算**:这条边界上缺的是「这次调用允许多久」这个参数。

**建议修法。**
1. `mcp_bridge.call_tool` / `tools.invoke` 接一个 `timeout` 参数,Blender 的四个操作
   (send / receive / pull / export)按各自的量级给;默认仍是 60 秒。
2. 超时时把「Blender 可能还在跑,请等它停下再重试」说出来,而不是「Blender 未响应」。
3. `bridge.exclusive` 的锁在超时路径上**不该立刻释放**——它代表的是「那台 Blender 正忙」,
   而超时并没有改变这件事。至少给一个冷却期。

---

### 2.7 【中】`X-Mosael-Client` 在两个客户端上是两个意思

- `backend/app/api/deps/auth.py:19-20` —— 常量就叫 `CLIENT_VERSION_HEADER`,
  注释「客户端**自报版本**的请求头」;`:73-79` 写进 `auth_sessions.client_version`;
  `backend/app/api/routes/admin.py:73` 在管理员表格里按「版本」列展示。
- `frontend/src/api/transport.ts:65` —— 发 `__APP_VERSION__`(如 `1.4.2`)。✅
- `browser-extension/src/mosael/client.ts:83` —— 发**字面量** `"browser-extension"`。❌

**为什么看不出来。** `_VERSION_SHAPE = ^[0-9A-Za-z.+\-]{1,32}$`(`deps/auth.py:24`)
是**专门为了挡住乱塞**加的守卫,而 `browser-extension` 这个串**恰好完全符合版本号的形状**
(字母加连字符,17 个字符)。于是守卫放行,库里存下,管理台照常显示——
一个为「别让这一栏变成任意文本通道」而生的检查,放过了一个不是版本的东西。

**为什么是架构问题。** 这和链条审计 §3 第四处「两个数碰巧相等」是同一类:
**形状校验证明不了语义**。而后果是实的:管理员想知道「谁还在用旧版」,扩展用户那一整批的答案
是一个常量,查不出版本、也升不了级提示。

**建议修法。** 扩展发 `manifest.version`——`browser-extension/scripts/build.mjs:46` 已经把根
`package.json` 的版本盖进 manifest 了,现成可读;客户端**类型**要报的话另开一个头
(`X-Mosael-Client-Kind`),别和版本挤在一格。

---

### 2.8 【中】扩展写死 `Accept-Language: zh-CN`,而它自己有完整的英文界面

- `browser-extension/src/mosael/client.ts:82` —— `"Accept-Language": "zh-CN"`,**无条件**。
- `backend/app/main.py:297` —— 中间件按这个头定整个请求的语言;
  `backend/app/core/i18n.py:8` 写的规则是「请求头 Accept-Language →(将来)用户偏好 → 默认 zh」。
- 而扩展自己:`browser-extension/src/i18n.ts:1` `UiLocale = "zh-CN" | "en"`,
  有 `_locales/en/messages.json`,设置里还有「界面语言 / 跟随浏览器」这一项。

**现象。** 用户把扩展切到英文:按钮、标题、提示全是英文,而**一切由后端产出的字**
(导入任务的进度文案、翻译/转写的失败原因、各种 `detail`)照旧是中文。

**为什么看不出来。** 两侧各自都是对的——扩展的 i18n 测试跑扩展自己的串,后端的 i18n 测试跑后端
自己的串,**没有任何一处同时看这两半**。这正是链条审计 §2 那条规律的翻版:
「给模型的」和「给人的」是同一件事的两个读者;这里是「扩展自己的字」和「后端产出的字」
是同一个人看的同一块面板。

**建议修法。** 把扩展当前的 `UiLocale` 传进 `MosaelClient`,`request()` 里用它填
`Accept-Language`(`zh-CN` / `en`,正好就是 `normalize_locale` 认的形状)。

---

### 2.9 【中低】重启之后没人收尾的两处状态

`backend/app/main.py:99-109` 的启动收尾一共四条(job / agent session / browser / 素材),
`grep "def reconcile"` 全仓 6 个函数。缺的两处:

1. **`PluginInvocation`。** `backend/app/domain/plugins/tools.py:192-196` ——
   调用**之前**先落一行 `status="running"`,然后才跑子进程 / MCP。后端此时被杀(开发
   `--reload` 每改一次文件就是一次),这一行**永远停在 running**。插件页的调用记录
   (`routes/plugins.py:362-372`)会一直把它列出来。没有任何 reconciler 碰它。

2. **Blender 的 `transfer.json`。** `backend/app/domain/blender/bridge.py:268-270` ——
   先写 `status='sending'` 再 `execute`;正常路径靠 `finally`(`:281-282`)改写成 ready/failed。
   进程被杀就写不到。而 `receive()`(`:308`)要求 `status == 'ready'`,`history()`(`:150-161`)
   会把它永远列在历史里。同样没有收尾。

**为什么是架构问题。** 「跨进程执行的东西在重启后要有人收尾」这条规矩在这个仓库里
**已经建立了四次**,每一次都写了很好的理由(`jobs.py:521`、`host.py:767`、
`browser/__init__.py:331`)。第五、第六处漏掉,说明**靠人记得给每个新的「先落 running 再去跑」
补一个 reconciler 是不成立的**——和链条审计 §1.3 得出的结论一字不差。

**建议修法。** 与其再加两个 reconciler,不如找出「所有会在调用前落 running 状态的表」
这个集合,让一条棘轮去问「它有收尾吗」。今天这个集合是 `Job` / `AgentSession` /
`BrowserAction` / `PluginInvocation` 四张表加一份磁盘记录,静态可枚举。

---

### 2.10 【低】协议上的死字段:一侧写、没人读;一侧声明、没人发

| 字段 | 位置 | 状况 |
| --- | --- | --- |
| `RunTurnRequest.history` | `agent-sidecar/src/protocol.ts:20` | 后端从不发,sidecar 从不读。**两侧都没有引用**,纯留档 |
| `_HEARTBEATS`(浏览器)| `browser_worker.py:21,64` | 写进去,全仓零个读者 |
| `_HEARTBEATS`(通用 job)| `job_worker.py:23,92` | 同上(租约续期走的是 `renew_worker_leases`,不读这个字典) |
| `GET /api/publish/worker/status` | `publish_worker.py:113-115` → `worker_online()` | 全仓唯一调用方是 `backend/tests/test_publish_worker.py:129`。前端只在生成的 `schema.d.ts:485` 里有它的类型 |
| `PublishAccount.profile_name` | `publish_worker.py:42,91` + `domain/publish/worker.py:303,314-315` | 后端收、落库、进 `api/schemas/publish.py:66`;而执行器那侧 `electron/publish/publishBackend.ts:145-150` 的 `patchAccount` 签名里**根本没有这个字段**。永远是 NULL |

单看每一条都无害。合起来它们是同一件事:**协议的两侧没有任何一处被强制对齐**,
所以两个方向都会长出死代码——一边加了没人读,一边读了从不出现。§2.1 建议的那条棘轮
(Event 联合 ↔ 消费分支)可以顺手覆盖请求方向。

---

### 2.11 【低】官网的版本耦合:自动校验覆盖两项,漏三项

`docs/RELEASING.md:11-13` 把要同步改的地方列清楚了,并说「官网的测试会逐项核对」。
实际 `website/test/documentation-media.test.mjs` 核对的是:

- `:14` `capture-manifest.json` 的 `documentedVersion` ✅
- `:43` 每篇 `*.mdx` frontmatter 的 `version:` ✅

漏的:

1. **下载页正文里那句话。** `website/content/docs/zh/start/download.mdx:27`
   「**1.4.2 已正式发布**」和 `en/start/download.mdx:26`「Version **1.4.2** is available」——
   同一个版本号在同一个文件里出现了第二次(frontmatter 一次、正文一次),
   **只有 frontmatter 那次被断言**。而且中英两侧的句式不同,一条正则盖不住两边——
   这大概正是它没被检查的原因。链条审计 §3 的判据在这里成立:一个值有两处来源,
   今天相等只是因为改的人细心。
2. **`website/content/releases.json`。** `:2` `fetchedAt: "2026-09-08..."`,最新一条是
   `v1.2.0`,而仓库已经是 1.4.2 —— 快照落后两个小版本,没有任何检查。
   它是 `website/src/lib/releases.ts:20-21` 的**离线回退**:GitHub API 挂了或超时(8 秒),
   官网就会拿两个版本前的列表当「最新发布」端给访客。
3. **它还把自己的缓存钥匙一起锁死了。** `releases.ts:7-11`:

   ```ts
   // A new published-release snapshot gets a fresh fetch-cache key on deployment.
   "User-Agent": `Mosael-Website/${Date.parse(snapshot.fetchedAt)}`,
   ```

   破缓存的钥匙**取自那份没人更新的快照**。快照不更新 → 钥匙不变 → 这段注释说它要避免的那件事
   (「Vercel can keep the previous release list for the full revalidation hour」)照旧发生。
   一个自我抵消的机制。

**建议修法。** 把 `releases.json` 的刷新做成发版流程里的一个脚本步骤
(`gh release list --json` 一条命令),并加一条断言:快照里最新的 tag ≥ `package.json` 的版本。
下载页正文那句话换成从 frontmatter 的 `version` 渲染出来,就不存在第二处了。

---

### 2.12 【低】开发态不构建 sidecar,也不 watch system

`frontend/package.json:15` 的 `electron:dev` 会先构建 `build:preload` / `build:publisher` /
`build:system`,并 watch `publisher` 和 `preload`。而:

- **没有 `build:sidecar`。** `agent-sidecar/dist/` 不入 git(`git ls-files agent-sidecar/dist`
  为空),所以**新克隆的仓库跑 `pnpm dev`,第一句对话必然失败**。
  失败消息本身是好的(`adapters.py:279-281` 指明了「在 agent-sidecar 目录执行 pnpm build」),
  但更要紧的是**日常**:改完 `agent-sidecar/src/*.ts` 不会自动生效,
  于是「改了没反应」这件事会周期性地浪费时间。
- **没有 `watch:system`**(脚本本身就不存在)。改 `electron/system/*.ts` 要重启整个 dev 栈。

对比:`electron/preload-build.test.ts:17-24` 为 preload 钉了一条很好的棘轮——
断言 dev / build:mac / dist:mac / release.yml **四条路径**都跑了 `build:preload`。
同一条棘轮没有覆盖 publisher / system / sidecar。

---

### 2.13 【低】CORS 名单写死 8800,而端口是可配的

`backend/app/main.py:310-311` 把 `http://localhost:8800` / `http://127.0.0.1:8800`
写进 `allow_origins`(注释:「backend serving the built frontend」)。
而端口由 `MOSAEL_BACKEND_PORT` 决定(`electron/main.cjs:51`,冒烟测试就用随机空闲端口)。
后端自己服务前端、又跑在非默认端口时,这条就不成立。
`mcp_server.py:26-33` 恰好为同一个问题留下了很好的记录:

> It was baked in at import time, so every tool 401'd or misrouted the moment the backend ran on
> any port other than 8800 — a packaged build picking a free port, or two instances side by side.

同一个教训,CORS 名单这一处还没学。

---

### 2.14 【低】扩展的消息分发靠兜底分支,加一种就会被悄悄当成 SEEK

`browser-extension/src/content.ts:138-152` —— `handle()` 显式判了 5 种,
第 6 种(`SEEK`)是**落到末尾的兜底**:

```ts
const video = videoElement();
video.currentTime = Math.max(0, Math.min(..., message.seconds));
```

今天是对的。但 `ContentRequest`(`shared/protocol.ts:11-17`)里再加一种类型时,
它**不会报错**,会被当成一次 `seconds === undefined` 的 SEEK(`Math.min(duration, undefined)`
= NaN → 赋值抛错 → 返回 `{ok:false}`,错误文案指向视频而不是指向分发)。
仓库里别处的分发都是显式的 + 一条 `log("unknown message type")`(`index.ts:225-227`),
只有这一处不是。

---

## 3. 没有发现问题的地方(也是结论)

沿链条走过、确认处处成立的:

- **「跑在别人进程里的代码」这条边界是干净的。**
  `backend/app/domain/blender/scripts.py:15-20` —— `worker.py` 的源码整份读出来拼在前面,
  但**参数从不拼进 Python 语句**:`json.loads(repr(json.dumps(payload)))`,
  文件头一句话就是「Paths and parameters travel as JSON data, never as Python source」。
  `worker.py` 的 import 只有 `bpy / json / math / pathlib / mathutils`——**一个主应用模块都没有**。
  而且它还是可测的:`backend/tests/test_blender_worker_export.py` 用假 `bpy` 单测了导出的降级梯子。
  唯一的小瑕疵:`bridge.py:129-133` 那段「worker.py 跑在别人的 Blender 里,换掉它的入参形状意味着
  新旧应用和新旧 Add-on 的组合都要考虑」的理由**其实不成立**——`worker.py` 每次调用都由后端
  现发过去,不存在「旧的 worker.py」。真正跨版本的只有 `execute_blender_code` 的工具名与
  `code` / `user_prompt` 两个参数名,而它已经被 manifest 里的 `blender-mcp==1.9.1` 钉住了。
  结论不变(保持线上格式不变是好事),但理由该改,否则下次会为一个不存在的约束多付一次代价。

- **发布执行器的多执行器正确性。** `electron/publish/publishBackend.ts:82-117` 的身份、
  `domain/publish/worker.py:58-89` 的两条回收判据(「只有认领者能说」+「全局兜底」)、
  `:114-124` 的「排除**任何人**正在跑的账号」,加上 `backend/tests/test_two_publish_workers.py`
  逐条钉住。这一处是本次审计里做得最完整的。

- **sidecar 的工具面是单一来源。** `agent-sidecar/src/tools.ts:1-19` ——
  工具全部从 `GET /api/agent/tools`(由 `mcp_server.py` 这份唯一注册表导出)生成,
  「There is no hand-written second list any more」,并记着上次漂移的代价(少了 19 个工具)。
  确认卡按 `confirmation: true` 标记走通用包装,不按名字特判。

- **`mcp_server.py` 的双身份。** `:26-52` —— `api_base` 与 token 都是 ContextVar,
  理由写得很清楚:它既是独立 stdio 进程,也被后端 import 进程内服务 sidecar,
  模块级常量会把一个人的令牌泄给另一个人。这正是本次要找的「卫星进程悄悄破坏单进程假设」,
  而它**已经被发现并修好了**。

- **凭据租约的设计本身。** `provider_auth.py:1-16` 把「为什么是租约而不是乐观并发」
  和「为什么放进程内存」讲透了:「后端是单进程 uvicorn,sidecar 才是多进程,而它们都经由后端 ——
  内存锁就是**这套进程拓扑下**真正的临界区」。判断是对的(全仓只有 `run_backend.py:18` /
  `main.cjs:217` 两处起 uvicorn,都没有 `--workers`)。问题只在收尾那一环(§2.2),不在设计。
  **唯一的缺口**:这条拓扑前提写在 docstring 里,**没有任何一处守着它**——
  哪天有人加了 `--workers 2`,失效的表现恰好就是它要防的那件事,且不会有任何报错。
  一个启动期的「数据目录里只有我一个后端」pid 锁能同时兜住这个和「两个后端共用一份数据」。

- **Electron 的单实例锁。** `electron/main.cjs:177-200` ——
  注释点名了没有它的后果:「两个发布 worker 抢同一批任务、两套内嵌浏览器争同一个登录分区,
  而后端因为 ensureBackend 见端口健康就复用,反而看起来"没问题"——很难查」。
  `app.setName("Mosael")` 在 ready 之前调(`:44`),开发态和打包版共用同一个 userData,
  所以这把锁**确实**同时盖住了两者。

- **冒烟测试的隔离是完整的。** 唯一故意绕开单实例锁的地方(`main.cjs:62-69`)配了三重隔离:
  userData 在 mkdtemp 目录、`MOSAEL_DATA_DIR` 独立、端口取空闲口
  (`test/bundle.smoke.mjs:52-68`)。三者齐了才安全,而**绕锁那一半在 `main.cjs`、
  另外两半在测试脚本里**——今天对,但这个关系没有任何东西钉住。值一条注释。

- **分区命名没有第二份。** 发布账号的 `persist:mosael-<id>` 前缀由
  `contracts/shared-constants.json` 钉住两侧;而浏览器会话的 `persist:rpa-*` / `ephemeral-*`
  **只在后端算**(`domain/browser/__init__.py:49-52`),经 claim 负载原样下发
  (`:293`),Electron 拿到就用(`browserWorker.ts:79`)——没有第二处拼串,做得对。

- **插件的进程隔离。** `domain/plugins/runtime.py:17-24,115-123` ——
  子进程只拿 PATH/HOME/LANG + 它自己声明的凭据,拿不到应用的供应商密钥、数据库、API 令牌;
  `output` / `state` 分成两样(刷新出来的 token 不会顺着工具结果流进对话记录);
  文件产出走暂存目录并在 `_collect_artifact` 里换成 `asset_id`,
  「换掉而不是两个都留」的理由也写了。

- **worker key 每次重读。** `browserBackend.ts:10-22` / `publishBackend.ts:33-48` ——
  「后端重启会换密钥,所以每次都重读:缓存下来会在重启后静默失效,而失败是 401 不是超时,
  很难查」。所以**后端单独重启时,两个执行器都能自己恢复**,不需要重启 Electron。

- **扩展版本号是自动的。** `browser-extension/scripts/build.mjs:46` ——
  `manifest.version = packageJson.version`(根包)。源码里的 `manifest.json:6` 还写着 `0.1.0`,
  只影响「直接加载未构建目录」这一种开发姿势,不影响产物。

- **打包 / 开发的路径差异都写了理由。** `file://` 的 Origin 是 `null`,CORS 名单里明确列了
  (`main.py:303`);打包版用 Electron 二进制当 node 跑 sidecar 并加 `ELECTRON_RUN_AS_NODE=1`,
  且**只在显式指定时加**(`adapters.py:352-355`);PyInstaller 冻结后端建不了 venv,
  所以随包分发独立解释器(`main.cjs:286-296`);Windows 控制台窗口用 `windowsHide` 压掉
  而不是改成 `--noconsole`(`main.cjs:301-309`)。这几处是本次读到的最舒服的代码。

---

## 4. 给下一次的建议

1. **把「协议的每一个成员都有消费者」做成一条棘轮。** 本次最贵的两条(§2.1、§2.2)都是
   *一侧产出的信息在另一侧没有落点*,而且两次都是**专门为某种情况造的回执**被丢掉。
   静态对一遍 `protocol.ts` 的 `Event` 联合 ↔ `adapters.py` / `login.py` 的分支,
   是链条审计建议的那三条检查在进程边界上的自然延伸。写的时候记得先**故意删掉一个分支
   验证它会红**——链条审计 §1.3 的第一版就是因为没验而保持了沉默。

2. **ADR 要有牙。** ADR-0002 说的是「**任何**跨进程执行的任务」,而第三条通道整条没落
   (§2.3)。`NOT_A_TOOL` 那种「要么符合,要么在清单里写明为什么」的形状在这个仓库里
   已经证明有效,把它套到 claim/report 通道上,成本很低。

3. **时间预算是跨运行时常量,该进契约。** `contracts/shared-constants.json` 的机制已经造好了,
   里面却只有视觉和存储那三条。时间预算完全符合它自己写的判据(「不一致时没有任何报错 ——
   只是行为悄悄错开」),而且 §2.2 已经付过一次学费。

4. **「学过的一课」要主动往隔壁推。** 本次三处同形:
   发布执行器的身份围栏 → 浏览器执行器没有;
   Python worker 的 `getppid()` 看门狗 → sidecar 没有;
   四处 reconcile → 插件调用和 Blender 传输没有。
   每一处的知识都已经在仓库里,而且都写了很好的注释——**缺的是「谁还该有这个」这个问句**。
   建议在这三处的注释里各补一句「同形的还有谁」,让下一个读的人顺手看见。

---

## 附:关键文件路径

**后端 ↔ sidecar**
- `/Users/kinda/Developer/Mosael/backend/app/ai/sidecar/adapters.py`
- `/Users/kinda/Developer/Mosael/agent-sidecar/src/protocol.ts`
- `/Users/kinda/Developer/Mosael/agent-sidecar/src/index.ts`
- `/Users/kinda/Developer/Mosael/agent-sidecar/src/pi.ts`
- `/Users/kinda/Developer/Mosael/agent-sidecar/src/tools.ts`
- `/Users/kinda/Developer/Mosael/agent-sidecar/src/credentials.ts`
- `/Users/kinda/Developer/Mosael/agent-sidecar/src/subagent.ts`
- `/Users/kinda/Developer/Mosael/backend/app/domain/agent/host.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/agent/login.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/provider_auth.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/routes/agent_credentials.py`
- `/Users/kinda/Developer/Mosael/backend/app/core/child_process.py`

**worker 通道**
- `/Users/kinda/Developer/Mosael/docs/adr/0002-claim-report-worker-protocol.md`
- `/Users/kinda/Developer/Mosael/backend/app/api/routes/job_worker.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/routes/publish_worker.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/routes/browser_worker.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/publish/worker.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/browser/__init__.py`
- `/Users/kinda/Developer/Mosael/electron/publish/publishBackend.ts`
- `/Users/kinda/Developer/Mosael/electron/publish/browserBackend.ts`
- `/Users/kinda/Developer/Mosael/electron/publish/browserWorker.ts`

**Electron 壳**
- `/Users/kinda/Developer/Mosael/electron/main.cjs`
- `/Users/kinda/Developer/Mosael/electron/publish/accountViews.ts`
- `/Users/kinda/Developer/Mosael/electron/preload-build.test.ts`
- `/Users/kinda/Developer/Mosael/test/bundle.smoke.mjs`
- `/Users/kinda/Developer/Mosael/frontend/package.json`(`electron:dev`)

**插件与 Blender**
- `/Users/kinda/Developer/Mosael/backend/app/domain/plugins/runtime.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/plugins/mcp_bridge.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/plugins/tools.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/blender/bridge.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/blender/scripts.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/blender/worker.py`
- `/Users/kinda/Developer/Mosael/plugins/examples/blender/mosael.plugin.json`

**扩展与对外面**
- `/Users/kinda/Developer/Mosael/browser-extension/src/mosael/client.ts`
- `/Users/kinda/Developer/Mosael/browser-extension/src/shared/protocol.ts`
- `/Users/kinda/Developer/Mosael/browser-extension/src/content.ts`
- `/Users/kinda/Developer/Mosael/browser-extension/scripts/build.mjs`
- `/Users/kinda/Developer/Mosael/backend/mcp_server.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/deps/auth.py`

**契约与官网**
- `/Users/kinda/Developer/Mosael/contracts/shared-constants.json`
- `/Users/kinda/Developer/Mosael/backend/tests/test_shared_constants_parity.py`
- `/Users/kinda/Developer/Mosael/website/src/lib/releases.ts`
- `/Users/kinda/Developer/Mosael/website/content/releases.json`
- `/Users/kinda/Developer/Mosael/website/test/documentation-media.test.mjs`
- `/Users/kinda/Developer/Mosael/website/content/docs/zh/start/download.mdx`
- `/Users/kinda/Developer/Mosael/docs/RELEASING.md`
