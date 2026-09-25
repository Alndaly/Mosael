# 架构

## 三段自举:App 启动时发生了什么

`open "Mosael.app"` 一条命令背后是三件事,顺序由 `electron/main.cjs` 编排:

1. **拉起后端** — spawn 打包的 `mosael-backend` 二进制(开发模式则是 `uvicorn`),轮询 `/api/health` 等它就绪(30s 超时)。
   若 8800 已有健康后端(如 dev server),**复用它**,不再起新进程(`ensureBackend()` 里的 `isHealthy()` 检查)。
2. **开窗加载前端** — 打包版 `loadFile(frontend/dist/index.html)`,开发版 `loadURL(localhost:5173)`。
   hash 路由(`#/editor?p=<id>`)——因为 `file://` 下 path 路由不可用。
3. **启动发布执行器** — `publish.bundle.cjs` 里的 worker 开始轮询后端认领发布任务(见 [PUBLISHING.md](PUBLISHING.md))。

后端是**唯一事实源**。前端和发布执行器都只是它的客户端——这也是为什么发布执行器能在 App 重启后接着干活。

## Chrome Side Panel 扩展：受认证的外部客户端

`browser-extension/` 是独立分发的 Chrome MV3 客户端，不进 Electron 安装包。点击工具栏图标由
`chrome.sidePanel` 打开原生侧栏；`page-bridge` 在站点主世界读取 YouTube / B 站自己的播放器与字幕
对象，其他 HTTP(S) 页面走通用 HTML5 播放器适配；隔离世界里的 `content` 只转发数据、从多个候选中
选择真正可见且可播放的 `<video>`、执行词/句级时间跳转与视频像素截帧，`sidepanel` 负责 UI 与
Mosael API。网页中没有可见注入节点，也没有悬浮层。

侧栏本身是 React 19 入口 `sidepanel.tsx`，表单与交互控件只经扩展自己的 `components/ui/`（Radix /
shadcn）暴露，布局使用 Tailwind v4 utility；`styles.css` 只保留 Tailwind 入口、产品色 token 与基础层，
不回到按 DOM id 维护手写样式。Chrome `_locales` 负责扩展名称、描述与工具栏标题；运行中 UI 字典由
`i18n.ts` 管理，支持跟随浏览器或固定简中 / English，选择保存在 `chrome.storage.local`。

扩展复用公开 API：`/api/translate`、`/api/assets/url-support`、`/api/assets/import-url`、
`/api/assets/{id}/transcribe`、`/api/jobs/{id}`、`/api/assets/{id}/transcript`、
`/api/assets/transcript-by-source`、`/api/assets/import` 与 `/api/browser/profiles`，
所以双语回退、无字幕自动转写、已生成逐字稿恢复、
工作区权限、后台任务和素材入库仍走原来的事实源。它用 `/api/auth/login` 换取独立 `AuthSession`，
只把会话保存到 `chrome.storage.local`，不保存密码；后端 CORS 仅额外接受形如
`chrome-extension://[a-p]{32}` 的真实扩展 Origin，接口本身仍逐条认证和鉴权。

扩展故意不申请 `cookies` 权限：Chrome Cookie 不会被导出到后端。用户可在侧栏选择 Mosael
已经管理的浏览器池档案；下载任务只把 `profile_id` 交给后端，由既有浏览器池复用档案 Cookie 与代理。
前端先用 DOM 判断是否有可操作播放器，再用 `/api/assets/url-support` 查询当前安装的 yt-dlp extractor；
因此「后端可导入/转写」与「页面可跳转/截帧」是独立能力，不能用站点域名枚举混为一个布尔值。截帧优先对 origin-clean 的
`<video>` 直接 `drawImage`，保留媒体固有分辨率且不含 HTML 控件；跨域媒体污染 Canvas 时，隔离世界
临时隐藏覆盖在视频矩形上的页面元素和原生 controls，等两个 animation frame 后再由侧栏
`captureVisibleTab` 裁切，最终无论哪条路径都只入库视频画面。

## 后端:领域内核 + 薄路由

`backend/app/domain/` 是真正的内核,`api/routes/` 只做 HTTP 转译与鉴权。

| 领域 | 职责 |
| --- | --- |
| `sequences/` | 剪辑内核:insert/move/trim/delete/split/cut-range 等操作,每次操作校验不变量并落 `sequence_operations` + `sequence_revisions`。撤销/重做拆成两层 —— `history.py` 只管队列(往回找该撤销的那一条、能不能重做),**怎么撤销**在 `undo/` 注册表里按操作类型成对登记(逆向 + 正向),`UNDOABLE_KINDS` 由注册表派生而非手写。新增一种操作 = 记录它 + 登记一对逆操作,`tests/test_undo_registry.py` 守着这个配对 |
| `render.py` | 序列 → RenderPlan(纯函数)→ ffmpeg 执行导出 |
| `transcripts/` | 逐字稿:ASR 导入、token 级编辑、投影到时间线(删句 = 剪源区间) |
| `workflows/` | DAG 工作流:节点注册表(元数据)+ `executors/` 执行器注册表(行为)+ 统一并行调度引擎(`execute_graph`);新增节点 = 元数据 + 一个执行器文件,引擎不动。**嵌套**:`subgraph`(内嵌可复用子图)、`call_workflow`(调另一工作流当子流程,子 job 收纳 + 级联取消 + 防递归/过深)、`output`(声明工作流输出契约);子图与循环体都跑在同一套引擎上(并行/条件一致)。**引用即依赖**(`reference_dependencies`):节点 `{{…}}` 引用了谁就等谁落定,拓扑排序、环路校验、调度共用这一份 —— 此前只有被规范化成数据边的引用(顶层字段、两段路径)才排先后,`{{分镜.json.shots}}` 或循环 `inputs` 里的引用可能在上游跑完前被读成空值 |
| `publish/` | 发布:平台注册表(**只有需要登录态的真平台**)、任务队列、worker 协议;账号即挂平台的浏览器档案(`profile_id`) |
| `browser/` | 浏览器池 / 持久登录:`BrowserProfile`(可复用登录身份 = 持久分区 + 代理 + 元数据)统一发布账号与通用档案;会话受**租约**(一档案一时刻一会话)。RPA 节点 / 智能体 / 手动会话都经「入队动作 + 执行器回报」桥驱动 Electron 里的浏览器 |
| `scheduler/` | 触发器(manual/interval/daily/weekly/webhook)→ 触发工作流。webhook 凭任务级密钥触发,同一把密钥还能查那次运行的进度、取消它(`api/routes/hooks`),密钥由服务端独管、可重置。启用着的任务一定跑得起来(`ensure_runnable`):绑的工作流删了,任务随即停用。注意:桌面端关掉进程后端就停了,所以定时任务依赖应用常驻(见「系统能力层」) |
| `agent/` | 智能体会话:pi Agent Adapter + sidecar 流式协议 + 会话/记忆 + 工具循环 + 子智能体 |
| `audio/`(在 `app/` 下,与 `domain/` 平级) | 语音:ASR 引擎目录与 worker、TTS 引擎与守护进程、音色克隆、字幕配音(`subtitle_dub.py`)。**语言能力挂在权重上而不是引擎上**(`f5_models.py` 是那张表,`tts_language.py` 是合成前的那道判断) |
| `generation/` | 文生图/视频。**参数描述符(`catalog.py`)是唯一事实源** —— 界面按它渲染控件、智能体按它知道能给什么、提交按它校验(五条路都汇到 `create_generation_job`,漏拦的后果不是报错:供应商可能默默忽略,于是要的 10 秒跑出默认的 5 秒)。描述符只按精确 `(vendor, model, kind)` 匹配，**查不到时不猜这个模型**(同系列不同型号的时长、角色、枚举经常不同)。但「不猜模型」不等于「什么都不知道」:请求是我们自己构造的,Adapter 说得出自己发哪几项标量参数(`parameter_surface`),那个面与模型名无关时兜底就用它 —— **只给键、不声称取值范围**;面依赖模型时才是空参数表。用户还可以给自己那条连接写一份参数组,在模型行上按 kind 指过去(见 [ADR-0015](adr/0015-generation-parameters-come-from-the-adapter.md))。布尔、枚举、特殊时长和分辨率-时长组合也属于这份契约。输入素材**带角色**,不靠位置 —— 各家接口本来就有 role,而扁平列表表达不了。角色分**三条互不相通的路**:首尾帧(决定成片的第一格和最后一格)、参考素材(参考图/视频/音频,一帧都不出现在成片里,只影响风格与主体)、视频输入(`source_video` 是被编辑的那一段、`first_clip` 是被续写的那一段、`driving_audio` 驱动口型与卡点)。素材之间的规矩全由描述符声明:份数上限 `source_limits`、互斥组 `exclusive_source_groups`、必填 `requires_source`、搭伴 `requires_companion`、参考图下限 `min_reference_images`、跟着素材变的时长上限 `conditional_max_duration_seconds`。数字来自各家接口自己的报错,不是文档里的建议值;角色的名字和给智能体的说明也在这里(`SOURCE_ROLE_LABELS` / `SOURCE_ROLE_HELP`),**只此一份** |
| `translate.py` | 文本翻译:Google 免费端点 + 走工作区模型的 LLM 两条路,字幕面板与工作流节点共用 |
| `assets/from_url.py`(配 `media/ytdlp.py`) | 从链接导入素材:先探清单再下选中的几条,音频/视频与画质上限在下载前定;需要登录的站点**借浏览器池档案的 cookie**(经既有动作队列问 Electron 要),入库仍走 `register_file_asset` |
| `assets/video_gif.py`(配 `media/video_gif.py`) | 视频转 GIF:领域层排任务并登记派生素材,媒体层只负责 ffmpeg 转码。来源关系只写到新 GIF 的 `media_info`,原视频字节与记录都不改;素材页右键与工作流节点共用这一条路径 |
| `plugins/` | 插件:子进程执行 + 权限门 + MCP 暴露;市场索引与安装(`registry.py`)、文件双向搬运(`artifacts.py` 交出 / `inputs.py` 收下)、跨调用状态(`state.py`)。**不认识素材库** —— `media_bridge.py` 只定义来源与落点的契约,由 `domain/assets/plugin_bridge` 在组装根登记(同 jobs 不认识智能体) |
| `core/pip_install.py` | **通往 pip 的唯一一道门**(声音克隆 / 转写共用)。带上设置页那个镜像、`--prefer-binary`(挡的是"为了新版本号去本机编译 Rust")、够用的超时重试;失败时挑出 pip 自己的结论行而不是取输出尾巴,并把完整输出落盘 |
| `core/run_log.py` | 子进程的完整输出落盘(`~/.mosael/logs/`)。装依赖、下权重两条路共用 —— 界面只放一句话,而排查要全文,此前全文哪儿都没有 |
| `core/text.blame_line` | 从子进程输出里挑出**说明失败原因**的那一行。**不取最后一行**:那常常是收尾提示、分隔线,或者一根 tqdm 进度条(这个坑踩过三次,判据因此收在一处) |
| `audio/remote_size.py` | 问下载源要**实际的**文件大小(HuggingFace `?blobs=true` / ModelScope `/repo/files?Recursive=True`),按这次真正要取的文件算而不是整仓。问不到就退回目录里的估算**并说出它是估算** |
| `jobs.py` | **任务总线**:所有后台工作(导出/转写/生成/工作流/发布)统一为 `jobs` + `task_events`;终态时按 payload 里的 `receipt` 回执给发起方(监听状态变化,不认某个函数 —— 各处写法不一) |
| `notifications.py` | 站内通知:按用户投递,团队模式扇出给工作区成员 |

### 任务总线是枢纽

任何耗时操作都建一个 `job`,前端任务中心只认 `jobs` + `task_events`,不关心是谁在干活。这让"取消任务"能有统一语义:
`cancel_job()` 把 job 落终态,工作流引擎**在每个节点边界重读 job 状态**决定是否停下
——中断是节点粒度的(执行中的单个节点无法安全掐断);子工作流经父子 job 链随父级级联取消。事件统一经 `emit_job_event()` 发,
TaskEvent 行只在总线创建。

每种 kind 有一个**执行模式**:`in_process`(默认,守护线程)或 `external`(外部 worker 经
`/api/jobs/worker/*` 的 claim/report 协议认领,跨后端重启存活——发布器同款模式的推广,
见 [ADR-0002](adr/0002-claim-report-worker-protocol.md))。`MOSAEL_EXTERNAL_JOB_KINDS=render`
即可把渲染交给独立 worker 机器,领域代码不改。

**任务的归属与播报**([ADR-0018](adr/0018-job-ownership-and-announcements.md)):

- `dispatch_job` 在它起的线程里把"当前父任务"设成这个任务,于是执行体里建的任务(字幕配音
  逐句的合成、导出收尾排的预览代理)都是它的子任务,取消会一并级联。两档:工作流引擎和调度器
  是**严格**的(父任务已结束就拒绝派生);执行体自己是**派生**的(父任务刚落终态也照样挂上)。
- 每种任务在界面上的样子在 `domain/job_catalog.py` 声明一次:名字、做完要不要说
  (`always` / `failures` / `never`)、可能改动的资源、在哪一页看它的记录;`GET /api/jobs/kinds`
  发给前端。前端只补图标和"资源 → 缓存键"两张表(`components/layout/jobKinds.tsx`)。
  `create_job` 用到的每个种类都得在目录里、每个种类都得有图标,都有测试守着。
- **只有任务中心播报**:它按目录给顶层任务弹提示、发系统通知、刷新改动过的数据。发起任务的
  组件只说"排上了"。站内通知(铃铛)不变。

**付过钱的远端工作不会被我们放弃**([ADR-0019](adr/0019-paid-remote-work-is-never-abandoned.md)):
提交给供应商之后,只有两种结束方式 —— 远端给出终态,或者用户取消。

- 回执在开始等的那一刻落库:`poll_until_ready`(七家异步适配器唯一共同经过的轮询循环)把轮询路径
  报给运行器装的 `RemoteTaskWatch`,运行器写进 `Job.payload.remote_task`。
- 提交和取回是两步:每家异步适配器实现 `resume(poll_path, …)`(`generate` = 提交 + 这一半)并声明
  `supports_resume`;漏了的会被棘轮拦下。
- 后端重启时,有回执的生成任务**接着取**(`jobs.register_resumer`),不再判"中断,请重新发起" ——
  照那句话做就是再付一次;开发时 `--reload` 每改一行代码就是一次重启。
- 轮询上限 6 小时,只防"供应商永远不回话";`wait_for_job` 没有自己的超时(取消会级联到子孙任务)。
- 循环一项失败后不再开始新的迭代(停止信号在失败的那个线程里立起来),失败全部报出来。

**失败原因只有认得出的才当 key**(`core/i18n.is_message_key`):任务消息和工作流错误都接受"key 或
一句现成的话",判断只在这一处。认不出的原样显示、不当模板填、不当 key 落库 —— 此前一句带 JSON
花括号的 LLM 报错被截成 80 字存进 `error_key`,读的时候拿它当模板 format,一条坏行把整个执行历史
接口打成 500,面板上看起来就是"一次都没跑过"。读取端不为改正之前的旧行留分支:迁移
`_migrate_job_keys_are_keys` 把库里不是 key 的清掉(每次启动都跑,不变式是 key ∈ 文案表 ∪ {""})。

### 创意画板:生成能力的第五个入口

画板(`domain/boards`)是一张无限画布,上面摆的是便签、图片、视频、音频、文档引用、3D 场景引用和分组框。它**不自己
实现生成** —— 出图出片汇进 `create_generation_job` 那条漏斗(前四个入口:AI 工作台、定时任务、
工作流节点、智能体),于是描述符校验、能力探测、计量记账、任务中心全都白拿。

画板上能产出东西的动作是一张**产出者注册表**(`domain/boards/producers`,ADR 0021):每个产出者
声明能挂在哪种格子上、要什么权限、有没有花钱或对外的副作用、收什么表单(在领域里用 pydantic 校验),
入口只有 `producers.run`(路由 `POST /api/boards/{id}/run`)。一格的产出者写在它的 `form.producer`
上,前端照它挂面板(`boardItemState.producerOf` → `boardComposers.BUILTIN_COMPOSERS`),不按种类猜。
四个内置产出者背后是三条路,因为它们本来就不是一回事:

| 动作 | 走哪条 | 同步还是任务 |
| --- | --- | --- |
| 出图 / 出片 | `create_generation_job` | 任务 + 回执 |
| 写 / 改文案 | `ai_chat.chat`(与工作流 LLM 共用单次补全 Interface;智能体走 pi Agent Adapter) | 同步,几秒就回 |
| 文案转音频 | `start_synthesis`(TTS 不是「生成」能力,选的是音色) | 任务 + 回执 |
| 剪一段 | 一次 ffmpeg,`register_file_asset` 登记成新素材 | 任务 + 回执 |

**产出落回画布靠回执**:建任务前用 `set_receipt()` 或 `job.payload["receipt"]` 标记「这次的
产出属于哪张板的哪一项」,任务落终态时由 `domain/boards.deliver_generated` 填回去。回执的登记
在组合层(`app/main._wire_seams`)的**导入期**,不在 lifespan 里 —— 不跑 lifespan 的入口
(TestClient、脚本)照样要能把产出填回画布。

`deliver_generated` 读任务结果**只经过 `outputs_of(job)`**,归一成
`[{"type": "asset", "asset_id"}, {"type": "text", "text"}]`:生成任务一次可能出多张(`asset_ids`),
语音合成和剪辑一次出一段(`asset_id`),便签写字交回正文(`text`)。这不是新旧兼容,是几种任务
本来就不同;只认一种的话,另一种落终态时占位会被当成失败摘掉 —— 用户看到的是「生成完就没了」。

节点的 `form` 与 `run` 是画布 JSON 的一部分,不是 React 选中态的副产品。`form` 保存提示词、模型、
参数与引用素材；`run` 保存 job id 和 idle/queued/running/succeeded/failed/cancelled 终态。保存时若旧快照
晚到,服务端保留已经落下的终态,避免失败任务被 stale autosave 改回 loading。边的命中半径覆盖左右可见
`+` 号,拖到交互目标即可吸附。五类节点都按同一套六态语义提供节点级描边、状态标签和终态内容，不能
只在空媒体槽里判断 `job_id`。Composer 的重建键只包含节点 id、产物 id 与成功终态：新产物或手动换
素材会从节点表单重新水合局部交互状态；成功会清空已消费的 prompt/手动引用并保留稳定模型选择，
拖动、逐字编辑、失败/取消不会清空，输入必须留给重试。便签写作同步返回，但同样是一个任务
（`board_write`，在请求线程里经 `jobs.run_job_inline` 跑完）：running → succeeded/failed 由任务总线
收尾、回执落回节点，任何异常都不会把节点留在 running；节点外壳与按钮读取同一生命周期。
提示词同时保存供模型调用的纯文本 `prompt` 与供编辑器水合的 TipTap `prompt_document`；后者保留正文中
`@` 素材 chip 的准确位置。只保存 `mentioned_asset_ids` 无法在组件重建后区分文件名文字与原子引用。

智能体改画板走 `edit_board`(细粒度算子 + 确认卡),和 `edit_workflow` 同一套:它表达意图,
服务端落到当前画布 —— 让模型吐回整份 canvas 的话,稍复杂一点的板必然出错(漏项,或把用户
一手拖好的位置推平),而这两种错都不报错。

### 工作流节点的字段声明

一个节点的表单**完全由 `NODE_TYPES` 的 `config` 声明生成** —— 编辑器不认识任何具体节点,
智能体和 MCP 读的也是同一份。所以「加一个字段」就是加一行声明,而**漏一个声明位不会报错**,
只会让界面安静地少一块能力。这份契约同时约束插件(见 [PLUGIN_MANIFEST](PLUGIN_MANIFEST.md)
的 `input_schema`,键名不同、语义一一对应)。

| 键 | 作用 | 判据 |
| --- | --- | --- |
| `type` | 控件形态:`template` / `string` / `number` / `object` / `graph` / `code` | **自由文本一律 `template`** —— 引擎对每个字符串值都做 `{{}}` 替换(`interpolate` 递归整个 config,不看类型),写 `string` 不是"不支持变量"而是声明落后于实现,后果是那一格没有 `@` 引用菜单。剩下的 `string` 只有三类:带 `options` 的枚举、带 `options_from` 的现查清单、选择器背书的 id |
| `required` | 必填 | 少了它跑不起来 |
| `advanced` | 收进面板的「高级」一档 | **留空也能跑**的才算。不是"我觉得它高深" |
| `options` | 静态枚举 → 下拉 | 渲染分支里 `options` **优先于** `type`,所以给选择器字段改 `type` 是无效的。**值一律是中性标识符**(`true` / `GET` / `image`):它会原样存进图、原样显示在下拉框上,是值不是文案,没有出口能把它翻掉 |
| `depends_on` | 这个字段跟着谁走 | 父字段一换,这里存的旧值就失效(换了供应商配置,模型还挂着上一家的)。声明在后端而不是前端一张表 —— **插件节点是运行时才知道的** |
| `active_when` | 这个字段在哪些配置下参与节点 | 形如 `{ "engine": "ai" }`，也可给允许值数组。表单显示、动态选项请求、就绪检查和运行前必填校验都读这一条；父值是运行时模板时保持启用。两端语义由 `contracts/workflow-field-activation.json` 对账。它表达的是能力分支，不用在某个节点组件里写 Google/AI 特例 |
| `outputs` | 这个节点交出什么 | 和执行体**真正返回的键**是同一批,两个方向都由棘轮钉着:声明了没返回 = 下游连上去拿到空;返回了没声明 = 界面上连不到它(`ai_generate` 的 `asset_ids` 就这么藏了一版) |
| `description` | 字段下面那行小字 | **只说标签说不出的东西**(约束、默认、格式、留空的含义)。说不出新东西就不写 —— 标签「系统提示词」下面再写一遍「系统提示词」,读的人要多花一次注意力才发现什么也没得到。反过来,执行器有硬约束而表单只字未提,那是要**补**说明 |
| `allow_custom` | 清单之外还能手填 | 模型名那种:新模型上线往往早于目录更新,只给下拉会把人堵死在「列表里没有,于是填不进去」的死角。**由声明说了算** —— 编辑器此前是按字段名猜(`key === "model"`) |
| `options_from` | 选项要现查:来源名 | 清单由 `domain/workflows/field_options.SOURCES` 里同名的函数给;有 `depends_on` 时,父字段的值作为 `parent` 带上,清单跟着它变。编辑器对所有这种字段走同一个接口(`GET /api/workflows/field-options`)。**一对互相牵连的字段(引擎 + 音色)是两格声明,不是编辑器里的特例** —— 语音节点曾把音色存成两个键、由编辑器按引擎显示其一,两个键一前一后,换引擎时那一格上下跳,看起来就是两个音色框。加一个来源 = 加一个函数;棘轮钉着"声明里用到的来源都存在"。**编辑器不认识任何具体节点**:插件的包/工具/连接、发布账号、可调用工作流、对话连接与模型此前是按 `node.type` 写死的一串 if,而**插件节点是运行时才有的类型** —— 那张表永远覆盖不到它,装了插件的人在那两个下拉里一个选项都看不到。来源函数拿得到的上下文是 `parent`(依赖字段的值)、`node_type`(插件节点的包名在类型里)和 `workflow_id`(可调用工作流要排掉自己),棘轮钉着取选项那段不出现 `node.type` |

字段在表单里的**顺序就是声明顺序**。编辑器不重排 —— 要换顺序改声明。

`label` 和 `description` 里写的是**消息键**,不是句子 —— 目录里存 key、出口才翻(见
[CONVENTIONS](CONVENTIONS.md#多语言))。写死一句中文不会报错,只会让英文界面上那一格是中文。

每一条都有对应的棘轮钉着(见 [CONVENTIONS](CONVENTIONS.md) 的清单),因为它们的共同点是
**违反了不会报错**:界面照常渲染,只是少了 `@`、少了一档、留下一个对不上的组合,
或者多一行白占地方的小字。

### 数据模型要点

SQLite(WAL)+ SQLAlchemy 2.0。工作区资源挂 `workspace_id`:只读入口显式调
`ensure_workspace_access`,写入入口显式调 `ensure_workspace_perm`。权限不从 HTTP 方法推断,
因此同一领域 Interface 从 worker / MCP / 飞书调用时不会静默改变语义。用户级资源
(如 Provider Profile /凭据)按 owner 隔离;实例配置由 `ensure_deployment_admin` 守卫。

**表结构怎么演进**(重要,曾被误记为 Alembic):运行时**不跑迁移框架**。`init_db()` 做两件事——
`Base.metadata.create_all` 建出新装机需要的全部表,再依次跑 `app/db/migrations.py` 里的一串 `_migrate_*`
函数,给**已装机**补上 `create_all` 不会施加的变更(加列、改外键、回填)。

改表结构因此是两步:①改拥有该表的 `model_slices/<domain>.py`(新装机由 ORM metadata
得到正确结构);②加一个 `_migrate_*`(已装机由此跟上)。只做①的话,
新装机正常、老用户升级后崩在缺列上。

**跑过的记账,下次跳过**:一次性迁移成功后把名字写进 `schema_migrations`,启动时先读这张表。
此前五十几个迁移每次启动全跑一遍,靠各自幂等兜着 —— 对,但代价随数据量长:十四个会整表读
(每条工作流的图、每张画板的画布)。实测空库 0.07s,两千工作流 + 一千画板 + 五千消息之后
0.40s,而它们什么都不做。记账之后这一段是 0.00s,升级那一次仍照常跑满。

**对账不是迁移**,三步除外:`create-current-schema`(create_all 每次都要跑,否则新版本加的表
永远建不出来)、清孤儿共享、job 消息键归一 —— 它们处理的东西会不断再产生,用 `_recurring()`
声明,不记账。失败的迁移不记账,下次启动重来。棘轮:`tests/test_migration_ledger.py`。

**记过账的迁移,身体不能再改**:那台机器再也不会碰它,所以事后改函数体对**所有已经升过的
机器无效** —— 而 bug 留在的恰恰是有历史数据、最需要修的那些库上。要改行为就新开一个步骤名
(新名字 = 新的一行账 = 老机器会跑)。指纹记在 `tests/migration_bodies.json` 里,算在
**可执行源码**上,所以补注释和 docstring 不受影响。棘轮:
`tests/test_migration_bodies_are_frozen.py`。

**步骤在计划里的位置也是语义**:加列的那一步必须排在读这一列的步骤之前。
`tests/test_schema_migrations_cover_the_models.py` 按 `schema_baseline.json` 建一个老库、
把全套迁移真的跑一遍,再对模型的每一列 —— 它就是这么抓到 `migrate-deployment-admin`
排在三条读 `users.is_deployment_admin` 的迁移之后、老库启动直接炸的。

发版 CI 还会运行 `test/bundle.smoke.mjs`:它先用 `test/upgrade_db_fixture.py` 造一份最小旧库,再真正
启动打包后的 Electron。通过条件不是「安装包能解压」,而是冻结后端完成升级并健康、打包 renderer
完成加载,最后旧库新增字段与数据仍正确。这条冒烟覆盖的是源码单测碰不到的打包路径和启动顺序。

`_migrate_*` 有明确的退休判据:**它保护的最早版本一旦不再需要支持,就可以删**。判据是引入时间
对比最早仍支持的 GitHub Release —— 早于它的只服务从未公开的 dev 库,可以删掉;晚于它的仍在为
真实用户的升级路径服务。当前门槛是 **v0.1.0**；调整它时同步 ADR-0006、Release Notes 和打包
升级夹具。仓库里一度还留着 30 个 Alembic 迁移文件,但它们从不被执行、且自
2026-07-23 起就与 `models.py` 漂移(此后模型改了 6 次、迁移 0 次),已随这条规约一并移除。

团队成员是**邀请制**:管理员按用户名发邀请(`workspace_invitations`),对方在站内通知里接受/拒绝。
工作区授权只使用 `owner > admin > editor > viewer` 四级角色,不再维护逐权限覆盖矩阵。
每张表归一个领域所有(`app/domain/ownership.py`),行创建只发生在拥有方,棘轮测试强制
(见 [ADR-0003](adr/0003-data-ownership-over-splitting-models.md))。**今天有 11 处存量越界,
全在路由层,写在棘轮的 ALLOWLIST 里只减不增。** 此前它们看不见:整个 `app/api/routes/`
写在豁免前缀里,理由是「路由是薄转译」—— 于是这句话在文档里是全称,在代码里不是。
一个被普遍相信的保证比一个没有的保证更坏,因为它让人不再去看。
文件布局可以按领域切片:`app/db/model_slices/*`、`app/api/schemas/*`、`frontend/src/api/domains/*`
提高 Locality,但切片不是公共 Interface。调用方仍分别只从 `app.db.models`、`app.api.schemas`、
`@/api/client` 这三个统一装配入口导入,因此继续拆文件不会把布局变化扩散到全仓。
**三侧都已切完**：ORM 类分在 `model_slices/` 里、schema 分在 `api/schemas/` 里，前端
`api/domains/` 同构；两个装配入口只剩一串转发，里面**不定义任何东西**。
（这里曾经写着确切的类数与文件数。每次拆分它们都会多几个，而没有任何东西提醒去改这句话 ——
一个写在散文里的数字，唯一的作用是在一年后骗人，而"分在若干个文件里"这个信息去掉数字照样成立。
要数就去数：`ls backend/app/db/model_slices | wc -l`。）`SourceAssetRef` 作为生成域的共享 schema 独立成文件，不反向依赖装配入口
(画板产出者的表单在领域里自己声明,见 `domain/boards/producers`)。
`tests/test_domain_assembly_entries.py` 与 `frontend/src/api/clientAssembly.test.ts` 钉住重导出身份和 ORM
metadata 注册，防止“文件移动成功、统一入口漏装配”这种只在运行期出现的错误 —— 前者已从逐域手写的
断言换成三条通用不变量，新切一个域自动被覆盖。

**代码节点是内容,隔离是执行器责任**:工作流的 `code` 节点与其他节点一样按
`edit` 授权。它通过 `app/domain/sandbox` 执行:默认无网、不继承后端环境变量,
并限制文件、内存、进程数与时长。所有平台统一使用 Docker（预先准备 `python:3.14-alpine`）；
原 macOS 原生策略因 home 外文件读取与资源约束缺口已移除。无可用隔离后端时 fail closed。旧的 `PRIVILEGED_NODE_TYPES` 与
`ensure_graph_node_privileges` 已删除,不得以普通子进程作为回落。

- `sequences` / `tracks` / `clips` — 时间线;`sequence_operations` 记录每次编辑及其逆操作(撤销)
- `jobs` / `task_events` — 任务总线
- `workflows` — DAG 存 JSON:`{nodes:[{id,type,config,position}], edges:[{source,target,source_handle}]}`
- `publish_accounts` / `publish_tasks` — 发布账号与发布记录(`publish_accounts.profile_id` 指向所挂的浏览器档案)
- `browser_profiles` / `browser_sessions` / `browser_actions` — 浏览器池:持久登录身份、会话(租约)、待执行动作队列
- `notifications` — 每用户一行,`type` 含 `team`(为协作申请预留)
- `provider_profiles` / `provider_models` / `provider_defaults` — AI 供应商的连接、模型、能力默认(见下)

### 声音克隆的运行环境由 App 托管

f5-tts / fish-speech 都要 torch + torchaudio + transformers,**2.5–3.5 GB**。全部预装会把安装包
从 ~700MB 顶到约 4GB,而多数用户不用声音克隆;但要求用户自己 `pip install` 再来设置里填解释器
路径,又把一个可选功能变成了配置作业。所以拆成两半:

- **随包只带解释器**(`build/python`,~48MB,由 `pnpm fetch:tts-python` 在构建期抓取)。
  打包版后端是 PyInstaller 冻结二进制、`sys.executable` 指向自己**建不了 venv**,所以壳经
  `MOSAEL_TTS_BASE_PYTHON` 把它指给后端(`electron/main.cjs`)。**开发时也用它**:
  `interpreter.base_python()` 在注入之后先找仓库里的 `build/python`,而不是后端自己 ——
  两者次版本可以不同(后端 3.14;随包 3.13,因为 whisperx 还不支持 3.14),托管 venv 装不装得上
  取决于建它的解释器。
- **重的部分按需装**:用户点「下载」时 `ensure_engine_runtime` 用那个解释器在
  `~/.mosael/tts/venv-<引擎>` 建环境(一个引擎一份,转写、分离同理)、装引擎依赖,再拉模型权重。
  顺序不能反——权重是用那个环境里的 huggingface_hub 拉的。
- **随包解释器换次版本时**,旧 venv 跑不起来了(site-packages 和扩展都绑着建它的那个版本)。
  启动对账 `drop-venvs-built-on-another-python` 删掉它们,引擎回到「未安装」,点一次下载按新解释器重装;
  权重不在 venv 里,不受影响。

探测顺序是 用户覆盖 → 托管 venv → 本进程解释器(`tts_models.candidate_pythons`),所以点过下载
之后自动可用。设置页的「TTS 解释器」因此是**高级覆盖项**,留空是常态。

音色库的新建入口负责“上传或现场录制参考音频”这条不依赖项目的路径。设置页与剪辑页复用
`features/voice/VoiceCreationDialogs.tsx` 的同一个 `UploadVoiceDialog`，麦克风生命周期进一步收口到
`useReferenceAudioRecorder`；不能在各页面复制 `MediaRecorder`，否则权限失败、空录音、编码扩展名和
关闭弹窗释放硬件会逐入口漂移。创建字段也不能内联进音色列表，否则空状态和列表高度会在点击后突变，
并绕开 `ModalShell` 的 sticky header/footer、焦点环安全区与统一提交状态。

“从转写说话人创建”仍归剪辑页，因为它依赖当前项目素材的 Transcript 上下文，但交互同样使用
`VoiceFromSpeakerDialog`，不在可滚动侧栏里展开。两条入口最终都写入同一份工作区音色实体。音色库和
创建入口只在“本地音色克隆”引擎下出现；远程 TTS 使用供应商自己的音色目录，不能把本地参考音色库
展示在远程引擎下，避免暗示两者可以混用。

**两个下载源是分开的**:「模型下载源」管 HF 权重(`HF_ENDPOINT`),「依赖下载源」管 pip 索引
(`--index-url`)。装引擎要拉 2.5–3.5GB,国内直连 PyPI 常常慢到不可用,而它与权重镜像并不是
同一件事。自定义 index 只接受 http(s),避免任意字符串进子进程 argv。

## AI 供应商:连接、模型、能力默认

三层,粒度各不相同——**混成一层是这块此前所有麻烦的根源**:

| | 是什么 | 表 |
| --- | --- | --- |
| **连接** | 某个用户配置的端点 + 鉴权方式(api_key / oauth) | `provider_profiles` |
| **模型** | 连接下的一行。能力与运行时参数的唯一挂载点 | `provider_models` |
| **能力默认** | 某个能力(chat/image/video/tts/podcast/embedding)用哪一行模型 | `provider_defaults` |

连接和秘密都归创建它的用户，但生命周期分开：`ProviderProfile` 保存端点与非密选项，
`ProviderCredential` 保存 API Key、OAuth 令牌、密字段和动态模型目录。业务读取只拿
`ResolvedConnection`；`resolve_connection()` 与 `require_connection()` 都按 `owner_user_id` 选择，
不会从另一个用户的第一条连接回退。

早期只有「档案」一层,还带一个 `default_model` 字段。于是同一个端点上的对话模型和生图模型没法
分别出现在两个能力分区里,用户被迫**拿模型名当档案名**建一堆档案——同一把 key 重复五遍,改一处
不牵连另一处成了负担而非特性。`default_model` / `capability_ids` / `model_overrides` 三个字段已从
`provider_profiles` 删除,替代品是模型行;此前散在二十来处的 `profile.default_model` 统一收敛到
`provider_models.model_id_for(db, profile, capability)`。

- **能力在模型上**。模型行的 `capability_ids` 留空时回落 vendor 预设(`domain/providers.py`),
  让回填来的老数据和"还没细分过"的连接继续可用。连接对外提供的能力 = 其下启用模型能力的并集。
- **运行时参数只下发显式设过的键**(`runtime_limits`):`context_window` / `max_output_tokens` /
  `reasoning` / `vision` / `reasoning_effort` / `developer_role`。带上 `None` 会让 sidecar 分不清
  "没设过"和"设成了 false",而两者的默认行为不同。
- **模型列表 = 已配置的行 + 供应商目录里还没配的**。目录说端点有什么(会变),模型行说用户做过
  什么(不该被目录冲掉)。目录里查不到的模型(私有部署、别名)可以手填,与目录来的平权,只额外
  标一个「目录中已不存在」。
- 供应商创建表单中的 `storage=default_model` 只是“创建时顺手加入一条模型行”，界面称为
  **初始模型**，不是能力默认；编辑连接时隐藏，由模型列表管理。Endpoint 属于供应商连接协议，标签
  不跟当前设置分区叫“对话/视频 Endpoint”；多能力供应商由各 Adapter 将同一地址归一到对应原生根。
- **数据归属**是 `app/domain/provider_models.py`,建行只经它的 `upsert`(棘轮盯着)。

Provider 代码用三层 Module 表达能力与连接协议两条轴：

| 路径 | 角色 | 依赖规则 |
| --- | --- | --- |
| `app/ai/providers/contracts/` | 图像/视频生成与语音能力 Interface | 不依赖 Adapter 或 Registry |
| `app/ai/providers/adapters/` | 按供应商/平台连接协议组织的 Implementation | 依赖契约和共享下载 Seam，不反向依赖公共门面或 Registry |
| `app/ai/providers/registry.py` | 内置 Adapter 的唯一装配入口 | 精确注册 `(vendor, kind)` / 语音引擎 id，重复键启动失败 |
| `app.ai.providers` | 领域调用方的稳定公共 Interface | 领域 Module 不直接选择具体 Adapter |

Adapter 目录先按**平台/企业归属**建立命名空间，再按**产品协议族**划分真正的实现边界；协议族内部
横跨多种能力时，再按 `image.py` / `video.py` / `speech.py` 拆分。ByteDance 下的
`ark/{image,video}` 与 `volcano/{speech,podcast}` 表达同一企业的两套控制台和协议，持久化 vendor id
仍各自兼容。阿里云的图像、视频和语音共享百炼 DashScope 连接协议，因此统一位于
`alibaba/dashscope/{image,video,speech}`。详见
[ADR-0010](adr/0010-provider-contracts-adapters-registry.md)。

Evolink 是「平台 Adapter」的例子：一个 `(evolink, image|video)` 协议实现服务多个上游引擎，
`model` 只负责选择 Seedance/Kling/Veo/Hailuo/WAN/Sora/GPT Image/Gemini/Seedream。它先把本地输入
上传到 Files API（图片归一化，视频/音频原样上传），按角色与顺序组装 `image_urls` / `video_urls` /
`audio_urls`，再走统一异步任务协议并立即下载限时结果；不会按引擎复制 HTTP Adapter。原生
火山 Seedance 与 Evolink Seedance 是两条独立连接，能力描述符仍按 `(vendor, model, kind)` 分开。
各模型族的已接通能力、证据等级与尚未接通差距见
[视频生成引擎能力矩阵](VIDEO_GENERATION_CAPABILITIES.md)。

所有远程媒体下载共用 `ai/providers/media_transfer.py`。API 客户端的 Authorization/API Key 只发往
显式受信同源；对象存储预签名地址不带凭据，重定向一旦跨源立即丢头。大文件流式写 `.part` 后原子
替换，inline/multipart 输入则有 64MB 上限。新增引擎不应再自己写
`client.get(url).write_bytes(...)`。

### 能力和执行面是两条轴

能力回答「这个模型会什么」,执行面(execution surface)回答「这次调用经哪个 Adapter」。把两者合在
一个 `vision_model` 或供应商开关里,会让调用方在 OAuth/API Key、工具权限和会话状态之间暗中换语义。
当前装配关系如下:

| 调用方 | 执行面 | Adapter / Interface | 状态与工具 | 视觉输入现状 |
| --- | --- | --- | --- | --- |
| AI Studio 智能体 | `agent` | pi Agent Adapter | 有会话、记忆、工具循环和子智能体 | 当前消息图片在所选模型声明视觉能力时直接送入;已有素材可经工具分析 |
| 无限画布写作/看图 | `automation` | `ai_chat.chat` → `direct` 或 `gateway` | 无状态、无工具的单次补全 | 图片经 `browser_compatible_image` 统一格式/MIME 后发送;视频发送采样帧 |
| 工作流 LLM 节点 | `automation` | `ai_chat.chat` → `direct` 或 `gateway` | 无状态、无工具的单次补全 | 节点目前只组装文本消息 |
| 素材分析 API / `analyze_asset` 工具 | 普通 HTTP=`direct`;AI Studio 工具=`automation` | `analysis.service` → `ai_chat.chat` | 无状态单次分析;工具调用继承令牌绑定的智能体会话模型 | 图片先归一化;视频走原生输入或采样帧 + 转写;OAuth Gateway 使用采样帧 |

`automation` 是选择集合而不是第四种传输协议:有 `base_url` 的 API Key 连接分派到后端 `direct`
Implementation;已登录 OAuth 连接分派到 sidecar `gateway` Implementation。两者对调用方暴露同一个
`ai_chat.chat` Interface。`analyze_asset` 的模型来源取决于调用身份：普通 HTTP/MCP 请求保持独立选模，
AI Studio 工具回连的短期令牌绑定 `agent_session_id`，服务端据此解析当前连接、模型与视频模式，工具参数
不能自报或覆盖这些事实。OAuth 图片与视频采样帧复用 `gateway`；Gateway 不支持原生 video block，
`auto` 因而走采样帧，显式 `native` 则明确提示改用抽帧。这里不再有 `gpt-4o-mini` 或其他硬编码模型
回退；Gemini 原生视频的 `generateContent` Adapter 也必须从模型行解析显式 `chat` 模型，模型不可用就
明确失败。

Gateway 的边界与安全不变量见
[ADR-0009](adr/0009-oauth-automation-through-a-tool-free-sidecar-gateway.md)。

**订阅计划(OAuth)的令牌自动刷新**。access token 普遍只有几小时,刷新是协议里就有的一步,但刷新
协议在 pi 的 Provider 定义里——自己在 Python 里实现等于把六家协议再抄一遍。所以后端只负责**决定
什么时候刷**,动作交给 sidecar 跑一次 `models.getAuth`(`refresh_oauth_credential`)。触发点有三处:
对话路径(pi 解析鉴权时)、查额度、以及**列档案**——少了最后一个,隔夜打开设置页必然看到一行
「已过期」,而它只要被用到就会自己好。刷不动才是用户需要知道的事,那时才用警告色说「需重新授权」;
失败带 5 分钟冷却,否则这个最常被拉的接口会每次都起一个 node 去撞同一堵墙。

**额度只在点击时查**(`domain/provider_quota.py`,六家各一个解析器)。这些端点都不是官方承诺的
公开接口(Anthropic 的 `oauth/usage`、Codex 的 `codex/usage` 都是各自 CLI 内部在用),定时轮询
既容易撞限流,也会在对方改接口后变成后台里一直失败的任务。查不到不抛 5xx——"这家不支持"和
"这次没查成"都是正常结果,统一的 500 错误提示会把两者吞成一句"请求失败"。

**重试是所有 AI 调用共享的**(`RetryingClient`,凡是发出站请求的那些模块都从它派生)。它是 `httpx.Client`
子类,在 `send()` 里对 429/5xx/RequestError 做指数退避 + 抖动,因此对调用方完全透明。此前只有对话
路径有重试,而限流对生图、生视频、TTS、向量化一视同仁。重试上限在设置 → **网络**(和出站代理同一页),进程级生效。

## 智能体的上下文:预算与整理

**窗口来自模型**:模型行的 `context_window` → 供应商目录 → **内置查证表** → 双档回退:云端 **128K**,
本机/LAN **32K**(按 base_url 判定)。四层合并**只在 `backend/app/domain/model_limits.py` 的 `resolve()`
一处发生**,**三条执行通道**都经过它:智能体那条(`domain/provider_runtime`)、直连 HTTP 那条
(`domain/ai_chat.target_for`,翻译/素材分析/工作流 LLM/AI 编排/发布文案/提示词优化/画板写作/放行判断
八个调用点)、以及设置页的回显 —— 界面显示的数和请求真正带的数必须是同一个。

直连那条此前**根本不经过它**:模型设置里填的「最大输出 Token」在那八个调用点上一个字节都发不出去,
而设置页那行写着「运行时真正会用的数」。`RUNTIME_FIELDS` 里每一格是不是两条通道都有落点,
由 `test_runtime_fields_reach_both_channels.py` 钉住;只有一条通道用得上的要在 `SIDECAR_ONLY`
里写明理由。

内置表(同一模块的 `KNOWN_LIMITS`)是手写的查证结果:多数端点的 `/models` 根本不报上限,于是 1M 窗口的
模型会被当成 128K。按**模型名前缀**匹配、不按 vendor(中转端点的 vendor 一律是 `openai-compatible`,
OpenRouter 的 id 还带 `厂商/` 前缀),最长前缀赢,数值一律向下取整 —— 报小只是早一点整理,报大是整轮请求被拒。

两个回退常量与判定逻辑在 sidecar(`agent-sidecar/src/compaction.ts`,`pi.ts` 引用)和后端各有一份,
**必须一致**——否则前端显示的水位和真正触发整理的时机会对不上。两侧由 `contracts/context-meter-cases.json`
钉住;内置表只在后端(sidecar 拿到的是后端算好的数),所以它不进契约。

**输出预算和上下文水位是两件事**:`stopReason=length` 表示本轮 `maxTokens` 已耗尽,推理 token 也计入;
它不能被解释成上下文窗口已满。知道模型上限时按 `OUTPUT_BUDGET_CAP = 65536` 封顶(**那是预算,不是上限**:
`max_tokens` 在部分接口上要和输入一起装进窗口);查不到上限时,普通兼容模型保守回退到 4K,推理模型回退到 32K,
两者都不超过上下文窗口的四分之一。

**判"是不是推理模型"用的是行为,不是我们的控制能力。** 这两件事此前共用一个数据结构:判据是
`thinking.profile_for(...)` 里有没有一档发得出去 —— 而那条判据回答的是「我发不发 thinkingLevelMap」。
qwen 和 GLM 用的不是 `reasoning_effort`(前者 `enable_thinking`、后者 `thinking.type`),我们这条路
发不出去,于是它们连同任何没查证过格式的推理模型都被当成"不思考",拿到 4K 的非推理额度。
现在 `thinking.burns_output_budget()` 单独回答行为那一问,**`None` 表示不知道**(不是 False),
由模型行上用户勾的「推理模型」决定;都没有才保守取 False。用户在模型设置里填的值不受封顶约束 —— 那一格存在的
意义就是突破默认预算。失败事件仍须携带真实 usage 与 context,供消息用量、计费和上下文水位展示使用。

**用量估算锚定真实 usage**:取最后一条带 usage 的助手消息(供应商回的 input+output),此后的新消息
才按 `CHARS_PER_TOKEN = 3.5` 估。纯靠字符估会随对话变长持续跑偏。同一套锚定规则在
`agent-sidecar/src/compaction.ts` 与 `backend/app/domain/context_meter.py` 各实现一次——前者决定何时
整理,后者供前端实时显示。

**整理发生在两轮之间**,不在 `transformContext`(那个在工具循环里每次 LLM 调用都会跑)。超过窗口的
`COMPACT_RATIO = 0.8` 时,把早期对话交给模型摘要,保留最近 `KEEP_RECENT = 8` 条:

- **切点必须回退到一条 `user` 消息**,否则会留下没有对应 `tool_call` 的孤儿 `tool_result`,下一轮直接 400。
- **摘要失败降级为截断,但仍如实回报**。静默降级会让用户以为上下文还在,而它已经没了。
- 结果作为一条 `compaction` 记录进时间线,前端折叠显示(移出多少条、腾出约多少 token)。
- 用户也可以在输入框的「会话设置」里点**立即整理上下文**——不必等它自己到线。

**思考档位**(off / low / medium / high)是**会话属性**:同一个模型有时要深想、有时要快答。off 表示
我们不主动向供应商要思考,**不表示模型不思考**——k3、DeepSeek reasoner 无论如何都会回思考内容,pi
照常解析、我们照常显示(藏掉才是撒谎)。这与模型设置里的「推理模型」是两件事:后者只决定拿到思考
内容后**怎么解析**。思考经 `thinking_start/delta/end` 流式落进同一条 timeline(与工具调用保序),
前端渲染成默认收起的折叠块。

## 预览与导出:两个渲染器,一份契约

画面有两套渲染实现,而且**只能有两套**:

| | 预览 | 导出 |
| --- | --- | --- |
| 在哪 | 浏览器,`CanvasCompositor`(WebCodecs 解 720p 代理 → canvas 2D)——**唯一路径,无 `<video>` 兜底** | 后端,`render_plan.py` + `render_executor.py` → 单次 ffmpeg |
| 为什么不能挪 | 要本地同步跑到 60fps,要渲染**尚未提交**的拖拽草稿 | 要无头、跨重启存活、可被外部 worker 认领([ADR-0002](adr/0002-claim-report-worker-protocol.md)) |

两个约束各自成立,所以合并成一个渲染器不是可选项。一致性按**谁是权威**分层处理
(理由与被否决的方案见 [ADR-0004](adr/0004-preview-export-parity-by-contract.md)):

- **可见层 / z 序 / base 归属 —— 必须逐字一致**。这是所有已发生 parity bug 的所在地。
  两侧实现(`frontend/src/features/editor/playback/sceneModel.ts` 与 `backend/app/media/scene.py`)由
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

### 多语言:我们自己的文案 vs 数据自带的文案

两套,别混:

- **我们自己的**(界面、节点声明、任务消息、失败原因)存 key,出口按请求方的语言翻(`core/i18n.t`
  与 `render_message`,语言由中间件放进 ContextVar)。棘轮钉着每个 key 两种语言都有。
- **数据自带的**(插件清单里作者写的、内置模板里节点的名字)是一段 `{"zh": …, "en": …}`,
  由 `core/i18n.pick_text` 挑:要的那种 → 同一主语言的变体(`en-US` 认 `en`)→ 作者声明的
  原文语言 → 部署缺省 → 作者写的第一条。**翻译贴着它翻译的那个东西写**,不另开一张对照表。

落库的东西按它**是谁的**决定在哪一刻定语言:任务消息和失败原因存 key + 参数(读的时候翻,
用户切语言后历史记录跟着变);模板生成的图是用户的数据(他随时能改名),所以节点名在**造图
那一刻**定死。

插件还拿得到「读的人在用哪种语言」:进程插件在请求体的 `locale` 和环境变量 `MOSAEL_LOCALE`,
MCP·stdio 在环境变量,MCP·http 在 `Accept-Language` —— 清单里的文案我们替它挑,而工具跑出来的
那些字只有它自己写得出。

**每个客户端都要把读的人的语言报上来**,后端的翻译全靠这一栏(中间件 `CarryLocale`,在 `app/api/middleware.py`)。
浏览器扩展曾经写死 `Accept-Language: zh-CN`:英文用户在扩展里收到的每一句后端文案都是中文,
而扩展自己的界面跟着浏览器语言走 —— 两半对不上,且没有任何地方会报错。

**客户端自报身份**的请求头是 `X-Mosael-Client`,语法 `<界面>/<版本>`(`app/1.4.3`、
`browser-extension/0.1.0`),在 `api/deps/auth.parse_client_header` **一处**解析,拆进
`auth_sessions` 的 `client_surface` / `client_version` 两列。认不出来就一对空串 ——
"不知道"是这两栏的合法状态,比编一个假的诚实。此前它只有一栏、没有语法:前端发版本号、
扩展发产品名,于是管理页把扩展那一行渲染成「vbrowser-extension」。

**反方向,后端也用响应头告诉客户端一件事:这次请求建了任务。** `X-Mosael-New-Jobs: N` 由中间件
`AnnounceNewJobs` 在任务总线 `create_job` 记下的基础上统一加(`jobs.watch_new_jobs`),CORS 点名
放行;前端请求层看到它就广播 `mosael:jobs-created`,App 让所有 `["jobs", …]` 列表失效。建任务的
接口有几十个、返回的也不都是 job —— 此前只有少数几个按钮记得自己刷新任务中心,其余的要等下一轮
轮询(空闲时 8 秒)。后台线程里派生的子任务不经过请求,仍靠轮询。

**请求中间件一律写成纯 ASGI**(`app/api/middleware.py`、`core/rate_limit.py`,补响应头共用
`core/asgi.adding_headers`),不用 `@app.middleware("http")`。后者把响应体放进一条内存管道、在另一个
任务里转发;拖视频进度条时浏览器每次跳转都中止上一个按范围读取的请求,而管道那头还在往下推。实测一条
370MB 录屏在 Chromium 里单次跳转,三层这样的中间件是 0.17–14.5 秒,纯 ASGI 是 0.03–3.7 秒。

**没接住的异常也要是一个读得到的 500。** Starlette 最外层的 ServerErrorMiddleware 在 CORS 外面,
它回的 500 不带 `Access-Control-Allow-Origin`,浏览器连状态码都不交给页面 —— fetch 直接失败,前端
只能说「连不上后端」,一个后端 bug 被说成网络问题(Blender「发送当前场景」连报过几次)。所以最里层
装着 `AnswerCrashes`:就地答一个带 CORS 的 JSON 500(按请求语言说「后端出错了」,不外泄异常原文),
再把异常原样抛出去,日志和测试照旧拿得到堆栈。它必须**最先** `add_middleware`,回复才会经过 CORS。

### 分层:底下那几层不认识功能模块

`components/`(通用件与外壳)、`lib/`、`api/`、`stores/` 是给所有功能用的,**不 import `features/…`**
(由 `design/layering.test.ts` 守着);唯一的组合根是 `app/`。反过来是允许的,功能模块之间也允许
互相用(画板用素材预览、剪辑台用配音面板)。

智能体对话是一个**功能模块**而不是一组通用件:`features/agent/` 里是整套对话壳(气泡、工具调用、
确认卡、语音、追踪视图),`features/ai-studio/` 只是把它摆进 AI 工作台那一页。此前它散在
`components/agent/` 和 `features/ai-studio/` 两处(那个目录现在已经不存在),于是 components
反过来依赖 features。

### 关键约定

- **时间线几何**是纯函数(`domain/timeline/geometry.ts`),组件绝不内联几何计算。吸附是**两级**的:目标轨片段边缘优先,播放头/零点/跨轨边缘只在本轨无命中时参与(单一候选池会让字幕 cue 边界劫持同轨对接)。
- **样式全部内联为 TSX Tailwind 类**,`styles.css` 只剩 portal 覆盖(~40 行);禁手写全局 class、禁共享类字符串文件。刻度:昼「暖纸面」`#f6f4f0`+`#6a5cd8` / 夜「暖檀黑」`#141218`+`#8a7bf0`(独立调校非翻转),`--radius: 8px` 派生 sm=6/md=8/lg=10/xl=14,分段控件一律药丸形,表单填充用 `--field` 实底。
- **全平面无阴影**:分层靠发丝边框 + 底色层级(`--shadow-*` 解析为 none);焦点环/inset 不算。
- **控件一律用 Radix/shadcn**(`components/ui/`),禁原生 `select`/`alert`/`confirm`/手写弹层;**动态长列表下拉一律可搜索 Combobox**(`components/app/combobox.tsx`)。
- **业务弹窗统一三段式**(`components/app/modals.tsx` 的 `ModalShell`):顶栏与动作栏 sticky 并复用
  中段的半透明 `popover` 表面 + backdrop blur,中间 body
  独占滚动并保留 `py-5` 焦点环安全区。底层 `DialogContent` 只留给命令面板、媒体预览这类非表单
  专用布局；命令面板仍须使用相同的半透明表面与 blur，不能回退到完全不透明；不能在业务页重复
  组合一套 `overflow-y-auto` 弹窗。
- **Tailwind v4 两个陷阱**(已踩实):`space-y` 落在前一子元素的 margin-bottom、对 inline 元素(如 Label)蒸发 → 纵向堆叠一律 grid/flex+gap;`translate-*` 类编译为独立 `translate` 属性、与行内 transform **叠加**而非覆盖 → 定位由行内样式负责的元素类里不得再写定位类。
- **表单一律 shadcn Form**(react-hook-form + zod),字段级错误就地红字,表单级错误用 destructive Alert。
- **拖拽一律 dnd-kit**(原生 HTML5 DnD 在 Electron 下真实鼠标不触发);dnd 相关 hooks 必须在任何 early-return 之前。
- **文案全部走 i18n**(`app/messages.ts`,zh-CN / en-US 双份,键必须成对)。
- **深链事件通道**:跨页面跳转用 `mosael:open-*` CustomEvent(workflow / publish task /
  settings / board / asset)。"打开哪一条"是一封**待取的信**(`lib/deepLink.ts`):发的一方
  放进信箱并立即广播一次;收的一方用 `useOpenRequest` —— 已挂载的当场收,还没挂载的挂载时
  自己来取,接不住(那一条还没加载出来)就返回 `false` 留着,列表到货后再投。此前是 80/300/800ms
  定时连发,赌对方什么时候准备好:慢机器上三次都赶不上就丢;页面卸掉之后定时器照样触发,在 CI 上
  撞上已经拆掉的 jsdom 把整轮测试打红。Mosael 没有知识库能力,不保留对应的事件或兼容分支。
- **详情恢复先恢复身份、再取数据**:`usePersistentSelection` 同步读取 localStorage 中的稳定 id，
  `CanvasDetailLoading` 在 React Query 返回前保留详情语义。工作流、画板、调度、插件和素材不能先以
  `null` 渲染列表页再异步切回详情，否则刷新会闪一次错误页面。
- **工作区智能体只有一套壳**:`features/agent/CanvasAgentChat.tsx` 被剪辑、工作流和画板复用。
  会话池、流、确认卡、附件和会话切换不能在各业务页复制；停靠态是布局列，悬浮态才是 overlay。
  左上角标题由 `AgentSessionSwitcher` 直接渲染当前会话并提供搜索，不能再包一层有边框的 selector。

### 桌面适配

前端通过 `window.mosaelDesktop`(preload 暴露)判断是否在 Electron 里,给 `<html>` 打 `is-desktop` / `is-mac` / `is-win`:

- 无边框窗:顶栏全宽横贯,mac 红绿灯落在顶栏左侧(面包屑让位 88px),Win/Linux 用 `titleBarOverlay` 并给顶栏右侧留位。
- 拖拽区:顶栏与侧栏可拖窗(`-webkit-app-region: drag`),其中交互元素必须 `no-drag`,否则点击被当成拖窗吃掉。
  **注意它不遵守层级**:拖拽区由 Blink 算好交给 OS,在页面拿到事件**之前**就被消费,z-index /
  绘制顺序一概无效。因此任何盖在侧栏或顶栏上方的全屏叠加层(对比视图、悬浮面板)**必须自己声明
  `no-drag`** —— 只有显式的 `no-drag` 能从拖拽区里减掉一块。见 MAINTENANCE_HOTSPOTS.md 第 10 条。

**悬浮层级**:工作流的悬浮面板与画布节点都支持 `Cmd/Ctrl + [` / `]` 升降层级
(`features/workflows/useFloatingPanel.tsx` 持模块级 z 序表,`Z_BASE = 55`)。**节点永远不得高于悬浮
面板** —— React Flow 的 `.react-flow__viewport` 带 `transform`、自成一个层叠上下文,节点的 z-index
在那个上下文内部生效,天然低于外层 fixed 面板,这条约束由结构而非纪律保证。焦点用
`onPointerDownCapture` 记(捕获阶段:拖拽与缩放都会 `stopPropagation`)。

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
| `protocol` | `mosael://` 唤起 + 视频/音频文件关联 + 全局快捷键 |

两条贯穿性的约束:

- **状态是推进来的,不是拉出去的。** 系统层不认识后端、也不知道「任务」是什么,只知道有个数字叫
  `runningJobs`(渲染层的 TaskCenter 本就在轮询 `/api/jobs`,顺手推给它)。托盘文案、角标、防睡眠
  吃同一份快照。这条单向依赖是这一层能被单独测、也能被整体摘掉的原因。
- **协议只导航,不执行。** 自定义协议是外部输入面:任何网页 `location = "mosael://…"` 就能触发,
  不需要用户确认。所以只支持「打开某个页面」(view 走白名单、id 限字符集),不支持「运行工作流」
  —— 后者意味着随便访问一个网站就能静默驱动你的自动化。将来要做,正确形态是链接只发起一个
  **待确认请求**,由应用内弹确认卡。

单实例锁在 `main.cjs`(必须早于 app ready):没有它,双击两次图标就有两个实例 —— 两个发布 worker
抢同一批任务、两套内嵌浏览器争同一个登录分区,而后端因为端口健康检查会复用,表面上「没问题」。

## 智能体与 MCP

智能体通过 MCP 工具读写系统(查素材、改时间线、跑工作流、生成内容)。
**所有写操作先出确认卡**(`tool_confirmations` 表 + 前端卡片),用户批准后才执行——见 [MCP.md](MCP.md)。

卡上那句话**落库存 key、出口才翻**(`summary_key` + `summary_params`,`ConfirmationOut` 按请求方的语言
渲染),和 `Job.message` 同一条规矩:卡活得比一次请求久,写入时就翻会把语言冻死在那一刻。
**确认卡尤其不能含糊** —— 它是授权界面,用户点「批准」之前唯一会读的就是这一行,一个英文用户
读不懂的授权提示等于没有提示。措辞是拼出来的,所以拼进去的每一段也留成 key(`core/i18n.fragment`,
`render_nested` 递归展开;连接号本身也随语言变)。老卡没有 key,原样返回它当时的原话。

**两种卡,一个等法,两种超时结局。** 确认卡问「这件事能不能做」,选择卡(`ask_user`,
`agent_questions` 表)问「你要哪一个」;后者不能被「本会话始终允许」自动答掉 —— 自动回答等于
让模型自己编一个。两者都让这次工具调用**停在那里等人**:等法由 manifest 上的标记
(`confirmation` / `awaits_answer`)驱动,各 runtime 自己生成 —— 应用自己那条(sidecar)阻塞
轮询,直连 MCP 的客户端自己轮询 `get_confirmation` / `get_answer`。所以工具描述里**不写怎么等**,
写死一种必然对另一种说谎。
到点之后两者相反:确认卡超时 = 那个动作**没有发生**,抛错;选择卡超时 = 用户还没顾上,而答案
仍然会到(作答后由回执送回这次对话),如实回一句「还没答」并拦住「再问一遍」。
智能体也能复用**浏览器池**:`browser_pool_list` 只读发现档案(不含 cookie),`browser_pool_open(profile_id)`
是确认卡工具——不经用户批准一张**点名该登录身份**的卡(显式授权每会话),智能体拿不到任何已登录档案。

工作流画布里的 AI 编辑也是同一套:每条工作流一个常驻智能体会话(`external_key = workflow:<id>`),
有记忆,改图走 `update_workflow` 工具 + 确认卡,画布检测到 `updated_at` 变化自动同步(未脏时)。

### sidecar 的生死

后端 spawn 它、用 stdin 喂帧,正常退出路径是**stdin 关了就退**。这条路在两种情况下到不了,
两种都留下一个 3.5MB 的 node 进程,没人管也没人看得见:

- **EOF 永远不来**:管道的写端只要还被任何一个进程持有就不关,而后端 fork 出的别的子进程会
  继承这个 fd。后端被 SIGKILL 之后,只要那些孙子进程还在,sidecar 就收不到 EOF;
- **EOF 来了但事件循环没空**:轮次是**故意不 await** 的(await 会让 stdin 停读),读循环结束时
  可能还挂着一次没返回的模型请求 —— 远端任务的轮询上限是六小时。

所以读循环结束时显式 `process.exit(0)`,并且另有一条看门狗按 `process.ppid` 判断父进程还在
不在(`agent-sidecar/src/lifetime.ts`)。判据用 ppid 而不是「ping 得到后端吗」:父进程一死,
内核立刻把孤儿挂到 init/launchd 名下,ppid 变成 1 —— 这是**内核给的事实**,不需要对方还能
答话,而后端正是在答不上话的时候才需要这条。看门狗的定时器 `unref()`:它自己不能成为
"进程还有事做"的理由,否则会把它要防的那件事变成必然。

### 子智能体

`run_subagent` 把一段独立调查派给**同进程内**的子智能体(sidecar 里另起一个 pi Agent,
不另起进程——它要的 models/streamFn 已在手上)。它只拿**只读工具**(manifest 的 `read_only`
标记,唯一名单在后端注册表):确认卡是对用户说的话,而卡上的发起方是用户看不见的子智能体,
这样的卡没法批;调查本来也不需要写权限。

派发**默认不阻塞**:调用立即返回 `subagent_id`,主智能体接着干别的,要结果时调
`wait_subagents`(报告经工具返回值进上下文);它不等的话,回合收尾时统一清算——等全部跑完,
把没送达的报告作为通知消息续一轮,模型消化完才真正结束。刻意不做轮中 steering 注入:
steering 存在「最后一次取队列之后 settle」的竞态,而 sidecar 是回合级进程,这轮不送报告就
永远没了。同一条消息里的多个 `run_subagent` 天然并发(pi-agent-core 并行执行工具批)。

过程全程可见:子智能体的每步工具调用以 `subtool` 协议事件外发(挂发起调用的 id),
跑完由 `subagent_result` 事件把完整存档(阶段性文字 + 每步工具)填回发起那张卡的
`details.subagent`——**只进 details 不进 content**,省下父模型的上下文正是派子智能体的意义。
前端把存档合成为一段"会话"(任务=用户气泡,产出=助手消息),与主对话共用同一个 ChatBubble。

### 智能体互通

`list_agent_sessions` 列出本工作区的会话(忙/闲);`notify_agent_session` 给另一个会话发
消息——就是 `POST /sessions/{id}/messages` 的原有语义:对方空闲立即开新一轮,忙则排队。
发起方身份取自 turn 令牌链上的 `_SESSION_ID`(不由参数转述,转述可伪造);来源走结构化字段
`origin_session_id` → `payload.from_agent_session`——标题自动命名跳过它,前端靠它画
「来自其他智能体」徽章,任何地方都不做信封文案匹配。

## 服务器切换(团队模式)

`API_BASE` 在**模块加载时**从 `localStorage["mosael.server.url"]` 解析一次,默认 `http://127.0.0.1:8800`。
切服务器 = 写 localStorage + **整页 reload** 让它重新解析(会话随之失效,落回登录页)。

因为 `hasUsers` 探测与 `login` 都打向 `API_BASE`,**服务器入口必须在登录之前**——所以 `ServerPicker`
同时挂在登录页和设置页(同一组件)。切换前探活 `/api/health`,探不通给"仍要连接"兜底。

## 解耦形态与决策记录

进程层是「微内核 + 卫星进程」:后端唯一事实源,重活出进程,接缝画在进程边界、协议显式化。
**不做网络微服务**——理由与边界见 [ADR-0001](adr/0001-no-network-microservices.md);
统一语言见根目录 [CONTEXT.md](../CONTEXT.md)。

### 声音处理:分离与降噪是能力,不是流程里的一步(1.4.0)

两件事同一个形状 —— 契约(`ai/providers/contracts/{separation,denoise}.py`)只说要什么、拿到什么,
不提引擎;实现在 `adapters/local/`;`registry.py` 是唯一装配点,重复 id 启动即失败;领域层
(`domain/separation.py`、`domain/denoise.py`)负责素材那一侧:取声音、调引擎、登记**新**素材,
原素材一个字节不动。四个入口(工作流节点、智能体工具、素材库、剪辑台右键)只跟领域层说话,
加一个引擎不改任何入口。

- **分离**([ADR-0016](adr/0016-source-separation-is-a-capability.md)):Demucs 跑在自己的托管 venv
  里(和转写、克隆的 torch 版本会打架)。**「装没装」的判据是起子进程 `import demucs.api`**,
  和转写、克隆同一条(`runtime/separation_models.probe_runtime`,缓存在 `download_state.ProbeCache`
  里,三种答案:跑得起来 / 跑不起来 / 还没测过)。此前这里看的是 `venv/bin/python` 在不在,于是
  pip 装到一半断掉的环境写着「已安装」,而 `ensure_runtime` 看到"已安装"就早返回、永远不去修它 ——
  用户拿到的是三个字「已安装」配一句「这个运行环境里没有 demucs:No module named 'numpy'」。
  现在跑不起来就一路补到底(包括解释器在、依赖不全的那种),装完再探一次,还是起不来就带着
  子进程说的那句话报出来。棘轮:`tests/test_runtime_readiness_is_an_import_probe.py`。
  字幕配音的「原声怎么办」(`domain/voices/original_audio`,
  剪辑台、智能体、工作流三个入口共用,由配音任务收尾时处理)选 `separate` 时只问领域有没有可用
  引擎；问不到就在排队前明确失败，执行中分离失败也原样上报，绝不静默改成整轨静音。问得到时每个发声的片段走一次剪辑台的「分离音频」,只是放到
  音频轨上的换成背景音:画面留在原处,源片段静音,可撤销。**不能**把视频片段直接指向背景音
  素材 —— 视频轨上的纯音频素材既不算画面、也不进混音,成片里就只剩静音。
- **降噪**([ADR-0017](adr/0017-noise-reduction-is-a-capability.md)),三个引擎:
  - 内置 `ffmpeg`(afftdn):**先量噪声底再下手**(写死的 `nf` 要么降不动、要么削人声),永远可用,
    `auto` 挑的就是它;只对持续的底噪有效。
  - `deepfilternet`:官方发布的 Rust 二进制(Python 包和新 torchaudio 不兼容),设置里显式下载,
    按平台**固定 SHA-256** 校验(`runtime/denoise_models`)。效果最好。
  - `rnnoise`:ffmpeg 自带的 `arnndn` + 打包进应用的模型文件(`runtime/models/rnnoise/`)。
  后两个都会把音乐当噪声,`auto` 从不挑它们。「只留人声」不在降噪里 —— 那是分离的人声那一份。引擎自己给出名字、说明、没准备好时的提示,界面
  不认识任何引擎。安装进度两种能力共用 `runtime/install_state.InstallStore`。
- 两者取声音都走 `media/audio_io`,**保留原采样率和声道**;转写那条 `_extract_audio` 降到
  16 kHz 单声道,只适合喂识别模型。视频降噪后画面原样拷贝、只换声音,产出的仍是视频。

### 生成参数从哪里来（1.4.0）

一条链上有四个来源,**按这个顺序**取第一个命中的:模型行上的声明(`generation_capability_refs`,
按 kind 分行)→ 目录里精确匹配的那一份 → 这条通道的 Adapter 说得出的参数面 → 空。
前三种各自回答一个不同的问题,不能塌成一个:

| | 谁说的 | 说了什么 | 取值验证过吗 |
| --- | --- | --- | --- |
| 目录 | 我们 | 键 + 取值范围 | 是 |
| Adapter 参数面 | 代码本身 | **只有键** | 否 |
| 用户写的参数组 | 用户 | 键 + 取值范围 | 否(保存时只校验形状) |

「这个模型真的没有参数」和「我们不认识这个模型」是两种处境,塌成一个就让后者看起来像前者 ——
界面因此要在落到 Adapter 兜底时**出声**,说出那几个键并说明没人验证过取值。反过来,界面
**不许替目录编值**:一个键出现而取值清单没声明时,凭空造出 `1024x1024` / `5 秒` 再取第一项当默认,
等于替这个端点作了它没做过的声明。

Adapter 声明 `surface_depends_on_model = False` 要同时满足两条:不按模型 id 分支,且面里每一项
在用户设置之前都不出现在请求里。两条由 `tests/test_adapter_parameter_surface.py` 钉住,退出声明
是一次显式编辑。可视表单的字段、分组、「这一格是谁的默认值」和「这个参数的取值装在哪个键里」
全部由后端 `domain/generation/custom_profiles.py` 描述 —— 抄到前端的那两份立刻就漏掉了四个
`default_*` 键。

### 3D 与画布协作（1.2.0）

3D 的 `scene_types` 定义物体、相机和关键帧；镜头通过 `camera_id` 引用物体。`sceneGraph` 与 `sceneTracks` 处理姿态采样、分组和帧编辑，`SceneDopeSheet` 只负责时间线交互。参考帧、灰模与 GLB 共用去除编辑辅助对象的导出副本。

**导入的模型归工作区,不归某个场景**(1.4.2)。此前它挂在 `scene_id` 上,而**工作流每跑一次都
新建一个场景** —— 于是在 Blender 里建好的产品模型在结构上永远进不了自动成片:那个场景还不存在,
模型没处挂。归工作区之后,`create_scene` 里那句「建完场景再导模型」和专为 Blender 接回而设的
`create_scene_with_model` 特例一起消失了 —— 它们都是那个错位边界的产物。老数据由
`_migrate_scene_models_to_workspace` 自动搬(表结构 + 文件目录,可重入)。

**后端也能渲白模**(`domain/scene_render`):几何、机位采样、投影、光照逐项对照工作台的 three.js,
所以工作流和智能体(跑在后端)也能拿 3D 场景当生成参考。**导入的模型也画得出**
(`scene_render/model_mesh`,1.4.2):此前后端把 `kind="model"` 整个跳过,而工作台的 three.js
画得出 —— 于是同一个场景在编辑器里有那件道具、在自动流程渲的每一张参考帧里没有,两边都不报错。
渲不动的(Draco/meshopt 压缩、面数超出 `TRIANGLE_BUDGET`、文件不在)逐条报出是哪一件、为什么
(`model_warnings`),而不是只记一个数。`domain/scenes.render_shot_references` 是
唯一的"渲参考 + 入库"实现,节点「渲染白模参考」、接口 `POST /api/scenes/{id}/shots/{shot}/references`、
智能体工具 `render_scene_references` 共用;还会从机位轨迹**算出**一句镜头语言(焦段、机位高度、
推拉/环绕/跟拍/摇/俯仰)供提示词使用。拍摄相机按世界坐标摆,不随分组变换(和工作台的 `pose()` 一致)。

**「从主题到完整视频」(模板 v8)按这套流程出片**:视觉圣经定下角色与场景 → 每个角色一张三视图、
每个场景一张设定图 → 分镜给出景别/焦段/运镜和每镜的出片路径 → LLM 按分镜搭白模(每镜一个布景台、
一台相机,台距由布景尺寸算出来,因为场景时间是所有镜头共用的,同一套人偶没法在不同镜头里站在不同位置)
→ 逐镜渲白模,再走首尾帧(按白模画首帧、必要时加尾帧)或参考素材(三视图 + 设定图 + 白模运镜视频)。
布景台的间距由布景实际尺寸算出来(不再是固定 40 米),每台收进一个组;「可用的 3D 道具」节点
(`scene_props`)把工作区里的模型列成「id + 名字 + **实测**长宽高」交给布景师,布景 schema 因此
能写 `kind="model"` —— 没有这份清单时,设计布景的那个 LLM 不可能凭空写出一串模型 id,自动流程的
布景就只能是基本体拼的。
两组素材在 Seedance 上互斥,生成节点用 `source_group` 逐镜选一组;能选哪几条由视频模型的能力决定。

评论与标记是画布协作层，使用独立模式和可见性开关；标记弹窗由每张画布的 provider 管理，任一时刻只打开一个。评论保留富文本提及信息并支持原地编辑。切换模式不卸载数据节点的连接点，撤销快照不能包含临时交互状态。文档节点只保存笔记 ID 与版本，通过工作区校验后读取正文。
