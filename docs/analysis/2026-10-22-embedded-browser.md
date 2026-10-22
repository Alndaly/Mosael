# 内嵌浏览器现状分析(2026-10-22)

> 触发:视频号登录连续三次回归(X 的 Turnstile 修复 → `weixin://` 被丢弃 → 回调提到顶层变空白页)。
> 这三件事都不是「某个小 bug」,而是这套内嵌浏览器的**结构性问题**在同一处冒出来。这份文档把它拆开看。

## 0. 一句话现状

内嵌浏览器不是「一个浏览器」,是**四层拼起来的执行环境**:原生视图(`WebContentsView`)当浏览器、
渲染层只画外壳、主进程是唯一执行者、站点知识散在适配器里。自动化有两条腿(DOM 事件 / 可信指针),
登录靠轮询堆判据,而**身份与指纹是一个全局开关** —— 这是目前最脆的地方,最近三次回归全出在这里或
它附近。

## 1. 四层结构

| 层 | 文件(行数) | 职责 | 决策点在哪 |
|---|---|---|---|
| 视图层 | `publish/accountViews.ts`(1514) | 会话(=视图)与页面(tab)两级、挂载/让位、面板几何、代理、下载、静音、外链协议 | 一个账号一个会话;前台单槽 |
| 驱动层 | `publish/pageDriver.ts`(1570) | `evaluate` / 选择器 / 文本匹配 / 可信指针 / 各种等待原语 | 每次交互都降级成什么 |
| 站点契约 | `publish/adapters/*` + `selectors.ts` + `platforms.ts` | 每个平台的入口、选择器、文案、上限 | 平台长什么样 |
| 执行循环 | `publishWorker.ts`(999) / `browserWorker.ts`(267) | 从后端 claim 动作 → 在视图上执行 → 回报 | 谁在什么时候能动这一页 |

三个**硬约束**贯穿全部设计,记住它们后面几乎所有怪设计都能解释:

1. **原生视图永远画在渲染层 DOM 之上**(Electron 的子视图合成顺序)。于是有了「让位协议」;
2. **只有被挂载(参与合成)的视图才有画面、才接受可信输入**。于是截图前要临时挂、面板上限 4 个;
3. **`sendInputEvent` 的坐标是 CSS 像素(受 zoomFactor 影响)**,而 `capturePage` 给的是**物理像素**。
   这两个单位在 Retina + 面板缩放(0.3)叠加时足以让点击脱靶 —— 我们踩过两次(Computer Use 的点击、
   面板里的 `humanClickAt`)。

## 2. 关键设计决定与代价

### 2.1 为什么是 `WebContentsView`,不是 `<webview>` / iframe
真实合成、真实输入、真实下载、真实权限、真实 WebAuthn —— 这些只有原生视图给得了;`<webview>` 已废弃,
iframe 受同源与 CSP 限制。**代价**是上面那条硬约束 1:它盖住一切 DOM。

### 2.2 分区即档案
`persist:mosael-<accountId>`(发布账号,前缀与后端 `PARTITION_PREFIX` 同一份常量);
池档案用显式登记的分区;RPA 会话用 `persist:rpa-*` / `ephemeral-*`(内存态)。
**代价**:登录态 = 这份分区里的 cookie + localStorage,「退出登录」只能靠清分区(`clearAccountData`),
平台自己的登出按钮不可靠(B 站只让当前页面失效)。

### 2.3 一个账号同时只一个会话 + 前台单槽
登录、待确认的现场、发布任务都抢同一个视图。于是有了用户会看到的
「该档案正被占用(同一时刻只允许一个会话)」。这是**有意的**,但 UX 上目前只有一句错误,没有
「谁占着、等多久、要不要抢」的选择。

### 2.4 让位协议(三种)
| 让位 | 用于 | 做法 |
|---|---|---|
| 让边距 | 页面列表、顶栏工具侧栏 | `shellInsetLeft/Right`,视图收窄,页面照常排版 |
| 挪到窗口外 | 页面列表在画面上变形、看大图浮层 | `OFF_WINDOW_REASONS`,照常出帧,揭开即回来 |
| 真藏起来 | 框选截图(渲染层铺冻结帧) | 只藏不摘,用完原样亮回 |

**成本**:每新增一个浮层都要接一次(`design/overlaysOverNativeViews.test.ts` 是那份清单)。
这是「原生视图 + DOM 外壳」这套架构的固定税。

## 3. 自动化执行模型

- 契约面:`PublishAdapter` 的 8 个方法(`openCreatorPage / checkLogin / uploadVideo / fillTitle /
  fillTags / submit / waitResult / knownPostId`)。所有平台行为都在这 8 个动作里。
- **点击三级降级**(这是经验堆出来的,每一级都对应一次真机失败):
  1. `pointerClickByText` —— 可信指针(`sendInputEvent`),依赖命中测试;面板挂载后才可用;
  2. `dispatchFullClickCss` —— 派发完整指针事件序列(`pointerdown`+`mousedown`+…),`isTrusted=false`,
     但**不依赖**命中测试。B 站「立即投稿」只挂 `pointerdown` 时,`el.click()` 毫无反应,这级能过;
  3. `clickCss` —— 兜底 `el.click()`。
- **输入**:`typeOrFill` 先真实按键(平台会审查 `isTrusted`),落不稳(自动补全/长度截断/富文本改写)
  再退回 DOM 事件 —— 「宁可 `isTrusted=false`,也不能把文案写坏」。
- **人味**:`humanClickAt` 有抖动、3–6 步移动、随机间隔。不是反检测,是因为逐点瞬移在部分站点上
  会被布局变化「吃掉」。
- **读**:`hasText` / `hasTextDeep`(穿 shadow DOM)/ `cssAttached` / `waitTextEnabledDeep` ……全是对
  站点 DOM 的**软契约**,平台改版即断。

## 4. 登录:轮询 + 判据堆叠

```
openLogin → configureAccount(代理) → 亮视图 → goto(loginUrl)
          → 每 5s 一次 adapter.checkLogin(),最多 10 分钟
          → 成功:回写 bound、自动收起视图;视图被用户收起 → 立刻停
```

`checkLogin` 的判据是**顺序堆叠**的:先判「当前在登录页」(有 `isLoginUrl` 的平台),再判
页面文案 / 文件 input,最后用**分区 cookie**(`session.cookies.get`)补一条与页面无关的正向信号 ——
YouTube 登完落在 `www.youtube.com` 而不是 Studio,只认创作页长相必错。

**问题**:这是一堆 if,不是一个状态机。失败时我们能留下的证据只有 「not logged in yet at <url>」
一行日志 —— 这次视频号就是因此多花了两轮。

## 5. 身份与反检测:当前最脆的一层

三层叠加:

1. **UA**:`view-identity.cjs` 按平台决定 —— X/Twitter 如实声明 Electron(否则 Cloudflare Turnstile
   无限验证);其余平台给干净 Chrome UA(只抹 `Electron/x.y.z` 与应用名 token);
2. **preload 指纹**(`account-view-preload.cjs`):`navigator.webdriver=false`、`window.chrome`、
   `languages`、Chrome 真实的 5 条 PDF Viewer plugins;WebGL / permissions **不伪造**(伪造才是破绽);
   WebAuthn:没有平台认证器就当场 reject(hybrid 通道 Electron 做不出来,挂着就是永远转圈);
3. **权限白名单**(`web-permissions.cjs`):内嵌网页默认全拒,只放全屏 / 写剪贴板 / 持久存储 /
   `storage-access`。`openExternal` 只给应用自己的页面,且只 `mailto:`。

**结构性矛盾**:同一个客户端,两套反欺诈的期待相反(X 要「诚实的 Electron」,国内平台要「正常的
Chrome」)。现在只有**平台级一个维度**,而真实世界的影响因素至少还有:站点、流程(登录/发布/阅读)、
是否需要过 Turnstile。这就是这轮连续三次回归的土壤。

## 6. 与真 Chrome 的行为差异(这几轮全踩在点上)

| 差异 | 现象 | 处置 |
|---|---|---|
| 外部协议(`weixin://`)Electron 不实现 | 点了没反应,无任何错误 | 白名单 scheme → `shell.openExternal` |
| 跨站 iframe 里的 OAuth 回调 | 「Allow 之后回登录页」 | **不能**把回调提顶层(它依赖 `window.parent`)—— 真正原因是身份 |
| `capturePage` 物理像素 vs `sendInputEvent` CSS 像素 | 点击全偏到左上角 | 截图先缩回窗口 CSS 尺寸 |
| 未挂载视图不出帧 | 截图空白 | 截图前临时挂到窗口外再摘 |
| WebAuthn 无 hybrid 二维码通道 | 站点一直等 passkey | preload 里当场 reject,逼站点回退密码 |
| 权限默认放行(Electron) vs 我们的白名单 | 与 Chrome 行为不同 | 有意为之:内嵌的是任意第三方网页 |

## 7. 脆弱点排序(建议按这个顺序处理)

| 优先级 | 问题 | 建议 |
|---|---|---|
| **P0** | 身份是平台级单值,失败无证据 | ①身份升级成「站点档案」(host → 身份 + 是否覆盖 client hints),②登录失败时自动取证:URL 链、关键 cookie **名**(不记值)、最后 3 次 `checkLogin` 判据结果、一张截图,落进 `browser-trace.log` 一处;**③已发现并修掉的实例**:同一个账号存在两份分区 —— 登录落在 `persist:mosael-<accountId>`,而池档案还指着历史前缀 `persist:openstudio-<accountId>`,于是「卡片说已登录、打开也是登录态,智能体开会话却让他登录」。修法:`_migrate_bound_profiles_use_the_account_partition` 把绑定了账号的档案改回规范分区(幂等) |
| **P1** | 站点契约散落、改版无感知 | 契约集中成数据(`contracts/platforms/*.json`),加「每日冒烟」:只开创作页,断言关键选择器还在;断了自动开卡或用 Computer Use 兜底 |
| **P2** | 让位协议手工登记 | 抽成统一的「宿主要在这一块画东西」声明 API,浮层声明区域 → 视图自动让位/挪开,而不是每个浮层各改一处 |
| ~~**P3**~~ | 登录是一堆 if | ✅ 已做:`publish/loginPhase.cjs`,`opening → waiting → verifying → bound / failed(timeout/dismissed/stopped/error/switched)`,已接进 `openLogin` |
| ~~**P4**~~ | 会话所有权只有一句报错 | ✅ 已做:池档案被占用时说出「谁占着、开了多久」(`browserErr_profileBusyInUse` + `browserHolder_*` 文案) |
| **P5** | 坐标系换算散落 | 统一 `pageToDip` / `dipToPage` helper,把 zoomFactor、Retina 缩放、窗口内容原点三件事收在一处 |
| **P6** | 面板缩放(0.3)下的交互 | 现在靠 `getZoomFactor()` 现算;归入 P5 |
| ~~**P7**~~ | 观察性差 | ✅ 已做:`publish/trace.cjs` 写 `<userData>/browser-trace.log`(一行一个 JSON、URL 只留 origin+path、凭据键打码、2MB 轮转),登录状态机与每个浏览器动作都记一条 |

## 8. 结论

- 这套架构**选对了**:原生视图 + 主进程执行是唯一能同时满足「真实登录态、可信输入、可截图、可代理、
  可下载」的做法;换来的是「原生盖 DOM」和「身份得自己维护」两项固定成本。
- 最近几次回归不是架构错,而是**我们把两个全局旋钮(身份、导航拦截)当成了可以随手整体调整的东西**,
  而它们的真实语义是「按站点/按流程」。P0 就是给这两件事加维度、加证据。
- 还有一条经验值得写进规矩:**登录/授权流程里每一步的上下文(iframe、opener、referrer、scheme)都是
  流程的一部分**,挪动它之前先确认它依赖谁 —— 视频号那次空白页就是把它挪走了。
