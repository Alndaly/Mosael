# 进程内状态清单

后端是**单进程 uvicorn**(`backend/run_backend.py` 直接 `uvicorn.run(app, …)`,没有 `workers=`)。
很多地方就建立在这个前提上,而那些地方的说明此前散在各自文件的注释里 —— 单看任何一处都不
显眼,合起来才看得出"能不能起第二个后端进程"这个问题的答案。

这份清单回答两件事:

1. **进程一重启,什么会丢?** 丢了之后是自动重建,还是要用户重新做一遍。
2. **起第二个后端进程会怎样?** 这是把后端搬上服务器、或者想横向扩一份时真正的拦路虎 ——
   数据库换不换 Postgres 不是关键,下面第一节才是。

> 清单由 `backend/tests/test_process_state_inventory.py` 看着(棘轮)。新加的模块级可变
> 状态必须写进这里并说明属于哪一类,否则那条测试会失败 —— 手写清单会腐烂,而这一份腐烂的
> 后果是"以为可以起两个进程"。

---

## 一、单进程是**正确性**前提

这几处不是"多进程会慢一点",是**多进程就是错的**。

| 位置 | 是什么 | 起第二个进程会怎样 |
| --- | --- | --- |
| `app/domain/provider_auth.py:_leases` | 刷新供应商令牌的租约(独占权 + TTL) | 两个进程各锁各的,于是两边同时刷同一份令牌。冲突在**写回时**才发现,而那时两次网络请求都已经打出去了 —— 后写的赢,先写的那份 refresh_token 被对方作废。sidecar 本来就是多进程,它们**都经由后端**,所以后端内存锁正是这套拓扑下真正的临界区。 |
| `app/core/worker_key.py:_key` | 执行器通道的密钥,每进程随机 | 执行器只认得它拿到的那一份,发到另一个进程上全是 401 —— 而发布、浏览器自动化、external 任务会各自看起来单独坏了。**已有出路**:配 `MOSAEL_WORKER_KEY` 就固定成同一个(见 `test_worker_key_can_cross_a_network.py`)。 |
| `app/api/routes/oauth.py:_pending` | 登录 OAuth 的待完成流(state / PKCE verifier,TTL 600s) | 授权回调**必须落回发起它的那个进程**。落到另一个上就是"state 不匹配",而用户看到的是一句登录失败,重试还是失败(负载均衡多半又把他分到另一边)。 |
| `app/domain/publish/worker.py` 的认领(心跳在 `app/domain/publish/worker.py:_last_heartbeat`) | `claim_next_pending` 靠同事务内 select→update 保证原子 | 那句原子性写着「单进程 SQLite 后端 + 单个 worker」。多个认领者会重复领同一条待发布任务 —— 同一个视频发两遍。 |
| `app/domain/agent/login.py:_sessions` | 平台登录会话(带子进程句柄) | 轮询进度的请求打到另一个进程上就查无此会话,而浏览器窗口正开在第一个进程那边。 |

## 二、单进程是**功能在场**的前提

这几处不会算错,但**功能只存在于持有它的那个进程里**。请求分到另一个进程上就是"这个功能不在"。

| 位置 | 是什么 | 重启 / 第二个进程 |
| --- | --- | --- |
| `app/ai/runtime/tts_daemon.py:_POOL` | 常驻 TTS 工作进程池 | 重启后第一次合成要重新加载模型(十几秒到几分钟)。第二个后端进程会**再养一份**,显存翻倍。 |
| `app/ai/runtime/asr_daemon.py:_POOL` | 常驻 ASR 工作进程池 | 同上。语音对话的首句延迟就取决于这个池热没热。 |
| `app/domain/agent/host.py:_streams` | 正在跑的那一轮的 SSE 流 | 后端一重启线程即死,`finally` 执行不到,会话永远卡在「思考中」—— 所以有 `reconcile_orphaned_agent_sessions()` 在启动时统一拨回,并把那一轮留下的确认卡一并作废(否则那张卡还能被点,而它是**当场执行工具**的)。 |
| `app/domain/jobs.py:_CHILDREN` | 任务的子进程句柄(ffmpeg / ASR / TTS) | 没有它,取消只是翻了个数据库字段:ffmpeg 跑完整段、烧掉用户明确要求停下的 CPU,然后把取消覆盖成「成功」。重启后旧句柄没了,那些孤儿由 `reconcile_orphaned_jobs` 收拾。 |
| `app/api/routes/job_worker.py:_HEARTBEATS`<br>`app/api/routes/browser_worker.py:_HEARTBEATS` | 执行器在线状态 | 有意做成进程内 —— worker 的在线本就随后端进程存在。但多进程下"在线"会随请求落到哪个进程而闪烁。 |
| `app/integrations/feishu/service.py:_processes` | 每个机器人一个子进程 | 独立进程是 lark SDK 的硬约束(它的 ws 客户端共享模块级事件循环)。第二个后端会**再拉一份**,同一条消息被处理两次。 |
| `app/ai/sidecar/adapters.py:_LIVE` | 正在跑的 sidecar 轮次 | 同 `_streams`。 |
| `app/workers/scheduler.py:_stop_event` | 定时任务线程的停止信号 | 每个进程一个调度线程 —— 多进程下同一条定时任务会被触发多次。 |

## 三、启动时装配的配置快照

它们把库里的设置装进**本进程**,改完即时生效。不是迁移,是启动装配;第二个进程读同一个库,
所以这一类多进程是安全的,只是"改了设置"要每个进程各自装配一次。

- `app/core/http_retry.py:_max_retries` — 出站重试次数。调用点散在十几个适配器里,不少拿不到 db 会话。
- `app/core/logging.py:_configured` — 日志装配一次的闸。
- `app/ai/runtime/config.py:_cached`、`app/ai/runtime/config.py:_source` — TTS 运行时配置及其来源。
- `app/ai/sidecar/adapters.py:_proxy_source` — 出站代理来源。
- 代理环境变量本身写在 `app/domain/network.py`(改的是**本进程**的 env,而不是给十几处 `httpx.Client` 逐个传 `proxy=`)。

## 四、纯缓存与去重

重启即重建,多进程下各算各的 —— 代价只是多算一遍。**这一类不构成部署约束**,列在这里是为了
让上面三类的边界清楚:不是所有模块级字典都是问题。

- `app/ai/model_catalog.py:_cache`、`app/ai/model_catalog.py:_refreshing` — 供应商模型清单,带 TTL。
- `app/ai/runtime/remote_size.py:_cache`、`app/ai/runtime/remote_size.py:_refreshing` — 远端权重体积。
- 引擎就绪探测(两套一模一样的形状):`app/ai/runtime/tts_models.py:_PROBED`、
  `app/ai/runtime/tts_models.py:_PROBING`、`app/ai/runtime/tts_models.py:_PROBE_GENERATION`、
  `app/ai/runtime/tts_models.py:_store`;以及 `app/ai/runtime/asr_models.py:_PROBED`、
  `app/ai/runtime/asr_models.py:_PROBING`、`app/ai/runtime/asr_models.py:_PROBE_GENERATION`、
  `app/ai/runtime/asr_models.py:_store`。
- `app/ai/runtime/f5_models.py:_live`、`app/ai/runtime/workers/tts.py:_LOADED` — 已加载的模型。
- `app/api/routes/sequences.py:_SEQUENCE_JSON` — 序列 JSON 按 revision 缓存。每序列一条,不随流量增长。
- `app/api/routes/settings/provider_profiles.py:_refresh_failed_at` — 刷新失败冷却。重启后是空的,于是第一次会说「已授权」哪怕它刷不动 —— **这个方向是有意选的**:说成"还不知道"只会晚一次发现,说成"需重新授权"是在没坏的时候喊坏。
- `app/integrations/feishu/service.py:_token_cache`(租户令牌)、
  `app/integrations/feishu/service.py:_seen`(消息去重)、
  `app/integrations/feishu/service.py:_onboard_state`(引导流程)、`app/domain/poem.py:_token`。

## 五、导入期注册表(不是"状态")

模块导入时填一次,之后只读。每个进程都一样,不构成任何约束。

- `app/domain/jobs.py:_EXECUTION_MODES`(每个 kind 在进程内跑还是交给外部执行器)、
  `app/domain/jobs.py:_RECEIPT_DELIVERERS`
- `app/domain/sequences/undo/__init__.py:_REGISTRY`
- `app/domain/workflows/executors/__init__.py:_REGISTRY`、
  `app/domain/workflows/executors/__init__.py:_PREFIX_REGISTRY`
- `app/domain/plugins/media_bridge.py:_sink`、`app/domain/plugins/media_bridge.py:_source`

---

## 想起第二个后端进程的话

按上面第一节逐条处理,而不是先去换数据库:

1. **worker_key** —— 已经能配了(`MOSAEL_WORKER_KEY`),这条最省事。
2. **oauth `_pending`** —— 挪进数据库(它本来就有 TTL,是天然的表)。
3. **provider_auth 租约** —— 挪成数据库里的租约行(TTL + 持有者),语义不变。
4. **publish 认领** —— 需要真正的行锁(`SELECT … FOR UPDATE SKIP LOCKED`),**这一条才是换 Postgres 的理由**,而不是"SQLite 不够大"。
5. **agent/login `_sessions`、feishu `_processes`、scheduler** —— 这些绑着子进程,天然属于"某一个进程"。正确做法是把它们从 web 进程里搬出去,成为单独的、只有一份的常驻服务,而不是让每个 web 进程都养一份。
