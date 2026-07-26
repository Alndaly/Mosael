# 发布与账号矩阵

自媒体矩阵运营是核心卖点:多平台账号集中管理 + 成片自动分发。

## 两类执行器

平台注册表在 `backend/app/domain/publish/__init__.py`(`PUBLISH_PLATFORMS`),每个平台声明 `executor`:

| executor | 平台 | 怎么执行 |
| --- | --- | --- |
| `local` | `folder`(投递到本地目录)、`webhook`、`mock` | 后端线程内直接完成 |
| `browser` | `douyin` `bilibili` `xiaohongshu` `weixin-channels` | **桌面端内嵌浏览器**驱动真实平台页面 |

`browser` 类平台的任务后端只负责入队(`status=pending`),真正干活的是 Electron 里的发布执行器。
所以**网页版无法发布到真实平台**——UI 会提示"需要桌面端"。

平台元数据里还有 `title_max`(抖音 30 / 小红书 20 / 视频号 16 / B站 80,创建任务时即校验)、
`short_title`(视频号需要)、`PLATFORM_ALIASES`(接受"抖音"/"b站"/"xhs"/"视频号"等中文别名)。

## worker 协议(后端 ↔ 桌面执行器)

执行器是个无 token 的 Node 进程,走 `/api/publish/worker/*`(**免鉴权,localhost 信任边界**,与老版一致):

| 端点 | 用途 |
| --- | --- |
| `POST /worker/claim` | 认领最老的 pending 任务并原子翻成 running(排除正在跑的账号 → 同账号串行) |
| `PATCH /worker/report` | 回报富状态:`pending/running/prepared/success/failed/login_required/waiting_manual/permission_required/blocked/cancelled` |
| `POST /worker/claim-check` | 认领一个待复检登录态的账号 |
| `POST /worker/mark-due` | 开机全量巡检:把所有账号标记待复检 |
| `PATCH /worker/account` | 回写 `binding_status` / `last_error` / `profile_name`(平台侧昵称) |
| `POST /worker/heartbeat` | 30s 心跳,前端据此显示执行器在线 |

任务富状态会同步映射到任务总线的 `job`,并产生站内通知(成功/失败/需重登/被拦截…)。
**已取消的任务不给后到的回报复活**(`report_task` 里的规则)。

## 账号矩阵

账号矩阵已从发布页抽离到独立的**「浏览器池」tab**(见 [ARCHITECTURE.md](ARCHITECTURE.md) 的 `browser/` 子系统):
发布账号 = 挂了平台的浏览器档案(`publish_accounts.profile_id`),与不挂平台的通用档案同屏管理。
发布页现在只做发布本身(发布记录 + 新建发布),账号的「增」和「管」都归口浏览器池。

- 每账号一张卡:平台、登录态徽标、平台昵称、上次检测、最近错误、登录/复检、启停开关、右键重命名/删除。
- **登录会话持久化**:每发布账号一个 Electron `persist:mibu-<accountId>` 分区(`~/Library/Application Support/mibu/Partitions/`),重启不掉登录——这是"睡一觉起来照常自动发"的基础;账号并入浏览器池时**沿用这个既有分区**,登录态不丢。通用档案则用 `persist:pool-<id>`。
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
单变量 A/B 确认:关掉 debugger 后登录页正常渲染出二维码与表单。老版 mibu-video 从没这东西,所以"原来都能打开"。

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

日志:`~/Library/Application Support/mibu/logs/publisher.log` —— 认领、runTask 各步、goto(含 loaded/timeout/rejected)、
checkLogin 结果、复检、回报,以及所有原本会被静默吞掉的 catch,全部有记录。

> **观测器效应警告**:用 `--remote-debugging-port` 起 App 会与 `wc.debugger` 争用,把 `sendCommand`
> 拖慢到 20+ 秒,足以掩盖或伪造时序问题。**别用它测 debugger/加载时序相关的东西**。

## 自动发布的串法

发布节点可以挂进工作流:`开始 → 导出时间线 → 发布`(`publish` 节点引用 `account_id` + `{{export.asset_id}}`),
再由定时任务(interval/daily/weekly/webhook)触发 → 全自动"剪辑成片 → 分发到矩阵账号"。
批量则是「工作流 × 参数行」,逐行跑、单行失败不打断整批。
