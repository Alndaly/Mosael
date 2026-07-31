# 架构

## 三段自举:App 启动时发生了什么

`open "Open Studio.app"` 一条命令背后是三件事,顺序由 `electron/main.cjs` 编排:

1. **拉起后端** — spawn 打包的 `open-studio-backend` 二进制(开发模式则是 `uvicorn`),轮询 `/api/health` 等它就绪(30s 超时)。
   若 8800 已有健康后端(如 dev server),**复用它**,不再起新进程(`ensureBackend()` 里的 `isHealthy()` 检查)。
2. **开窗加载前端** — 打包版 `loadFile(frontend/dist/index.html)`,开发版 `loadURL(localhost:5173)`。
   hash 路由(`#/editor?p=<id>`)——因为 `file://` 下 path 路由不可用。
3. **启动发布执行器** — `publish.bundle.cjs` 里的 worker 开始轮询后端认领发布任务(见 [PUBLISHING.md](PUBLISHING.md))。

后端是**唯一事实源**。前端和发布执行器都只是它的客户端——这也是为什么发布执行器能在 App 重启后接着干活。

## 后端:领域内核 + 薄路由

`backend/app/domain/` 是真正的内核,`api/routes/` 只做 HTTP 转译与鉴权。

| 领域 | 职责 |
| --- | --- |
| `sequences/` | 剪辑内核:insert/move/trim/delete/split/cut-range 等操作,每次操作校验不变量并落 `sequence_operations` + `sequence_revisions`(撤销/重做的基础) |
| `render.py` | 序列 → RenderPlan(纯函数)→ ffmpeg 执行导出 |
| `transcripts/` | 逐字稿:ASR 导入、token 级编辑、投影到时间线(删句 = 剪源区间) |
| `workflows/` | DAG 工作流:节点注册表(元数据)+ `executors/` 执行器注册表(行为)+ 统一并行调度引擎(`execute_graph`);新增节点 = 元数据 + 一个执行器文件,引擎不动。**嵌套**:`subgraph`(内嵌可复用子图)、`call_workflow`(调另一工作流当子流程,子 job 收纳 + 级联取消 + 防递归/过深)、`output`(声明工作流输出契约);子图与循环体都跑在同一套引擎上(并行/条件一致) |
| `publish/` | 发布:平台注册表(**只有需要登录态的真平台**)、任务队列、worker 协议;账号即挂平台的浏览器档案(`profile_id`) |
| `browser/` | 浏览器池 / 持久登录:`BrowserProfile`(可复用登录身份 = 持久分区 + 代理 + 元数据)统一发布账号与通用档案;会话受**租约**(一档案一时刻一会话)。RPA 节点 / 智能体 / 手动会话都经「入队动作 + 执行器回报」桥驱动 Electron 里的浏览器 |
| `scheduler/` | 触发器(manual/interval/daily/weekly/webhook)→ 触发工作流。注意:桌面端关掉进程后端就停了,所以定时任务依赖应用常驻(见「系统能力层」) |
| `agent/` | 智能体会话:CLI 适配器 + 流式 + 记忆 |
| `kb/` | 知识库:FTS5 trigram + 向量(Milvus Lite)+ 图谱(Neo4j,可选) |
| `generation/` | 文生图/视频:供应商契约 + 适配器 |
| `plugins/` | 插件:子进程执行 + 权限门 + MCP 暴露 |
| `jobs.py` | **任务总线**:所有后台工作(导出/转写/生成/工作流/发布)统一为 `jobs` + `task_events` |
| `notifications.py` | 站内通知:按用户投递,团队模式扇出给工作区成员 |

### 任务总线是枢纽

任何耗时操作都建一个 `job`(kind = render/transcribe/ai_generation/workflow/publish/scheduled),
前端任务中心只认 `jobs` + `task_events`,不关心是谁在干活。这让"取消任务"能有统一语义:
`cancel_job()` 把 job 落终态,工作流引擎**在每个节点边界重读 job 状态**决定是否停下
——中断是节点粒度的(执行中的单个节点无法安全掐断);子工作流经父子 job 链随父级级联取消。事件统一经 `emit_job_event()` 发,
TaskEvent 行只在总线创建。

每种 kind 有一个**执行模式**:`in_process`(默认,守护线程)或 `external`(外部 worker 经
`/api/jobs/worker/*` 的 claim/report 协议认领,跨后端重启存活——发布器同款模式的推广,
见 [ADR-0002](adr/0002-claim-report-worker-protocol.md))。`OPEN_STUDIO_EXTERNAL_JOB_KINDS=render`
即可把渲染交给独立 worker 机器,领域代码不改。

### 数据模型要点

SQLite(WAL)+ SQLAlchemy 2.0。所有实体挂 `workspace_id`,路由层 `ensure_workspace_access` 强制隔离(方法感知:写门禁读 ASGI 中间件绑定的 HTTP 方法)。

**表结构怎么演进**(重要,曾被误记为 Alembic):运行时**不跑迁移框架**。`init_db()` 做两件事——
`Base.metadata.create_all` 建出新装机需要的全部表,再依次跑 `app/core/db.py` 里的一串 `_migrate_*`
函数,给**已装机**补上 `create_all` 不会施加的变更(加列、改外键、回填)。

改表结构因此是两步:①改 `models.py`(新装机由此得到正确结构);②加一个 `_migrate_*`(已装机由此
跟上)。只做①的话,新装机正常、老用户升级后崩在缺列上。

`_migrate_*` 有明确的退休判据:**它保护的最早版本一旦不再需要支持,就可以删**。判据是引入时间
对比最早仍支持的 GitHub Release —— 早于它的只服务从未公开的 dev 库,可以删掉;晚于它的仍在为
真实用户的升级路径服务。仓库里一度还留着 30 个 Alembic 迁移文件,但它们从不被执行、且自
2026-07-23 起就与 `models.py` 漂移(此后模型改了 6 次、迁移 0 次),已随这条规约一并移除。

团队成员是**邀请制**:管理员按用户名发邀请(`workspace_invitations`),对方在站内通知里接受/拒绝,四级角色 + 逐权限覆盖。
每张表归一个领域所有(`app/domain/ownership.py`),行创建只发生在拥有方,棘轮测试强制
(见 [ADR-0003](adr/0003-data-ownership-over-splitting-models.md))。

**主机权限 vs 内容权限**:工作流的 `code` 节点在后端主机上执行任意 Python(进程隔离 + 超时 +
输出上限,但**不是沙箱**)。单机安装下作者就是机器主人,无所谓;团队/远程后端下,`edit` 是所有
写路由的门而 editor 默认就有 `edit`,不额外设防就等于「能改内容」隐含「能拿服务器」。因此四条
落库路径(create / import / patch / 确认卡审批)都过 `ensure_graph_node_privileges`,要求
`ensure_instance_admin`——与供应商凭据、解释器路径同级。扫描**递归进子图/循环体**,否则
「折叠为子图」即可绕过。

- `sequences` / `tracks` / `clips` — 时间线;`sequence_operations` 记录每次编辑及其逆操作(撤销)
- `jobs` / `task_events` — 任务总线
- `workflows` — DAG 存 JSON:`{nodes:[{id,type,config,position}], edges:[{source,target,source_handle}]}`
- `publish_accounts` / `publish_tasks` — 发布账号与发布记录(`publish_accounts.profile_id` 指向所挂的浏览器档案)
- `browser_profiles` / `browser_sessions` / `browser_actions` — 浏览器池:持久登录身份、会话(租约)、待执行动作队列
- `notifications` — 每用户一行,`type` 含 `team`(为协作申请预留)

### 声音克隆的运行环境由 App 托管

f5-tts / fish-speech 都要 torch + torchaudio + transformers,**2.5–3.5 GB**。全部预装会把安装包
从 ~700MB 顶到约 4GB,而多数用户不用声音克隆;但要求用户自己 `pip install` 再来设置里填解释器
路径,又把一个可选功能变成了配置作业。所以拆成两半:

- **随包只带解释器**(`build/python`,~48MB,由 `pnpm fetch:tts-python` 在构建期抓取)。
  打包版后端是 PyInstaller 冻结二进制、`sys.executable` 指向自己**建不了 venv**,所以壳经
  `OPEN_STUDIO_TTS_BASE_PYTHON` 把它指给后端(`electron/main.cjs`)。
- **重的部分按需装**:用户点「下载」时 `ensure_engine_runtime` 用那个解释器在
  `~/.open-studio/tts/venv` 建环境、装引擎依赖,再拉模型权重。顺序不能反——权重是用那个环境里的
  huggingface_hub 拉的。

探测顺序是 用户覆盖 → 托管 venv → 本进程解释器(`tts_models.candidate_pythons`),所以点过下载
之后自动可用。设置页的「TTS 解释器」因此是**高级覆盖项**,留空是常态。

**两个下载源是分开的**:「模型下载源」管 HF 权重(`HF_ENDPOINT`),「依赖下载源」管 pip 索引
(`--index-url`)。装引擎要拉 2.5–3.5GB,国内直连 PyPI 常常慢到不可用,而它与权重镜像并不是
同一件事。自定义 index 只接受 http(s),避免任意字符串进子进程 argv。

## 预览与导出:两个渲染器,一份契约

画面有两套渲染实现,而且**只能有两套**:

| | 预览 | 导出 |
| --- | --- | --- |
| 在哪 | 浏览器,`CanvasCompositor`(WebCodecs 解 720p 代理 → canvas 2D)——**唯一路径,无 `<video>` 兜底** | 后端,`render_plan.py` + `render_executor.py` → 单次 ffmpeg |
| 为什么不能挪 | 要本地同步跑到 60fps,要渲染**尚未提交**的拖拽草稿 | 要无头、跨重启存活、可被外部 worker 认领([ADR-0002](adr/0002-claim-report-worker-protocol.md)) |

两个约束各自成立,所以合并成一个渲染器不是可选项。一致性按**谁是权威**分层处理
(理由与被否决的方案见 [ADR-0004](adr/0004-preview-export-parity-by-contract.md)):

- **可见层 / z 序 / base 归属 —— 必须逐字一致**。这是所有已发生 parity bug 的所在地。
  两侧实现(`frontend/.../playback/sceneModel.ts` 与 `backend/app/media/scene.py`)由
  [`contracts/scene-cases.json`](../contracts/scene-cases.json) 钉死:同一份语言中立语料,
  两侧测试各跑一遍,任一侧单方面改语义 → 两边 CI 一起红。**改语义先改语料**。
- **调色 —— ffmpeg 权威,预览近似**,这是**有意的**而非缺陷。导出用 `eq`/`curves`/`lut3d`
  做真实色彩运算;预览是 CSS/canvas 近似(`monitorFilters.ts` 的函数名与注释即声明了这一点)。
  想让 canvas 成为权威就得放弃色阶曲线与 3D LUT——把权威换到低保真的一侧,不是对齐。
  预览显示不了的效果在 UI 明示(LUT 选择器下方的提示)。
- **文字 —— 已经同源一致**:导出侧 `text_render.TextRasterizer` 用无头 Chromium 加载
  **app 自己构建出的 CSS 与 @font-face** 渲成透明 PNG 再由 ffmpeg 叠加,字体环境与预览完全相同。
  拿不到 Chromium / 前端 dist 时优雅回落 libass。

**预览侧不再有第二条画法**。曾经并存一条 `<video>`/`<img>` 元素路作兜底,两条路的取景、层级与
调色都对不齐,「预览长什么样」于是取决于当时走了哪条。现在画不出来时**明说**而不是降级——
`previewReadiness.ts` 把状态判定成 转码中 / 生成失败 / 本机解不动 / 环境不支持,由
`PreviewUnavailable` 铺在监视器上,后两种给「重新生成代理」按钮,转码中按秒轮询自愈。
判定只看**播放头当前要画的**素材,末尾一个还在转码的片段不会挡住开头能放的部分。

> 想要逐像素精确的画面,行业惯例(PR / DaVinci)是**渲染预览**——走真正的导出管线渲一段来看,
> 而不是让两套近似互相追。

## 前端:服务端真相 vs 瞬时状态

- **React Query** 持有一切服务端实体(项目/素材/序列/任务/账号…),是唯一的服务端缓存。
- **Zustand** 只放拖拽草稿与瞬时 UI 状态(正在拖的 clip、选中集…)。

这条线不能混:把服务端实体塞进 Zustand 会立刻产生两份真相。

### 关键约定

- **时间线几何**是纯函数(`domain/timeline/geometry.ts`),组件绝不内联几何计算。吸附是**两级**的:目标轨片段边缘优先,播放头/零点/跨轨边缘只在本轨无命中时参与(单一候选池会让字幕 cue 边界劫持同轨对接)。
- **样式全部内联为 TSX Tailwind 类**,`styles.css` 只剩 portal 覆盖(~40 行);禁手写全局 class、禁共享类字符串文件。刻度:昼「暖纸面」`#f6f4f0`+`#6a5cd8` / 夜「暖檀黑」`#141218`+`#8a7bf0`(独立调校非翻转),`--radius: 8px` 派生 sm=6/md=8/lg=10/xl=14,分段控件一律药丸形,表单填充用 `--field` 实底。
- **全平面无阴影**:分层靠发丝边框 + 底色层级(`--shadow-*` 解析为 none);焦点环/inset 不算。
- **控件一律用 Radix/shadcn**(`components/ui/`),禁原生 `select`/`alert`/`confirm`/手写弹层;**动态长列表下拉一律可搜索 Combobox**(`components/app/combobox.tsx`)。
- **Tailwind v4 两个陷阱**(已踩实):`space-y` 落在前一子元素的 margin-bottom、对 inline 元素(如 Label)蒸发 → 纵向堆叠一律 grid/flex+gap;`translate-*` 类编译为独立 `translate` 属性、与行内 transform **叠加**而非覆盖 → 定位由行内样式负责的元素类里不得再写定位类。
- **表单一律 shadcn Form**(react-hook-form + zod),字段级错误就地红字,表单级错误用 destructive Alert。
- **拖拽一律 dnd-kit**(原生 HTML5 DnD 在 Electron 下真实鼠标不触发);dnd 相关 hooks 必须在任何 early-return 之前。
- **文案全部走 i18n**(`app/messages.ts`,zh-CN / en-US 双份,键必须成对)。
- **深链事件通道**:跨页面跳转用 `openstudio:open-*` CustomEvent(`open-cmdk` / `open-asset` / `open-kb-doc` / `open-publish-task` …),派发统一走 `lib/deepLink.ts` 的 80/300/800ms 三连发(目标视图挂载慢时单发会丢)。

### 桌面适配

前端通过 `window.openStudioDesktop`(preload 暴露)判断是否在 Electron 里,给 `<html>` 打 `is-desktop` / `is-mac` / `is-win`:

- 无边框窗:顶栏全宽横贯,mac 红绿灯落在顶栏左侧(面包屑让位 88px),Win/Linux 用 `titleBarOverlay` 并给顶栏右侧留位。
- 拖拽区:顶栏与侧栏可拖窗(`-webkit-app-region: drag`),其中交互元素必须 `no-drag`,否则点击被当成拖窗吃掉。

### 系统能力层(`electron/system/`)

每个能力一个模块 + 统一 `register(ctx)`,`main.cjs` 只负责遍历;esbuild 打成
`system.bundle.cjs`,缺失不挡启动(只是退化)。

| 能力 | 解决什么 |
| --- | --- |
| `residency` | **关窗 = 收进托盘,不退出**。后端是主进程 spawn 的子进程,退出即随之停止 —— 在此之前 Windows/Linux 关个窗就把定时任务一起关了,而用户以为它还在跑 |
| `tray` | 关窗不退之后,应用还活着的**唯一可见证据**;只做前者就是关不掉的幽灵进程,两者必须成对 |
| `loginItem` | 开机自启(带 `--hidden` 静默驻留)。和 residency 是一对:一个让它开机就活着,一个让它一直活着 |
| `power` | 有任务在跑时 `prevent-app-suspension`。渲染/发布是分钟到小时级,机器合盖会把 ffmpeg 一起挂起 |
| `badge` | mac/Linux 角标数字、Windows 任务栏进度。切走之后也看得到进度 |
| `notify` | 任务完成通知,**窗口有焦点时不发**(应用内已有 toast,否则同一件事说两遍) |
| `protocol` | `openstudio://` 唤起 + 视频/音频文件关联 + 全局快捷键 |

两条贯穿性的约束:

- **状态是推进来的,不是拉出去的。** 系统层不认识后端、也不知道「任务」是什么,只知道有个数字叫
  `runningJobs`(渲染层的 TaskCenter 本就在轮询 `/api/jobs`,顺手推给它)。托盘文案、角标、防睡眠
  吃同一份快照。这条单向依赖是这一层能被单独测、也能被整体摘掉的原因。
- **协议只导航,不执行。** 自定义协议是外部输入面:任何网页 `location = "openstudio://…"` 就能触发,
  不需要用户确认。所以只支持「打开某个页面」(view 走白名单、id 限字符集),不支持「运行工作流」
  —— 后者意味着随便访问一个网站就能静默驱动你的自动化。将来要做,正确形态是链接只发起一个
  **待确认请求**,由应用内弹确认卡。

单实例锁在 `main.cjs`(必须早于 app ready):没有它,双击两次图标就有两个实例 —— 两个发布 worker
抢同一批任务、两套内嵌浏览器争同一个登录分区,而后端因为端口健康检查会复用,表面上「没问题」。

## 智能体与 MCP

智能体通过 MCP 工具读写系统(查素材、改时间线、跑工作流、生成内容)。
**所有写操作先出确认卡**(`tool_confirmations` 表 + 前端卡片),用户批准后才执行——见 [MCP.md](MCP.md)。
智能体也能复用**浏览器池**:`browser_pool_list` 只读发现档案(不含 cookie),`browser_pool_open(profile_id)`
是确认卡工具——不经用户批准一张**点名该登录身份**的卡(显式授权每会话),智能体拿不到任何已登录档案。

工作流画布里的 AI 编辑也是同一套:每条工作流一个常驻智能体会话(`external_key = workflow:<id>`),
有记忆,改图走 `update_workflow` 工具 + 确认卡,画布检测到 `updated_at` 变化自动同步(未脏时)。

## 服务器切换(团队模式)

`API_BASE` 在**模块加载时**从 `localStorage["openstudio.server.url"]` 解析一次,默认 `http://127.0.0.1:8800`。
切服务器 = 写 localStorage + **整页 reload** 让它重新解析(会话随之失效,落回登录页)。

因为 `hasUsers` 探测与 `login` 都打向 `API_BASE`,**服务器入口必须在登录之前**——所以 `ServerPicker`
同时挂在登录页和设置页(同一组件)。切换前探活 `/api/health`,探不通给"仍要连接"兜底。

## 解耦形态与决策记录

进程层是「微内核 + 卫星进程」:后端唯一事实源,重活出进程,接缝画在进程边界、协议显式化。
**不做网络微服务**——理由与边界见 [ADR-0001](adr/0001-no-network-microservices.md);
统一语言见根目录 [CONTEXT.md](../CONTEXT.md)。
