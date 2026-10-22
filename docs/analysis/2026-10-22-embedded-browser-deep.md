# 内嵌浏览器:深入一层(2026-10-22)

> 上一份 `2026-10-22-embedded-browser.md` 讲的是「四层结构 + 为什么这么选」;这一份进到**机制**:
> 一次任务/一次登录的完整时序、四套坐标系、视图状态机与不变量、每一处失败留什么证据、以及按
> 「改一处要动几个地方」排出来的风险表。结论在最后一节。

## 0. 一句话

它是一个**跑在原生视图里的、被主进程驱动的、按账号分区的浏览器**,外加一层「让位协议」处理原生视图
盖住 DOM 的老问题。可靠性不取决于某段代码,而取决于四条不变量有没有被守住(见 §4)。

## 1. 一次发布任务的完整时序(带文件/函数)

```
后端 /api/publish/worker/claim          (publish/worker.py 认领, 单 worker + 心跳)
  → Electron publishWorker.loop         (每 IDLE_MS 拉一批, running 集合去重)
  → views.setAccountPlatform(id, 平台)   (身份:见 §5, 必须在建视图之前)
  → views.configureAccount(id, proxy)   (session.setProxy; 记进 appliedProxy 防重复)
  → views.getDriver(id) → ensure(id)    (建 WebContentsView + PageDriver)
  → views.panelAttach(id, idleMs?)      (挂成右下角悬浮面板 = 参与合成 = 可信输入可用)
  → adapter.openCreatorPage → goto(...) (pageDriver.goto: 出站检查 + 45s 预算)
  → uploadVideo / fillTitle / fillTags  (pageDriver: 文件注入、可信输入、DOM 降级)
  → submit → waitResult                 (终态判定 = URL 模式 + 页面文案, 见 selectors)
  → backend.report(id, status, post)    (作品 id/url/发布时间写回后端)
  → finally: panelDetach / hide
```

关键点:**挂载与否决定能力**。
| 状态 | 有画面 | 可信输入(isTrusted) | 截图 | 布局视口 |
|---|---|---|---|---|
| 前台(visibleId) | ✅ | ✅ | ✅ 原生 | 窗口内容区(让位后) |
| 悬浮面板(panels) | ✅ | ✅ | ✅ | 1280×800 × zoom |
| 后台(detached) | ❌ | ❌ | 临时挂窗口外再截 | 0×0 或上次的 |

「后台视图不出帧」是 Electron 的事实(见 `withPageOnSurface` 的注释),不是我们能绕的;所以截图前要
**临时挂到窗口外负坐标**、并按本来该有的宽度排版,截完摘掉、尺寸与缩放还原。

## 2. 四套坐标系(这是最容易错的地方)

| 坐标系 | 谁在用 | 换算 |
|---|---|---|
| **页面 CSS 像素** | `getBoundingClientRect`、`innerWidth` | 基准 |
| **视图 CSS 像素** | 面板里页面被 `setZoomFactor(z)` 缩放 | `视图px = 页面px × z`,`z = 视图宽 / 1280` |
| **窗口 DIP** | `view.setBounds()`、`sendInputEvent`(面板/前台) | `DIP = CSS × hostZoom`,`hostZoom` = 主窗口缩放(渲染层「视图→放大/缩小」) |
| **屏幕点** | `screen.getCursorScreenPoint`、Computer Use 光标提示 | `屏幕 = 窗口内容原点 + DIP` |
| **物理像素** | `capturePage`(Retina 2x) | `物理 = CSS × deviceScaleFactor` |

已经踩过的三个坑,一一对应:
1. **Computer Use 点击脱靶**(点击全偏到左上角):`capturePage` 给 1600×1136(2x),而 `sendInputEvent`
   要的是 **CSS** 800×568 → 现在截图在 Electron 里先缩回窗口 CSS 尺寸(见 `captureMosaelWindow`);
2. **面板里可信点击脱靶**:面板缩放到 0.3,`humanClickAt` 里 `× getZoomFactor()` 才对得上
   (pageDriver 的注释写着「实测:不乘 zoom 完全脱靶」);
3. **顶栏压住网页**:渲染层报的是 CSS 像素,`setBounds` 要 DIP,`toDip` 统一在**那一下**换算
   (x/y 向上取整、右下向下取整 —— 宁可窄半像素,也不压住外壳的边)。

**规矩**:只有 `toDip` 和 `humanClickAt` 两处允许出现 `× zoom`;别处再出现一次,就是下一次脱靶。

## 3. 视图状态机

```
                 show()                        panelAttach()
  detached ──────────────► foreground ──────────────► panel
     ▲                        │  ▲                      │
     │      hide()            │  │  show()              │ panelDetach()
     └────────────────────────┘  └──────────────────────┘

  foreground/panel 都可以被「让位」临时挪开:
    · inset(左/右)  → 页面列表、顶栏工具侧栏:视图收窄,页面照常排版
    · off-window    → cover(列表在画面上展开) / overlay(整窗浮层):挪到窗口外,照常出帧
    · hidden        → region(框选截图):setVisible(false),只藏不摘(避免揭开闪旧帧)
```

**不变量**(写下来是因为改坏它们不会报错):
1. 一个账号同时最多**一个**前台视图(`visibleId`),它是「授权现场」;
2. `panels` 里最多 **4** 个挂载视图(超额不挂、任务照跑);
3. 一个会话最多 **10** 个页面(`MAX_PAGES`);关当前页落到相邻页;
4. `applyPanelZoom` 只对**非前台、且已挂载**的视图设缩放;前台视图的缩放由宿主管理;
5. 音频:后台页面一律 `setAudioMuted(true)`;只有「前台」或「面板且用户点过喇叭」才有声;
6. 一个分区(session)上同一时刻只允许一个会话(租约,见 §4)。

## 4. 会话语义与所有权

- **分区 = 档案**:`persist:<PARTITION_PREFIX>-<accountId>`(发布账号)/ 池档案显式分区 /
  `ephemeral-*`(临时,内存态)/ `persist:rpa-*`。cookie 与服务端登录态就是「这个账号」。
- **租约**:同一分区同一时刻只给一个 owner;别人占着回 `browserErr_profileBusyInUse`,现在会说清
  「被谁的会话占用、开了多久」(P4)。这轮真机上卡住我们的正是它。
- **前台单槽**:登录、待确认现场、发布任务都抢同一个可见位;被别的账号占着时 `publishErr_foregroundBusy`。
- **迁移事故(这轮的正主)**:库里同一个账号出现过两份分区 —— 登录落在 `persist:mosael-<accountId>`,
  而池档案的 `partition` 还指着历史前缀 `persist:openstudio-<accountId>`。表现极具误导性:
  卡片显示「已登录」、点「打开」也是登录态,但**智能体经池开会话**打开的是另一份没有登录的分区。
  修法:`_migrate_bound_profiles_use_the_account_partition`(幂等)把绑定账号的档案改回规范分区。

## 5. 身份:四层叠加,必须自洽

1. **UA**(`view-identity.cjs`):`chrome` 档 = 洗掉 `Electron/x` 与应用名 token;`electron` 档 = 原样;
2. **CDP `Emulation.setUserAgentOverride`**:`chrome` 档才发,一次覆盖 UA 头 + `Sec-CH-UA` +
   `navigator.userAgentData`(**只洗 UA 会自相矛盾**:UA 说 Chrome、brands 只有 Chromium ——
   视频号扫码成功、`sessionid` 种下、随即被判无效,就是这一条);
3. **preload 指纹**(`account-view-preload.cjs`):`webdriver=false`、`window.chrome`、`languages`、
   Chrome 真实 5 条 PDF Viewer plugins;WebGL / permissions **不伪造**(伪造才是破绽);
4. **权限白名单**(`web-permissions.cjs`):内嵌网页默认全拒,只放全屏 / 写剪贴板 / 持久存储 /
   `storage-access`;外部协议只给应用自己的页面,且只 `mailto:`;`weixin://` 这类**登录协议**另有一条
   白名单(见 §6)。

**判据**:洗或不洗,不是「哪家反欺诈更凶」,而是「洗完之后 UA 与 client hints 还一致吗」。

## 6. 站点流程差异(真 Chrome 有、Electron 没有的那些)

| 差异 | 现象 | 我们的处置 |
|---|---|---|
| 外部协议 `weixin://` 不被实现 | 点「微信快捷登录」没反应,无任何错误 | 白名单 scheme → `shell.openExternal`(唤起微信客户端) |
| OAuth 回调落在跨站 iframe | 「允许」之后回登录页 | **不能**把回调提顶层(它依赖 `window.parent`,提上去就是白页);真正原因在身份 |
| `capturePage` 物理像素 / `sendInputEvent` CSS | 点击脱靶 | 截图归一化到窗口 CSS 尺寸 |
| 未挂载视图不出帧 | 截图为空 | 临时挂窗口外再截 |
| WebAuthn 无 hybrid(扫码)通道 | 站点等 passkey 一直转 | preload 里当场 reject,逼它回退密码 |
| 权限默认放行(Electron 原生行为) | 与 Chrome 不同 | 我们收紧成白名单(有意为之) |

## 7. 观测性(这轮补的)

- `plog`:自由文本,进程内;
- **`browser-trace.log`**(`trace.cjs`):一行一个 JSON,`scene` ∈ {login, action, net, net-probe};
  URL 只留 origin+path(查询串里的 code/state/ticket 不落盘),cookie/token/password 一类键打码,
  超 2MB 轮转;
- 登录状态机(`loginPhase.cjs`):`opening → waiting → verifying → bound / failed(timeout|dismissed|
  stopped|error)`,每次变化一条;
- 网络探针(`netTrace.cjs` + preload 里的 `mosael:net-probe`):`channels.weixin.qq.com` /
  `open.weixin.qq.com` 的**请求状态 + 响应体前 200 字** —— 登录接口的 `errCode` 只有页面自己看得见。

## 8. 失败分类学(遇到问题先查这张表)

| 现象 | 先看哪里 | 常见原因 |
|---|---|---|
| 卡片「已登录」但打开是登录页 | 分区名与档案 `partition` 是否一致 | 历史前缀残留(本轮事故) |
| 登录成功又退回登录页 | `browser-trace.log` 的 net-probe | 身份自相矛盾 / 会话被判无效 |
| 点了没反应 | 是否有外部协议导航 | `weixin://` 这类被丢 |
| 上传完成但按钮点不动 | `did not confirm publish` + 截图 | 选择器/文案失配(站点改版) |
| 截图空白 | 视图是否挂载 | 未参与合成 |
| 点击偏左上角 | 是否乘了 zoom / 是否 Retina | 坐标系混用 |
| 「该档案正被占用」 | 谁占着(现在会写出来) | 上一会话没收尾 |

## 9. 风险与优先级(按「改一处要动几处」排)

| 级别 | 问题 | 为什么危险 | 做法 |
|---|---|---|---|
| **P0** | 身份与分区都是「一次性配置」 | 改一次就悄悄废掉所有已登录账号(本轮两次) | 身份写进**档案**、分区只由账号算;迁移幂等;登录失败自动取证 |
| **P1** | 站点契约散在适配器 | 平台改版即断,且断在「看起来成功」的地方 | 契约数据化 + 每日冒烟(只开创作页断言关键选择器) |
| **P2** | 让位协议手工登记 | 新浮层漏接就是「点不到」 | 声明式让位 API |
| **P3** | 登录是一堆 if | ✅ 已做(状态机 + 取证) | — |
| **P4** | 所有权只给一句报错 | ✅ 已做(谁/多久) | 再加「等待/抢占/取消」 |
| **P5** | 坐标换算散落 | 每处自己乘一遍 = 三次错的机会 | 统一 `pageToDip` / `dipToPage` |
| **P6** | 面板缩放下的交互 | 归入 P5 | — |
| **P7** | 观察性 | ✅ 已做(trace + net-probe) | 把登录/动作的耗时也量化 |

## 10. 结论

- **架构没问题**:原生视图 + 主进程执行是唯一能同时满足「真实登录态、可信输入、截图、代理、下载」的
  做法;换来两项固定成本:**原生盖 DOM**(让位协议)与**身份要自己维护**(四层叠加)。
- 这轮所有事故都落在同一类:**某个「全局旋钮」被当成可以随手整体调整的东西** ——
  分区前缀、UA、(曾经的)导航拦截。它们的真实语义都是「按账号/按站点」。
- 因此下一步不是继续打补丁,而是把这两件事**结构化成数据**:身份进档案、分区只由账号算、
  登录失败自动留证。做完之后,再遇到「某家登不上」应当能在一份日志里看到答案,而不是像今天这样
  靠人回忆「之前是好的」。
