# Open Studio

本地优先的 AI 视频创作工作室(Electron 桌面应用)。这份文档定义架构讨论用的统一语言——
子系统文档见 docs/,决策记录见 docs/adr/。

## Language

### 命名

**Open Studio**:
产品名,也是仓库名。一切对外可见处一律用它——GitHub(`Alndaly/OpenStudio`,大小写敏感:
更新检查直连 GitHub API,写错大小写会吃 301,而检查失败是静默的)、App 名、文档站、README、
数据目录 `~/.open-studio/` 与主库 `open-studio.db`、打包二进制 `open-studio-backend`。

| | 规范名 |
| --- | --- |
| 环境变量前缀 | `OPEN_STUDIO_`(`config.ENV_PREFIX`) |
| preload 桥 | `window.openStudioDesktop` |
| 深链事件通道 | `openstudio:open-*` |
| 浏览器分区前缀 | `openstudio` |
| MCP 环境变量 | `OPEN_STUDIO_API` / `OPEN_STUDIO_TOKEN` |

### 进程与协议

**事实源(后端)**:
FastAPI 后端(127.0.0.1:8800),持有全部持久状态;前端、发布执行器、sidecar 都只是它的客户端。
_Avoid_: 服务端(团队模式语境除外)、server

**卫星进程**:
由壳或后端拉起、经显式协议与后端通信的独立进程(发布执行器 / agent sidecar / ASR·TTS 解释器 / ffmpeg / 插件 / 飞书 bot)。
_Avoid_: 微服务

**worker 协议**:
拉取式任务执行契约:claim(CAS 原子认领)→ report(富状态回报)→ heartbeat;后端从不反向连接 worker。
_Avoid_: 推送、回调、消息队列

**执行模式**:
job kind 的属性,决定由谁执行:`in_process`(守护线程,进程死任务亡)或 `external`(worker 协议驱动,跨重启存活)。声明权在各领域(`register_external_kind`),读取权在任务总线。

### 任务总线

**任务总线**:
`jobs` + `task_events` 两张表加 `app/domain/jobs.py` 的接口;一切耗时操作收敛为 job。
_Avoid_: 队列服务、调度中心

**派发(dispatch)**:
`dispatch_job`:领域描述「怎么跑」,总线决定「由谁跑」。

**准入槽**:
按 kind 的信号量并发上限(render 2 / ASR 1 / TTS 1 / 生成 4),防单机 OOM;external 模式下等价于 worker 侧并发容量。

### 工作流

**节点注册表(NODE_TYPES)**:
节点的元数据接缝:驱动校验、画布 UI、智能体提示。

**执行器注册表(executors/)**:
节点的行为接缝:每种节点类型一个执行器适配器,签名 `handler(db, workflow, config) -> dict`。与 NODE_TYPES 一一对应(锁步测试钉死)。

**引擎(engine.py)**:
纯 DAG 调度器:拓扑、并行、条件路由、取消边界、事件与进度。对具体领域零 import。

**主机权限节点(PRIVILEGED_NODE_TYPES)**:
能在后端主机上跑任意代码的节点(今天只有 `code`)。它的写入权限是**主机权限而非内容权限**:
进程隔离 + 超时 + 输出上限**不是沙箱**。所有落库入口(create / import / patch / 确认卡审批)
额外要 `ensure_instance_admin`,且扫描必须**递归进 `config["body"]`**——否则「折叠为子图」
一步就绕过。新增同类节点(shell/exec/eval…)必须登记进这个集合。
_Avoid_: 把它当普通节点按 `edit` 权限放行、只扫顶层 nodes

### 剪辑

**一次手势 = 一条操作**:
撤销的粒度必须与用户感知的动作对齐。多选后的删除/移动/改文案等批量动作,一律做成**一个**
`SequenceOperation`(`*_batch` 系列),而不是循环调用单片段操作——后者会让删 5 段要按 5 次 ⌘Z。
批量操作**先全量校验再落库**:一个非法就整批不落,不留下改了一半的时间线。
_Avoid_: 前端 `for (const id of ids) await 单个操作(...)`;把顺序依赖(如波纹删除要从后往前)留在前端

### 渲染

**场景模型**:
「t 时刻画面上有哪些层、按什么 z 序、谁是 base」。有且只有两份实现——预览
(`playback/sceneModel.ts`)与导出(`app/media/scene.py`)——因为预览要本地同步跑到 60fps 且
渲染未提交的草稿,导出要无头可外派。两者由**契约语料**钉死。
_Avoid_: 说「合并成一个渲染器」(见 [ADR-0004](docs/adr/0004-preview-export-parity-by-contract.md))

**契约语料**:
`contracts/*.json`:语言中立、由多侧测试各跑一遍的可执行规约。改语义**先改语料**,看两侧一起红,
再改实现——反过来做就把语料降级成实现的复读机。
_Avoid_: 当成文档、当成 fixture、先改实现后补语料

**权威侧**:
某项语义以哪一侧为准。可见层/z 序/base **两侧必须逐字一致**;调色**ffmpeg 权威、预览近似**
(canvas 做不了 `curves`/`lut3d`,让它当权威等于把导出拉平到预览的保真度);文字**两侧同源 CSS**。
_Avoid_: 把「预览和导出不一样」一概当 bug——调色的不一样是设计

### 数据

**数据归属**:
每张表归一个领域模块所有,行创建只发生在拥有方(`app/domain/ownership.py`);跨领域需要新行时调用拥有方的领域函数。

**归属棘轮**:
`tests/test_data_ownership_ratchet.py`:存量越界冻结在 allowlist 只减不增;新增越界与修复后未删条目都会失败。

**表结构演进**:
运行时**不跑迁移框架**。`init_db()` = `create_all`(新装机建全表)+ 一串 `_migrate_*`(已装机补差)。
改表 = 改 `models.py` **且** 加一个 `_migrate_*`,少一步就是「新装机好、老用户崩」。
_Avoid_: 说「加个 Alembic 迁移」——那套已随漂移移除

**迁移退休判据**:
一个 `_migrate_*` 的引入时间**早于最早仍支持的 Release** 时即可删除(它只服务从未公开的 dev 库)。
晚于的必须留着——那是真实用户的升级路径。删错=用户打开看到空工作室。
_Avoid_: 凭「看起来很旧」删迁移;凭本机没有该目录就断定没人有

**用量台账**:
`provider_usage_events` + `provider_pricing_rules` 两张表加 `app/domain/usage.py` 的接口;记录 AI 对话、图片/视频/音频生成、嵌入等供应商调用的可审计事实。调用方只上报 provider/model/capability/operation/units/raw_usage/duration,价格估算与幂等写入收敛在台账模块。
_Avoid_: 把费用写进 `task_events`、把供应商账单逻辑散落在各 adapter、用 toast 文案替代可查询的成本事实

### 智能体

**工具注册表**:
`mcp_server.py` 是唯一工具定义处;`/api/agent/tools` manifest 派生它,所有 runtime(pi sidecar / MCP 客户端 / 飞书)从 manifest 生成工具,不再手写第二份。

**确认门控**:
变更工具的属性(manifest 的 `confirmation: true`):调用只创建待确认卡,用户批准后才执行;sidecar 对此类工具统一阻塞轮询。
_Avoid_: 按工具名硬编码确认逻辑

**上下文预算**:
一次对话还能塞多少 token,由**模型的上下文窗口**决定(模型行的 `context_window` → 目录 → 保守回退 32000)。
估算锚定在**最后一条带 usage 的助手消息**(供应商回的真实 input+output),此后的新消息按
`CHARS_PER_TOKEN = 3.5` 估。sidecar(`compaction.ts`)与后端(`domain/context_meter.py`)各有一份实现,
**回退值与估算规则必须逐字一致**——不一致时用户看到的水位和真正触发压缩的时机会对不上。
_Avoid_: 按消息条数判断"聊得够久了";把 `maxTokens` 当上下文窗口

**上下文整理(compaction)**:
超过窗口的 `COMPACT_RATIO = 0.8` 时,把早期对话交给模型摘要、保留最近 `KEEP_RECENT = 8` 条。
切点**必须回退到一条 user 消息**,否则会留下没有对应 tool_call 的孤儿 tool_result。摘要失败时
降级为截断,但**仍然如实回报**发生了什么——静默降级会让用户以为上下文还在。发生在**两轮之间**,
不在 `transformContext`(那个在工具循环里每次 LLM 调用都跑)。
_Avoid_: 压缩=丢最老的 N 条;失败了不说

**思考档位**:
会话级设置(off / low / medium / high),决定**我们是否主动向供应商要**思考内容。
「关闭」不等于模型不思考——k3、DeepSeek reasoner 这类模型无论如何都会回思考,照常解析、照常显示。
与模型设置里的「推理模型」是两件事:后者只决定拿到思考内容后**怎么解析**。
_Avoid_: 把 off 理解成"屏蔽思考显示"

### 供应商

**连接(ProviderProfile)**:
一个端点 + 一份凭据 + 一种鉴权方式(api_key / oauth)。**不是模型**——它下面可以有任意多个模型。
_Avoid_: `profile.default_model`(已删,是"一档案一模型"时代的字段);拿模型名当档案名建一堆档案

**模型(ProviderModel)**:
连接下的一行,是能力与运行时参数的**唯一挂载点**:`capability_ids`(留空回落 vendor 预设)、
`context_window`、`reasoning` / `vision` / `reasoning_effort` / `developer_role`。
拥有方是 `app/domain/provider_models.py`,建行只经 `upsert`。
运行时参数**只下发用户显式设过的键**——`None` 与"显式设成 false"在下游行为不同。
_Avoid_: 把能力挂在连接上(同一端点常常既有对话模型也有生图模型)

**能力默认(ProviderDefault)**:
每种能力(chat / image / video / tts / podcast / embedding)指向**一行模型**,不是一个档案。
指向失效时回落"该能力下第一个可用模型",而不是报未配置。

**vendor 预设**:
`app/domain/providers.py` 声明某个 vendor 支持哪些能力、设置页要收集哪些 `fields`、支持哪些鉴权方式。
前端只渲染后端声明的 `fields`,不硬编码通用凭据模型。它是**兜底**:模型行没写能力时按它回落。
_Avoid_: 仅凭 vendor 文案推断能力

**订阅额度**:
`domain/provider_quota.py`,六家(anthropic / codex / openrouter / kimi / xai / copilot)各一个解析器。
**只在用户点击时查**——这些端点都不是官方承诺的公开接口,定时轮询既容易撞限流,也会在对方改接口后
变成后台里一直失败的任务。查不到不抛 5xx:"这家不支持"和"这次没查成"是两种正常结果。

**AI 调用重试**:
`domain/ai_retry.RetryingClient`(httpx.Client 子类,在 `send()` 里对 429/5xx/RequestError 指数退避重试)。
它是**所有** AI 出站调用的统一入口(15 个模块),不是对话专属——生图、生视频、TTS、向量化同样会遇到限流。
_Avoid_: 在某一条调用路径里手写重试循环

## Relationships

- 一个 **job** 属于一种 kind;kind 有且只有一个**执行模式**
- **引擎**只认**执行器注册表**;**执行器注册表**与**节点注册表**一一对应
- **卫星进程**经 **worker 协议**(external 类)或 stdio/subprocess(共生类)与**事实源**通信
- 每张表有且只有一个**数据归属**领域;**归属棘轮**守护它
- **用量台账**从任务总线、智能体、生成执行器接收事实,不反向决定业务是否成功
- 一个**连接**有 0..n 个**模型**;**能力默认**指向一行**模型**;**vendor 预设**只在模型没声明能力时兜底
- 能力的实际 HTTP/SDK 差异由该能力自己的 Adapter 接缝负责,不由**连接**或**模型**表达
- **上下文预算**由所选**模型**的窗口决定;超过阈值触发**上下文整理**;**思考档位**是会话属性,与模型无关

## Example dialogue

> **Dev:**「我要加一种『视频翻译』节点,改哪里?」
> **架构:**「**节点注册表**加元数据,**执行器注册表**加一个执行器文件——**引擎**不动。如果它耗时,内部建 job 走**任务总线**;将来想让翻译跑在 GPU 机器上,把它的 kind 注册成 external **执行模式**就行,worker 经 **worker 协议**认领,领域代码不改。」

## Flagged ambiguities

- 「worker」曾同时指发布执行器与任意后台线程——现约定:**worker** 专指经 worker 协议认领任务的外部进程;进程内的叫守护线程/执行器。
- 「注册表」需带限定词:**节点注册表**(元数据)/ **执行器注册表**(行为)/ **工具注册表**(智能体)/ 平台注册表(发布)。
- 「供应商」在 UI 里指**连接**(设置页那一行),在讨论 vendor 支持什么时指**vendor 预设**。谈架构时用**连接** / **模型** / **vendor 预设**三个词,别用「档案」——它此前既指供应商档案又指浏览器档案(`BrowserProfile`),而后者才是「档案」的正主。
