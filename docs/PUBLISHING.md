# 发布与账号矩阵

自媒体矩阵运营是核心卖点:多平台账号集中管理 + 成片自动分发。

## 只有一类执行器

平台注册表在 `backend/app/domain/publish/__init__.py`(`PUBLISH_PLATFORMS`),现在只有需要登录态的
真平台:`douyin` `bilibili` `xiaohongshu` `weixin-channels`,一律由**桌面端内嵌浏览器**驱动真实
平台页面。

后端只负责入队(`status=pending`),真正干活的是 Electron 里的发布执行器。所以**网页版无法发布**
——UI 会提示"需要桌面端"。

> 曾经还有一个 `executor` 字段区分 `local`(`folder` 投递到本地目录、`webhook` POST 给外部自动化)
> 与 `browser`。那两个从来不是「账号」:没有登录身份、没有平台,却因为 `create_account` 无条件建档,
> 每存在一个就在浏览器池里留一个永远不会有登录态的空壳。它们代表的能力已从产品中移除,`executor`
> 字段连同散在领域层、worker 与两个前端组件里的 9 处分叉一并删除。升级时自动清理旧数据。
>
> 注意别和**定时任务的 webhook 触发器**搞混——那个仍然存在,是「外部 POST 进来触发工作流」,
> 与「发布到 webhook」是相反方向的两件事。

平台元数据里还有 `title_max`(抖音 30 / 小红书 20 / 视频号 16 / B站 80,创建任务时即校验)、
`short_title`(视频号需要)、`PLATFORM_ALIASES`(接受"抖音"/"b站"/"xhs"/"视频号"等中文别名)。

## worker 协议(后端 ↔ 桌面执行器)

执行器是个没有用户会话的 Node 进程,走 `/api/publish/worker/*`。这条通道**要带共享密钥**
(`X-Mosael-Worker-Key`,由 `require_worker_key` 校验)—— 「只监听 127.0.0.1」挡不住浏览器:
用户随便打开一个网页就能 POST 到本机。真正把执行器和网页分开的是那把密钥(见
`backend/app/core/worker_key.py`)。后端每次启动写进数据目录(0600);跨机部署时两边配同一个
`MOSAEL_WORKER_KEY`。

| 端点 | 用途 |
| --- | --- |
| `POST /worker/claim` | 认领最老的 pending 任务并原子翻成 running。带上执行器身份(`worker`),排除**任何执行器**正在跑的账号 → 同账号串行 |
| `PATCH /worker/report` | 回报富状态:`pending/running/success/failed/login_required/waiting_manual/permission_required/blocked/cancelled`(权威清单在 `domain/publish.TASK_STATUSES`,`report_task` 按它校验)。`success` 时带上 `post`(见下) |
| `POST /worker/claim-check` | 认领一个待复检登录态的账号 |
| `POST /worker/mark-due` | 开机全量巡检:把所有账号标记待复检 |
| `PATCH /worker/account` | 回写 `binding_status` / `last_error` / `profile_name`(平台侧昵称) |
| `POST /worker/heartbeat` | 30s 心跳,前端据此显示执行器在线 |

任务富状态会同步映射到任务总线的 `job`,并产生站内通知(成功/失败/需重登/被拦截…)。
**已取消的任务不给后到的回报复活**(`report_task` 里的规则)。

### 发出去的那条作品(`post`)

发成功时,任务记下这条作品在平台上的 ID 与链接(`publish_tasks.post`:`platform / post_id /
url / ids / published_at`),之后按作品 ID 查数据(TikHub 之类)就靠它。任务列表接口、job 结果
(工作流发布节点的 `post_id` / `post_url` 输出)、智能体的 `list_publish_tasks` 都能读到。

ID 是执行器从**平台自己的发布接口的响应**里读的(`electron/publish/publishedPost.ts`):
点提交前开始监听那一个接口,等到平台确认后停。读原文而不是 JSON.parse —— 抖音 / TikTok
的 19 位 ID 过一次 JS 数字就错了;每个平台的 ID 都有形状校验。读不到就是空 `post_id`,不编。
YouTube 另有一路:详情页上的 youtu.be 链接(适配器早就在读,用来认「这一支」)。

监听用的是上传视频时已经 attach 的 debugger,只在「提交 → 等确认」这一段 `Network.enable`,
停下就 `Network.disable` —— 不违反下面「不常驻 CDP」那一条。

> 各平台发布接口的地址与字段来自它们的网页端在用的那一版;平台改版后读不到时,执行器日志里
> `runTask post:` 那一行会列出截到了哪些响应、读出了什么,照着改 `POST_SOURCES` 即可。

### 多个执行器

支持,而且**必须靠身份区分**。回收悬挂任务有两条判据:

1. **「这个账号不在我当前在跑的集合里」** —— 只有**认领者**说了才算数,所以它只作用于
   `claimed_by` 等于自己的任务。拿自己的集合去判别人的任务,结论必然是"孤儿",于是两个
   执行器会互相把对方正在跑的任务标成失败,而错误文案还写着「请到平台确认是否已发布」。
2. **「多久没动静了」**(`STALE_RUNNING_MINUTES`)—— 这条是全局的,而且必须是:执行器彻底
   死掉之后没人再来认领它的任务,只有这条能把它们收回来。

执行器的身份跨重启稳定(`userData/publish-worker.id`,可用 `MOSAEL_WORKER_ID` 覆盖 ——
容器里数据目录常常是临时的)。**稳定是必需的**:重启后第一拍要认出自己那些没跑完的任务,
那正是判据 1 存在的理由。不报身份的老执行器行为不变(单执行器部署)。

回收一律置 `failed` 而不是重排:任务可能其实已经发出去了,重排会造成重复投稿。

## 账号矩阵

账号矩阵已从发布页抽离到独立的**「浏览器池」tab**(见 [ARCHITECTURE.md](ARCHITECTURE.md) 的 `browser/` 子系统):
发布账号 = 挂了平台的浏览器档案(`publish_accounts.profile_id`),与不挂平台的通用档案同屏管理。
发布页现在只做发布本身(发布记录 + 新建发布),账号的「增」和「管」都归口浏览器池。

- 每账号一张卡:平台、登录态徽标、平台昵称、上次检测、最近错误、登录/复检、启停开关、右键重命名/删除。
- **登录会话持久化**:每发布账号一个 Electron `persist:mosael-<accountId>` 分区(`~/Library/Application Support/Mosael/Partitions/`),重启不掉登录——这是"睡一觉起来照常自动发"的基础;账号并入浏览器池时**沿用这个既有分区**,登录态不丢。通用档案则用 `persist:pool-<id>`。
- **账号归人,默认私有**:发布账号是某人在平台上的登录态,建的人就是主人(`owner_user_id`),默认只有他自己
  看得见、用得上;要给同事用,由主人在卡片上共享到工作区(账号和它的浏览器档案一起共享、一起收回,见
  `domain/sharing`)。**私有账号只有主人和被共享到的人能用来发布** —— 在 `publish.start_publish` 这一处查,
  发布页、工作流发布节点、智能体 `publish_asset` 卡都经过它,拒绝时回一句说清怎么办的话
  (`shareErr_notUsable_publishAccount`)。谁在发:发布页是当前用户;工作流是这次运行的操作人,定时任务 /
  webhook 触发的运行记在**任务主人**头上;确认卡是批准它的人。执行器认领的是建任务时已经过闸的任务,不再重查。
  详见 [PERMISSION_MODEL.md §3.6](PERMISSION_MODEL.md)。
- **登录态复检**:执行器空闲时后台静默巡检(bound/login_required 超过 12h 或 unknown 即到期),把 UI 拉回真实状态。手动「复检」把账号打回 `unknown` 让下一轮立刻认领。

### checking 卡死的自愈(踩过的坑)

账号被翻成 `checking` 后,若执行器中途崩溃/出错,它**不在任何认领条件里**,会永久卡死。三重保险:

1. 后端 `claim_check` 把**超过 10 分钟仍是 checking** 的账号视为悬挂,重新认领;
2. 执行器复检的 catch 里把账号翻回复检前的状态,绝不留在 checking;
3. 「复检」按钮在 checking 态**不禁用**,作为手动逃生口。

---

## ⚠️ 内嵌浏览器的硬约束(改动前必读)

这两条是付出真实调试代价换来的,违反会立刻表现为"页面打不开 / 点登录卡死"。

### 1. 禁止给账号视图常驻 attach CDP debugger

曾为反检测用 `wc.debugger.attach("1.3")` + `Page.enable` + `Page.addScriptToEvaluateOnNewDocument`
注入 navigator 补丁。结果:**bilibili / 小红书 / 视频号这类重前端 SPA 渲染直接坏掉、页面空白、`loadURL` 长时间不 resolve**。
单变量 A/B 确认:关掉 debugger 后登录页正常渲染出二维码与表单。前身项目从没这东西,所以"原来都能打开"。

**反检测只保留不需要 debugger、不破坏渲染的两条**(已验证 `navigator.webdriver=false`、UA 无 Electron):

- 引擎层:`app.commandLine.appendSwitch("disable-blink-features", "AutomationControlled")`(`electron/main.cjs`)
- UA 层:`platformUserAgent()` 去掉 UA 里的 `Electron/x.y.z` 标识(`accountViews.ts`)

debugger 只允许 **文件上传时按需 attach**(`pageDriver` 的 `DOM.setFileInputFiles`,JS 无法给 file input 赋值),用完不常驻。

### 2. `openLogin` 里登录导航必须 fire-and-forget

`await driver.goto(loginUrl)` 会等**整页加载完**才返回 → IPC 不 resolve → 登录按钮一直转
(重站 + 后台巡检争用时实测 18s)。正确做法:`views.show()` 亮出视图后 `void driver.goto(...)` 立即返回,
poll 循环接管登录态判断。改后登录 IPC **8ms** 返回,视图立刻显示并随加载出二维码。

### 3. 看门狗与后台巡检的固有慢

`pageDriver.goto` 的 `loadURL` 有 45s 看门狗、`evaluate` 有 20s 看门狗(老版无超时,靠自然 resolve)。
**后台巡检**(`checkAccountStatus`)在视图 **不 show、零尺寸** 的状态下加载,Chromium 会节流隐藏视图,
重站可能很慢甚至撞 45s——这是隐藏视图的固有特性,不是 bug;**前台登录**(视图 show)则正常。

## 调试

日志:`~/Library/Application Support/Mosael/logs/publisher.log` —— 认领、runTask 各步、goto(含 loaded/timeout/rejected)、
checkLogin 结果、复检、回报,以及所有原本会被静默吞掉的 catch,全部有记录。

> **观测器效应警告**:用 `--remote-debugging-port` 起 App 会与 `wc.debugger` 争用,把 `sendCommand`
> 拖慢到 20+ 秒,足以掩盖或伪造时序问题。**别用它测 debugger/加载时序相关的东西**。

## 自动发布的串法

发布节点可以挂进工作流:`开始 → 导出时间线 → 发布`(`publish` 节点引用 `account_id` + `{{export.asset_id}}`),
再由定时任务(interval/daily/weekly/webhook)触发 → 全自动"剪辑成片 → 分发到矩阵账号"。
定时触发的运行替**任务主人**发:图里引用的账号得是主人自己的、或共享给了工作区的,否则那一次运行带着
「这个发布账号属于别人且没有共享出来」失败。节点的账号下拉只列当前用户能用的账号。
批量则是「工作流 × 参数行」,逐行跑、单行失败不打断整批。
