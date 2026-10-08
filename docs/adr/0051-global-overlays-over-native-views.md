# ADR 0051:工作台 / 内嵌浏览器在前台时,全局浮层怎么让

## Status

Accepted — 2026-10-09,已实现(见文末「实现记录」)。2026-10-08 全项目体检桌面壳那一路起草(发现 EL-04);草稿里的七条待拍板和
「弹窗开着时提示条点不到」那一条由维护者 2026-10-09 **全部按推荐拍板**(拍板页 D33–D40,对照见「拍板记录」)。

## Context

### 原生视图盖在一切 DOM 上

内嵌浏览器(发布账号、浏览器池档案、RPA / 智能体会话)和 ComfyUI 工作台的画布都是挂在主窗口上的 `WebContentsView`。原生视图永远画在
主窗口网页(Mosael 的界面)上面,z-index 管不到它。所以界面里任何一块落在视图那片区域里的 DOM,不管 z 多高,都看不见、点不着。

此前已经有几套各管一摊的做法,都对,本 ADR 原样留着、在它们上面搭:

| 机制 | 在哪 | 管什么 |
| --- | --- | --- |
| 窗口外壳(`APP_CHROME`,z-200) | `components/ui/appChrome.ts`;内嵌浏览器的顶栏 `PublishViewBar`、页面列表、侧栏,工作台的顶栏和右边那一列 | 外壳画在视图**旁边**(视图按外壳让出的宽度摆,见 `electron/publish/accountViews.ts` 的 `foregroundBounds`),不是上面 |
| `ChromeAboveDialogs` | 同上 | 外壳挂到 body 末尾:拖拽区按文档顺序收集,排在已经开着的弹窗后面才拖得动窗口 |
| 让开 + 冻结帧(`nativeViewAside`) | `components/ui/nativeViewAside.tsx`;看大图、工作台里的模型详情(`OverChromeModals`,z-205) | 先在原处铺一张网页此刻的画面,再请主进程把视图挪到窗口外;收起时反过来。网页一直在出帧,画布不闪 |
| 浮层视图(`FloatLayer`) | `electron/publish/floatLayer.ts`、`frontend/float-layer.html` | 外壳里的悬停说明画在一块透明的原生视图上,压在网页视图上面;不拿焦点 |

问题是:**这几套都是「用到的组件自己记得接」**。没接的那些,原生视图一亮着就全看不见 —— 而它们大多不是用户在视图里点出来的,
是系统、后台、快捷键从外面开的。

### 实测(隔离 Electron,2026-10-08;截图见体检报告的 EL-04)

- **点系统通知「需要登录」「需要你处理」**(`system/notify.ts` → `mosael:open-tasks`):任务中心在 DOM 里开着,内嵌浏览器亮着时整块在
  网页视图底下;工作台里被画布和右边那一列盖住。窗口被唤到前台,用户看不出任何变化;按「返回 Mosael」之后它还开着。
- **提示条**(Sonner,`app/App.tsx` 的 `AppToaster`,右下角):把一个文件拖到 Dock 图标上导入失败,「1 个文件导入失败」在 DOM 里,屏幕上
  看不见。写请求的错误都报成提示条(`createAppQueryClient(... toast.error ...)`),内嵌浏览器亮着时这些错误全部丢失。
- **深链**(`mosael://open?view=settings`):工作台开着时路由在底下切成 `#/settings`,工作台纹丝不动;按「返回 Mosael」之后才落到设置页。
- **⌘K**:`CommandPalette.tsx` 在 document 上听 ⌘K;在地址栏、工作台右列的输入框里按 ⌘K,命令面板 z-50 开在视图底下,焦点圈套把之后
  敲的字收进一个看不见的搜索框,键盘像是坏了。在网页里按 ⌘K 则什么都不发生(键盘在网页那边)。
- **全局确认卡**(`ConfirmationCenter`,`fixed right-4 top-14 z-[60]`):没有对话面板接着的卡只在这里出现;内嵌浏览器、工作台亮着时它在
  视图或右列底下,智能体等着人拍板,人看不见卡。
- **免提浮标**(`VoiceDock`,z-70):拖到哪就在哪,落在视图那片区域里就看不见、点不着。
- **弹窗开着时提示条上的按钮**(和原生视图无关,全应用的老问题):Radix 的模态弹窗把 body 设成 `pointer-events: none`,Sonner 的提示条
  跟着继承 —— 点「查看」落在弹窗的遮罩上,弹窗当成「点了外面」关掉,「查看」没打开。

## Decision

**一条规矩:原生视图在前台时,应用级的浮层要么画在看得见的地方(外壳里、浮层视图上),要么请视图让开,要么先收起视图再走;
不许画在视图底下。** 一处登记(`components/app/overNativeView.tsx` 的 `GLOBAL_OVERLAYS`),一道棘轮盯着(`design/overlaysOverNativeViews.test.ts`)。
内嵌浏览器和工作台是同一个视图机制,同一条规矩(D38)。

「原生视图在不在前台」由一处说:`lib/nativeView.ts`(主进程推的 `onViewState`,全应用只订一次)。

### 1. 四种处理,按浮层的性质分

| 性质 | 处理 | 归到这一类的 |
| --- | --- | --- |
| 要人马上看、要操作的(弹出层、对话框、命令面板) | **让开**(`aside`):挂在 `<OverNativeView>` 里 —— 里面的 Dialog / AlertDialog 抬过外壳(z-205)、开着时请视图让开(和看大图同一套 `nativeViewAside`);弹出层读同一个范围,抬到 z-210、自己请视图让开 | 任务中心、命令面板、配音库嗓子交给远端引擎那一问 |
| 后台冒出来的、常驻的 | **收进外壳**(`chrome`):外壳顶栏上留一个位(`ChromeStatusSlot`),收成一个小标;人点了才展开 | 确认卡、免提浮标 |
| 只是告知、几秒就走的 | **画在视图上面**(`float`):交给浮层视图画在网页上面,上面的按钮照样点得到 | 提示条 |
| 换地方的 | **先收起视图再走**(`leave`):`hideView`(和「返回 Mosael」同一下:视图还活着,工作台里没存的改动还在,不另弹确认) | 深链落地(邀请链接加入之后切工作区也是);命令面板、任务中心详情、确认卡上「去那里」的那几项 |

### 2. 提示条画进浮层视图(D33)

原生视图在前台、且没有让开时,`useToastMirror` 把 Sonner 那一整块(`<section>`)原样交给主进程的**提示条浮层视图**(`FloatLayer` 的
`toasts` 那一种,和悬停说明那块分开):视图的右下角就是窗口的右下角,浮层页照主窗口的样子把提示条贴着右下角摆(`--offset-*` 在 HTML 里
带着,`useToastClearance` 抬起的那一截跟着过去)。左上角按提示条摆满时的样子量(每条的 `--offset`、收着时露出来的几道边),不按动画
此刻走到哪儿量。DOM 里那份照常渲染、计时、给读屏念,只是透明。

**按钮点得到**:浮层视图上的那份只是照着画的样子。主进程在这块视图上听 `before-mouse-event`,把指针换算成主窗口的 CSS 坐标交回渲染层
(`toasts:pointer`):移进来 → 在 DOM 那份上发 `mousemove`,Sonner 照常展开、停住计时;移出去 → `mouseout`,收回;左键松开 → 按位置找到
落在哪条提示的哪个按钮上,点 DOM 里那一个。按位置找,不用 `elementFromPoint`:DOM 那份透明着,上面可能还压着弹窗的遮罩。

视图让开着(看大图、命令面板、任务中心开着)时窗口里看得见的全是 DOM,提示条回到 DOM 里画。提示条让开贴底输入区的那条规则
(`data-toast-avoid`)原样留着;视图在前台时页面整块在网页底下,只认外壳里的输入区(工作台右边那一列的智能体输入框)。

### 3. 确认卡不自己跳出来

确认卡是后台冒出来的,自动让开会在用户浏览网页、登录、看画布时突然把画面冻住、盖上一张卡。所以原生视图在前台时,外壳顶栏上亮一个
「N 个请求等你确认」的小标;点了才让开、在右上角展开卡片列表(z-210,挂 `APP_CHROME`);收起或拍完,视图回来。只剩执行失败、留着读的
那几张时不亮「0 张」,等视图收起再摆出来。视图不在前台时照旧右上角直接摆卡。

### 4. 系统通知、⌘K、免提浮标

- **系统通知点进来**(D34):让开、打开任务中心。用户点通知就是要看那件事;收起视图会打断正在登录、正在看的网页。
- **⌘K**(D36):照常能用,开着时视图让开。网页在前台时键盘在网页那边:主进程在前台网页的 `before-input-event` 里认出 ⌘K / Ctrl+K
  (不带 ⇧ ⌥),截下来、把键盘交回 Mosael、发 `mosael:command-palette`;渲染层落在看不见的地方的按键照旧吞掉,⌘K 除外。这会占掉网页
  自己的 ⌘K —— 维护者接受。面板里选了去别处的一项,先收起视图再走(换主题这种人还在原处的不收)。
- **免提浮标**(D37):收成外壳顶栏上的一个图标,同一个免提循环,说话照常;视图收起,回到原来拖到的位置。

### 5. 弹窗开着时提示条点得到(D40)

提示条外面包一层 `APP_CHROME`:它和窗口外壳是同一种东西 —— 盖在弹窗上面、却在弹窗外面。`[data-app-chrome]` 放开指针,
`keepOpenOnAppChrome` 让点它不算「点了弹窗外面」,`installAppChromeGuards` 让焦点进出它不被弹窗的焦点圈套拽回去。全应用都生效,
和原生视图在不在前台无关。

### 6. 棘轮(D39)

`design/overlaysOverNativeViews.test.ts` 盯三件事:

1. 挂在应用根上(`App.tsx`、`AppShell.tsx`)、会浮起来的组件(Radix 的弹层、portal、`fixed` 加一层 z),要么在 `GLOBAL_OVERLAYS` 登记了
   处理,要么在测试的 `NOT_GLOBAL` 里写明为什么不用管(外壳本身、只从被外壳盖住的顶栏 / 侧栏点出来的、开发专用的……);
2. 桌面壳从外面派的 window 事件(`electron/preload.cjs` 里 dispatch 的),听它的模块都登记了 —— 它们正是在原生视图亮着时被叫起来的;
3. 登记的处理真接上了:`aside` 在宿主里包在 `<OverNativeView>` 里,`chrome` 住进 `ChromeStatusSlot`,`float` 走 `useToastMirror`,
   `leave` 调 `leaveNativeView`;提示条外面包着 `APP_CHROME`。

行为由各自的 DOM 测试盯(任务中心、命令面板、确认卡、免提浮标、提示条、深链、`OverNativeView`),主进程那一半由
`electron/publish/floatLayer.test.ts`(提示条那一种、指针换算)和 `accountViewsPanels.test.ts`(⌘K)盯。

## 否掉的备选

- **只要有浮层开着就把视图藏起来**:最简单,但藏起来的视图揭开时会先闪一帧藏之前的画面(`accountViews.ts` 的 `ForegroundHideReason`
  注释),而且提示条这种每隔几秒就来一条的,会让网页来回闪。
- **全部画进浮层视图**:浮层视图刻意不拿焦点(`floatLayer.ts`),这样才不会把地址栏、网页里打的字抢走;命令面板、确认卡要键盘、要点击,
  放进去得重做一套焦点和无障碍,不值得。只让提示条这种按一下就完的进去(指针转交,不拿焦点)。
- **提示条在外壳顶栏下沿开一条带**:56px 高的顶栏放不下多条;**攒着等视图收起再弹**:写请求失败的提示晚到没意义。
- **系统通知点进来时收起视图**:会打断正在登录、正在看的网页。
- **原生视图在前台时 ⌘K 交给网页**:命令面板只能从顶栏按钮开,而顶栏被外壳盖着 —— 等于开不了。
- **各组件自己接(现状)**:看大图、模型详情接了,任务中心、提示条、命令面板、确认卡没接 —— 每加一个浮层就会再漏一次,体检里漏了五处。
- **把原生视图换成截帧流画进 DOM**:画面延迟、可信输入(`isTrusted`)没了,RPA 和发布都依赖后者(`accountViews.ts` 的 `PANEL` 注释)。

## Consequences

- 系统通知点进来、⌘K、确认卡在内嵌浏览器和工作台里都看得见了;写请求的错误不再悄悄丢;弹窗开着时提示条上的按钮点得到。
- 让开有代价:冻结帧期间网页照常出帧但看不见变化(那一刻用户在看浮层,可以接受);命令面板开着时画布是一张静止的图。
- 提示条在原生视图前台时,浮层视图那一块(提示条摆满时的范围,右下角一小块)接住指针:那几秒里点不到它底下的网页,和 DOM 里的提示条
  盖住页面一样。
- 网页自己的 ⌘K / Ctrl+K 在 Mosael 里用不了。
- 深链、命令面板里去别处的那几项会收起工作台 —— 视图留着,回来时没存的改动还在。

## 拍板记录(2026-10-09,维护者照推荐)

| 拍板页 | 草稿 | 定了什么 |
| --- | --- | --- |
| D33 | 待拍板 1 | 原生视图在前台时提示条画进浮层视图,看得见、按钮点得到。 |
| D34 | 待拍板 2 | 点系统通知进来:视图让开,打开任务中心。 |
| D35 | 待拍板 3 | 深链跳到别处:先收起前台视图再跳;工作台里没存的改动保留,不另弹确认。 |
| D36 | 待拍板 4 | ⌘K 照常能用,打开时视图让开。 |
| D37 | 待拍板 5 | 免提浮标在原生视图前台时收成顶栏上的一个图标,说话照常。 |
| D38 | 待拍板 6 | 工作台和内嵌浏览器用同一条规矩。 |
| D39 | 待拍板 7 | 上棘轮测试。 |
| D40 | (拍板时并入) | 任何弹窗开着时提示条上的按钮点不到(全应用的老问题),在这一篇里一起解决。 |

## 实现记录(2026-10-09,分支 feat/adr-0051-overlays-over-native-views)

**主进程 / preload**
- `FloatLayer` 多一种 `toasts`:不留余量;`onPointer` 时在视图上听 `before-mouse-event`,左键松开 / 移动 / 移出换算成主窗口的 CSS 坐标
  (按主窗口的缩放)交出去。`publishWorker` 建第二块(`toastLayer`),视图收起时一起收;`showToasts` / `hideToasts`。
- IPC:`toasts:show`(`parseToastsShow`:html ≤ 256 KiB,矩形和根元素属性同悬停说明那一套校验)、`toasts:hide`、`toasts:pointer`、
  `mosael:command-palette`;preload 把后者转成 `mosael:open-cmdk`。
- `accountViews`:前台网页的 `before-input-event` 里认 ⌘K(`isCommandPaletteKey`),截下、`onCommandPalette` → 主窗口拿焦点、发事件。

**渲染层**
- `lib/nativeView.ts`:`useNativeViewInFront` / `nativeViewInFront` / `leaveNativeView`。
- `components/app/overNativeView.tsx`:`GLOBAL_OVERLAYS` 登记表、`<OverNativeView>`;App 里命令面板、远端引擎那一问,AppShell 里任务中心
  挂进去。任务中心的弹出层在范围里时挂 `CHROME_LAYER`、`<StepNativeViewAside />`;详情框、确认框照 `OverChromeModals` 自己抬、自己让。
- `components/app/toastMirror.ts`(`useToastMirror`)、`AppToaster` 外面包 `APP_CHROME`、`styles.css` 的 `[data-toasts-mirrored]`;浮层页
  `showToasts` + Sonner 导出的样式,窄视口样式照宽屏摆回来(这块视图只有提示条那么宽,主窗口最窄 980px)。
- `components/app/chromeStatusSlot.tsx`:`ChromeStatusSlot`(内嵌浏览器顶栏 xs、工作台顶栏 sm)、`useChromeStatusSlot`、`InChromeStatusSlot`
  (补上顶栏的说明范围,悬停说明照样画在网页上面);确认卡、免提浮标住进去。
- `nativeViewAside`:最后一处放开时,放回视图那一步等一个微任务 —— 同一次提交里另一处接着要它让开(任务中心里点一条任务,弹出层换成详情框)
  时视图不回来一下再挪走;`useNativeViewSteppedAside`。
- `embeddedFocus` 不吞 ⌘K;`lib/shortcuts` 的 `isCommandPaletteKey` 和主进程同一个判据;命令面板去别处的项、任务中心详情的「前往」、
  确认卡的「回到那里」、深链(`lib/deepLink`)、邀请链接(`lib/inviteLinks`,ADR 0054)先 `leaveNativeView`。

**真机走查**(隔离 Electron:独立 `--user-data-dir`、后端 8863、ComfyUI 克隆 18863):内嵌浏览器里拖到 Dock 的导入失败、更新提示画在网页
上面,悬停展开、点「查看」打开链接、移出收回;系统通知 → 任务中心在网页前面,Esc 收起视图回来;网页里按 ⌘K → 面板开、网页让开,选「设置」
→ 视图收起、落在设置页;免提图标、「1 个请求等你确认」在顶栏上,点开卡片在网页前面,拒绝之后视图回来;工作台里同样(提示条、任务中心、
免提图标);工作台开着时深链 → 收起、落在设置页,回到工作台没存的改动标记还在、没有另弹确认;新建项目的弹窗开着时点提示条的「查看」→
打开链接、弹窗还在。
