# 约定与结构性约束

这份文档记两件事:**写代码时照着做的约定**,和**仓库自己会检查的约束**。

区别很重要。约定靠人记,读到了就照做;约束不靠人记 —— 违反了测试会红。所以下面第二部分的
每一条都对应一个真实的测试文件,而不是一句期望。

---

## 前端约定

### 样式

- 交互控件一律用 JSX 上的 Tailwind 类加本地的 shadcn/ui 组件。不写全局类,也不搞共享的
  class 字符串文件 —— 那两样都会变成第二个样式系统。
- 字号走 `text-ui-*` token(有哪几档由 `design/tokens.css` 说了算),不写死像素。写死的 `text-[11px]` 不跟屏幕走,而且各写各的;
  这一条有棘轮守着(`design/typeScale.test.ts`),特例列在它的 `ALLOWED` 里。
- 圆角走 8px 刻度,分段控件是胶囊形,表单填充用 `--field`。不用投影。
- 按钮高度走 `Button` 的 `size` 档,不在 className 里改高宽。四档:`xs`/`icon-xs` 28px(工具栏)、
  `sm`/`icon-sm` 32px、`default`/`icon` 36px、`lg` 40px。缺一档就往 `buttonVariants` 里加一档 ——
  就地写 `h-7 w-7` 盖住 `size="icon"` 的代价是漏一处就露 8px,智能体输入框栽过这一下。
  棘轮:`components/ui/buttonScale.test.ts`,一次性尺寸列在它的 `GRANDFATHERED` 里。
- **按钮的分量跟着它的地位走。** 一页 / 一个弹窗只有一个实心的主动作(`default`);和它并排的次要动作用
  `outline` / `secondary`;工具栏、卡片角上不带边框的文字按钮用 `ghost`;只有图标的用 `IconButton`。
  **挨着一个值、一行说明的次要动作用 `variant="inline"`(行内动作)**:比正文小一档、次要色、悬停才显出底色、
  图标 14px、不撑高那一行,不写 `size`。挨着值的按钮用正文字号,就比值本身还醒目 —— 模型详情里「在 Civitai 上找」
  「标为 NSFW」就是这样喧宾夺主的。棘轮:`design/inlineActions.test.ts`(值那一格里的按钮、手搓的 `h-6` / `text-ui-xs`)。
- **动效只用一套刻度,只在它说明了一件事的时候动。** 时长四档(值在 `design/tokens.css` 的 `--motion-*`):
  快 `duration-100`(行上的悬停底色、小箭头转向、悬停才露出的小图标)、中 `duration-160`(控件换颜色、浮层 / 菜单 /
  说明 / 弹窗进出、折叠区块、东西挪到新位置;只写 `transition-colors` 不写时长就是这一档)、慢 `duration-240`
  (从窗口边滑进来的抽屉、大图放大)、余韵 `duration-600`(只给「刚做完」的高亮慢慢退掉)。缓动两种:出现用
  `ease-enter`,消失用 `ease-exit`(`data-[state=closed]:ease-exit`);样式表里写 `var(--motion-base)`、
  `var(--motion-ease-enter)`。**该动的**:东西出现 / 消失 / 换了位置(让眼睛跟得上去哪了)、状态变了(悬停、选中、
  刚做完);**不该动的**:进页面时整页飞入、数字滚动、为了「有活力」的装饰性循环。循环动画只给「还在做」(转圈、
  骨架屏、录音灯、语音浮标)。**减少动态**:`tokens.css` 那条全局规则把过渡和动画压成一瞬、循环的只走一遍(停在原样,
  不卡在半截);转圈例外 —— 放慢、不停,它是「还在做」的唯一信号。JS 驱动的动(画布视口飞过去)自己判:
  画布走 `canvasCameraDuration`,别处用 `matchMedia("(prefers-reduced-motion: reduce)")`。
  棘轮:`design/motion.test.ts`(刻度外的时长、一次性动画写死时长、减少动态那两条规则)。
- 设置页只保留页面主面板这一层容器。section 使用 `components/settings/settings-layout.tsx` 的平面
  `SettingsGroup`(设置、插件、定时任务、管理四页共用),相邻 section 之间那条线由
  `SettingsSectionStack` 用**相邻兄弟选择器**画在后一节身上 —— 不插独立元素:此前是「index > 0
  就插一条」,于是一个只走 portal 的孩子(AlertDialog)就能让页面末尾多出一条底下什么都没有的线。
  同类数据行使用 `SettingsList` 的分割线,不要给每个 section、每一行再套圆角边框和背景。输入控件、可选择卡片、
  独立状态面板等确实需要交互或语义边界的元素可以保留边框。
- **停靠的栏之间只有一条 1px 分割线,没有缝。** 可拖宽的栏用 `lib/useResizableSidebar`
  (`useResizableSidebar` / `useSidePanels` / `HANDLE_COLUMN` + `handleOffset`),拖柄压在那条线的
  正中;grid 上不要再加 `gap-*`,否则拖柄会悬在离线几像素的空白里、和别的页一处有缝一处没缝。
  只有画布上的浮动卡片(`RightDockResizeHandle`、工作流右侧上下两块)之间真有缝,那里显式传
  `handleOffset(size, { gap: 8 })`。棘轮:`lib/dragHandle.test.ts`。
- **新页面挂进 `app/pages.tsx` 时用 `React.lazy`。** 静态 import 会把那一页连同它的依赖
  (图编辑器、富文本内核、图表、three.js)拖回主包,而打包照样成功、测试照样全绿 —— 十四个页面
  这么攒出过一个 4.20 MB 的主包(现在 0.28 MB)。兜底的 Suspense 在 App 的渲染出口上,页面不必
  各写一次。首屏那一页(home)例外。棘轮:`app/pageChunks.test.ts`。
- 每个新界面都要同时管好浅色和深色。
- **功能模块之间不得互相依赖。** 一处功能引用另一处没问题(画板放一张 3D 场景卡),两边互相
  引用永远说明有个东西站错了地方:通用工具放 `lib/` 或 `components/`,属于某个领域的东西放回
  它的领域(评论归协作、录制归素材)。棘轮:`features/featureBoundaries.test.ts`。
- **控件的字号字重直接写在控件上就行。** `design/tokens.css` 里那条
  `button, input, select, textarea { font: inherit }` 曾经是无层级的,压过 `@layer utilities`,
  于是写在按钮上的 `text-ui-xs` 会静默失效(class 还在,尺寸回落到继承值);2026-08 那一轮
  把它挪进了 `@layer base`,并把 `ui/` 下的组件按本项目的 ui-* 刻度重定了一遍。
  没写字体类的控件仍然继承。棘轮:`design/unlayeredGlobals.test.ts`。
- **第三方组件的样式表在 `design/tokens.css` 里以 `@import … layer(vendor)` 引入,不在 JS 里
  import。** JS 里 import 的 CSS 不分层,压过所有工具类:工作流里真/假分支的红绿、数据线的
  主色和线宽写了几个月,一条都没生效。层序 `theme, base, vendor, components, utilities` 在
  tokens.css 第一句说定。给它们上色先找组件公开的 CSS 变量(React Flow 的 `--xy-*`),
  变量够不着的才用 `[&_.x]:` 任意选择器 —— 而选择器里的 `__` 必须写成 `\_\_`(整串 String.raw),
  否则 Tailwind 把 `_` 换成空格、规则选不中任何东西。
  棘轮:`design/vendorStyles.test.ts`、`design/arbitrarySelectors.test.ts`。
- **画布连线只有一套外观,在 `components/app/canvasEdges.ts`。** 工作流(含循环体/子图那一层)和
  创意画板共用:容器挂 `CANVAS_EDGE_CLASS`,每条边带 `CANVAS_EDGE_OPTIONS`(箭头、命中宽度),
  有语义的边挂 `canvasEdgeClass(tone, { flow })` 给的类。别处不写线色、线宽、箭头、虚线、
  `connectionLineStyle`。意思不同才长得不同:

  | 变体 | 意思 | 样子 |
  |---|---|---|
  | 引用 / 控制流(默认) | 画板的上游 → 下游;工作流的执行顺序 | `--canvas-edge` 实线 2px + 闭合箭头 |
  | `true` / `false` | 条件节点的真 / 假两路 | `--success` / `--destructive` 实线 + 箭头 + 标签 |
  | `data` + flow | 端口之间传值 | `--primary` 流动虚线,无箭头 |
  | `mismatch` + flow | 数据线两端类型不兼容(软提示) | `--warning` 流动虚线,无箭头 |
  | `taken`(数据线再带 flow) | 上一次运行走过 | `--canvas-edge-run`(紫,不和「真」那一路的绿撞),选中那一档线宽 |
  | `pending` / 拖线途中 | 松手在空白处待选 / 正在拉 | `--primary` 静止虚线 + 箭头 |
  | 悬停 / 选中 | —— | 本色往前景色走一截、2.5px / `--primary`、2.75px |

  箭头颜色是 `context-stroke`(跟着线本身的颜色走),尺寸按画布坐标定(不随线宽胀缩)。
  画板上连线的层次夹在分组框和项之间(`LAYERS.edge`)。点阵和线色两个令牌
  (`--canvas-dot`、`--canvas-edge`)一起调,对比度有测试盯着。
  棘轮:`components/app/canvasEdges.test.ts`。

### 布局

- 纵向堆叠用 grid/flex 加 `gap`,不用 `space-y`。Tailwind v4 把它实现成前一个子元素的
  `margin-bottom`,对 label 这类行内子元素是空操作。`components/ui/` 里几个 vendored 的
  shadcn 组件还留着 `space-y`,那是上游原样,它们的子元素都是块级,不受这条影响。
- 用内联 style 定位的元素,不要同时挂 Tailwind 的 translate/inset 类 —— v4 的独立
  `translate` 属性会和内联 `transform` 叠加。
- 单列 grid 想让内容可收缩,轨道要写成 `grid-cols-[minmax(0,1fr)]`。默认的隐式列是
  `auto` 也就是 max-content,长内容会把宽度顶开,而给子元素加 `min-w-0` **约束不到轨道**。
- 负外边距(`-mx-N`)抵消外壳内边距时,两者是一对。改外壳内边距而不动它,页面就会横向溢出。
- 业务弹窗统一用 `components/app/modals.tsx` 的 `ModalShell`:外壳 `overflow-hidden`,标题与动作区
  分别 sticky 在顶/底,只有中间 body 纵向滚动。头尾使用与中段同源的半透明 `popover` 表面加
  backdrop blur,不能另铺一块完全不透明的异色底。body 必须保留上下内边距,不能让第一个/最后一个
  控件贴住 overflow 裁剪线 —— `focus-visible` 的 ring 画在控件边框外,贴边时会被切掉。命令面板与
  纯媒体预览有自己的交互模型,可直接使用底层 `DialogContent`,但表面仍须采用 `popover/90` +
  backdrop blur,不能退回完全不透明的遮挡块；普通表单不能绕过公共壳。

### 数据与交互

- 服务端实体留在 React Query 里;Zustand 只放草稿和瞬时 UI 状态。
- **缓存键的失效用最短前缀。** React Query 按前缀匹配,所以同一份数据用几种形状的键并存时,
  刷不刷得到全看谁比谁长:剪辑页按 `["assets", 工作区, 项目]` 失效,首页按 `["assets", 工作区]`
  取数 —— 三段匹配不到两段,导入的素材在首页不出现。素材、工作区列表、音色库这几族已收进
  `api/queryKeys.ts`(`list()` 取数、`all()` 失效;只有一种形状的族只有 `all()`),棘轮
  `api/queryKeys.test.ts` 不许再内联手写它们。别的键族还是内联字面量,新写的尽量跟着这个形状走。
- 不用 `alert` / `confirm` / `prompt` 这些原生弹窗。
- 所有用户可见文案走 i18n(`src/app/messages.ts`),中英两份都要有。
- 时间线的几何计算住在 `domain/timeline/geometry.ts`,是有测试的纯函数;组件里不内联几何。
- 动态长列表的下拉用共享的可搜索 Combobox;拖拽交互用 dnd-kit。
- **⌘S / Ctrl+S 全应用一个行为:能存就马上存,不能存也拦下**(不让网页版弹浏览器的「存储网页」),焦点在输入框、编辑器里一样。
  全局监听在 `main.tsx` 装一次(`lib/saveShortcut`),页面用 `useSaveShortcut(fn)` 登记「此刻存什么」(自动保存的页面就是把
  欠着的那份马上存掉),不各自另听这个键。ComfyUI 工作台在它自己那一栏里先接(存那张工作流)。
- **多选的修饰键只有两条规则。** 摆在空间里的东西(画板、工作流画布、时间线片段、3D 关键帧):⌘ / Ctrl / Shift + 点击都是
  「加入 / 移出选择」,Shift + 拖空白是框选(两块画布共用 `components/app/canvasInputMode` 的 `CANVAS_POINTER_PROPS`)。
  有先后顺序的列表(素材、笔记、场景列表、设置里的表,`lib/useMultiSelect`):⌘ / Ctrl + 点击加入 / 移出,Shift + 点击从上一次点的
  那项连选到这项。
- **从素材库挑媒体(图片、视频、音频、文档素材)的弹窗只有一种:`components/app/AssetGridPicker`** —— 缩略图网格,格子下面写名字、
  种类和尺寸、来源和多久以前;键盘、看大图、加载 / 空态都在里面。点了即挑中的直接用,多选或先选再确认的给 `selection` 和 `footer`,
  头里的筛选和动作给 `toolbar`。按名字挑的清单(笔记、3D 场景、资产)用 `components/app/PickListDialog`;表单里就地挑一份的用 Combobox。
- **悬停说明只有三种写法,不用原生 `title`。** 原生 `title` 停一秒多才出、样式是系统的、深色下不跟主题,
  还不管字放不放得下都出。只有图标的按钮用 `IconButton`(名字只写一次:既是 `aria-label` 也是说明的第一行;
  快捷键给 `shortcut`,点不了给 `disabledReason` —— 禁用的按钮自己收不到悬停,它会在外面套一层壳);文字按钮、
  标签、徽标上的补充说明和禁用原因用 `Hint`;会被截断的名字、文件名、网址用 `Truncate`(真被截断了才出,
  说明里是全文)。文字已经写清楚的按钮不再套说明。`<iframe title>` 是给辅助技术的名字,留着。
  棘轮:`design/nativeTitles.test.ts`、`design/iconButtons.test.ts`、`design/truncatedText.test.ts`。
- **菜单和选值下拉的宽度只在 `components/ui/floating.ts` 定,调用方不写。** 点按钮弹出的动作菜单用
  `MenuContent`、右键菜单用 `ContextMenuContent`,都是 `MENU_WIDTH`(随内容,12–20rem,不超出窗口);Select
  是 `SELECT_CONTENT_WIDTH`,带搜索的下拉和 Combobox 是 `SEARCHABLE_CONTENT_WIDTH`。菜单行用 `MenuItem` /
  `MenuItemBody`:静态文案放不下就折行,括号里的补充挪成名字下面一行淡色的 `description`;动态的长值
  (文件名、网址、工作流名、模型名、用户输入)传 `truncate`,单行截断、悬停看全文。手写 `SelectItem` 放动态值时
  同样传 `truncate`。棘轮:`design/menuWidths.test.ts`。
- 会发请求的按钮必须显示 `loading`,而不只是 `disabled`(棘轮:`app/buttonPending.test.ts`)。反过来也一样:
  `disabled` 里等着一件在跑的事(`isPending`、`busy`、`saving`……)的按钮要转圈 —— `Button` / `IconButton`
  给 `loading`(`unstyled` 的也认,图标换成同样大小的转圈),原生 `<button>` 把图标换成转圈、挂 `aria-busy`。
  后台任务的按钮转到任务做完,不是发起任务的那个请求回来就停。好几颗共用一个请求的,转圈的是点的那一颗,
  别的只是点不了;菜单里的条目点了就关,进度在发起它的地方或任务中心。「别的事在跑所以这颗点不了」
  (取消键、只是打开确认框的按钮)不转圈,写进例外并说清楚在跑的是谁(棘轮:`design/pendingButtons.test.ts`)。
- 参考音频录制统一使用 `features/voice/useReferenceAudioRecorder.ts`，设置页与剪辑页的音色创建统一
  使用 `features/voice/VoiceCreationDialogs.tsx`。不要在页面组件里另写 `getUserMedia` / `MediaRecorder`；
  弹窗取消、切换入口和卸载都必须停止轨道，权限拒绝、录音器故障和空录音必须是不同错误。
- 领域资源跟随能力显示：工作区音色库只属于本地克隆引擎；远程 TTS 选择后只显示该供应商的音色目录，
  不保留本地音色卡片、空状态或创建入口。
- 供应商表单按真实归属命名：连接字段使用供应商/协议级 Endpoint 名称；`default_model` 兼容存储只在
  新建时显示为“初始模型”，编辑时一律去模型列表，不得重新称作供应商默认模型。

## 后端约定

### 多语言

- **领域里存 key,出口才翻。** 数据目录(发布平台、TTS 引擎、工作流节点)里写的是消息键,
  句子在接口那一层按语言组装 —— 语言从 `Accept-Language` 来,不从某个全局配置来:这是个
  多租户、可远程部署的后端,没有「服务端语言」这回事。表按领域分片在 `app/core/messages/`(新 key 进它所属的那一片),
  出口用 `t()` / `translate_fields()`。
- 两条棘轮跟着每一份目录:「目录里不许出现文案」和「写的 key 必须翻得出来」。
- **选项的值不是文案。** 下拉选项的 value 会原样存进数据、也会原样显示,没有出口能翻它 ——
  所以一律写中性标识符(`true` / `GET` / `image`),要显示什么由出口那一层决定。
- **插件清单是唯一的例外**:它是第三方写的,没法往我们的表里加词条。那里的约定是
  「一段文字既可以是字符串,也可以是 `{"zh": …, "en": …}`」,见
  [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md#多语言)。

---

### 一次用例一个事务,授权在领域里

同一个领域操作有四个入口:HTTP、智能体工具、工作流节点、飞书。所以:

- **领域函数不提交**。只改对象;要拿 id 就 `db.flush()`。提交之后才能做的事(起线程读刚写的行、推送通知)
  用 `core/unit_of_work.after_commit(db, fn)` 登记,回滚了就不执行。
- **入口层包住一次用例**。写操作的路由用 `Tx`(`api/deps`)代替 `DbSession`,路由里也不写 `db.commit()`;
  后台线程、工具、节点用 `with unit_of_work() as db:`。`Tx` 在响应发出之前提交,提交失败就是这次请求的 500。
- **授权在领域函数里**。领域函数收行动人(`domain/authority.Actor`)、自己把关,入口层不再各写一份。

存量按领域逐个迁移,`tests/test_use_case_boundaries_ratchet.py` 让两类旧写法只减不增。

### 任务的状态只经总线写,取消要真的停下

- **起步用 `jobs.start_job`,收尾用 `jobs.finish_job`**,返回 False 就停手 —— 不直接 `job.status = …`。排队时被取消的
  任务轮到它时不许被写回「在跑」;ORM 上守着「终态不回头」(`jobs._terminal_is_terminal`,写回去当场抛 `JobStateError`)。
- **登记产出、改时间线、写逐字稿之前问一句**:`jobs.ensure_wanted()`(认的是上下文里正在跑的那个任务,工作流节点认的是
  工作流);只改库的那一步可以先 `lock_active_job` 拿住任务、在同一个事务里写、再 `finish_job`。
- 外部命令照旧只从 `core/child_process.run_logged` 出去:在任务里跑时它自己登记在任务的取消开关上,取消停下整棵进程树;
  常驻的识别 / 合成进程同样(`ai/runtime/worker_pool`)。
- **失败兜底由派发处套**:`dispatch_job` 替每个执行体套 `run_job_guarded`,执行体不用、也不该再自己套一层。

### 要碰库的路由写成 `def`,要发很久的响应先还会话

- `async def` 的端点体跑在事件循环上,在那里查库 / 写库,整个后端的请求都排在它后面。要碰库的端点写成普通 `def`
  (上传用 `upload.file.read()` 同步读);非 async 不可的(要 `await request.form()`)把库的那一段交给线程池、会话在那边开。
  棘轮:`tests/test_async_routes_do_not_touch_the_database.py`。
- 文件、事件流这类要发很久的响应只从 `api/responses.py` 出(`file_response(db, …)` / `event_stream(db, …)`):鉴权查完就关会话,
  不让它攥着连接池里的一条连接直到发完。棘轮:`tests/test_long_responses_release_the_session.py`。

### 加了一次性迁移,数据库版本号就加一

`app/db/safety.DATABASE_SCHEMA_VERSION` 是老版本手里**唯一**的降级判据:库的 `user_version` 比它认得的大就拒绝启动。新加一步一次性迁移,
先把这个数加一,再跑 `python -m tests.freeze_migration_bodies`(它同时更新迁移指纹和 `tests/schema_version.json`)。忘了加,
`tests/test_schema_version_follows_the_migrations.py` 会红 —— 此前这个数停在 4 而其间加了几十步,v1.9.3 照常打开 main 迁过的库,
智能体页随即 `no such column`。

### 写锁:攥着它的时候不做长活

SQLite 同一时刻只有一个写事务。从第一句写到提交,别的写入(别的节点、请求、任务进度)都在排队,最多等 `core/db.LOCK_WAIT_SECONDS`。
所以写过之后不做长活(调供应商、等子任务、跑插件进程):先提交再等,见 `executors.common.connection_handed_back`、
`plugins.tools._plugin_slot`。攥写锁超过 `LONG_WRITE_SECONDS` 的事务、等不到锁的那一句,`core/db` 都记一条警告,点名攥锁的线程
和它从哪一行开始写 —— 查「database is locked」先看这两条。

- 先读后写不用特意开 `BEGIN IMMEDIATE`:pysqlite 只在第一句写之前才 BEGIN,之前的读各自自动提交,第一句写排队等锁。
  要「判和写之间不许别人插进来」才用 `immediate_unit_of_work`(浏览器会话的租约)。
- 保存点(`begin_nested`)可以放心用:事务里还没写过时开保存点,`core/db` 先 `BEGIN IMMEDIATE`,保存点从来不是最外层
  (否则 SQLite 把它当成延迟事务的开头:里面先读后写当场报 database is locked,RELEASE 还会当场提交)。
  棘轮:`tests/test_writes_wait_for_the_write_lock.py`、`tests/test_unit_of_work.py`。

### 批量维护不把行读成 ORM 对象

清理、批量删这类「一次动成千上万行」的活:先用集合式查询挑出 id(读,不占写锁),再按批删、一批一个事务,删用
`execution_options(synchronize_session=False)`(或 Core 的表达式)。ORM 的 DELETE 默认把身份映射里的全部对象过一遍,
读进来的行越多越是平方级,而整段攥着写锁,别的写入等满上限就失败(见 jobs.prunable_task_events / finished_job_trees)。
一次放下很多段片段同理:`coverage.TrackCover` 只查一次轨,二分找落点,不逐段 `clear_range`。

### JSON 里点名的别的记录,反查走引用表

画布、工作流图、生成请求、3D 场景、定时任务的 JSON 里点名的素材 / 资产 / 场景 / 时间线……由 `db/references`
按一份抽取规则派生进 `record_references`:flush 时跟着写,启动时按规则版本号对账重建。「谁还指着它」用
`domain/references.referrers` 查,**不要**再把整列 JSON 转字符串去 `LIKE`,也不要逐行遍历。

- 新增一种来源或一个点名字段:改 `db/references` 的抽取规则,并把 `EXTRACTOR_VERSION` 加一。
- 绕过 flush 的写(比较并交换的 `update(Board)…values(canvas=…)`)要就地 `references.resync`
  (棘轮:`tests/test_record_references.py`)。

## 测试约定

### 测试里怎么等

后端测试默认并行(pytest-xdist),CI 是 4 核满载。「睡一下,它应该已经……了」在本机永远绿,在机器忙的时候随机红 ——
而红的经常是无辜的那条。规矩:**等事件、等条件,不等时间。**

- **替身阻塞在事件上,由测试放行**:要「这一轮还在跑」,替身就 `release.wait(30)`,断言完再 `release.set()`;
  不要「替身睡 0.2 秒,测试赶在 0.2 秒内做完」。要「几项同时在跑」,让它们在 `threading.Barrier(n, timeout=10)` 上会齐。
- **要「它已经进去了」,就让它进门时 `entered.set()`**,测试 `assert entered.wait(30)`;不要 `time.sleep(0.3)  # 让它进去`。
- **轮询等那个事实**(`assert until(predicate), "等的是什么"`,`tests/util.until`,默认上限 30 秒):上限给足,条件一成立就返回,
  给多大都不花钱。只领一次、只看一眼的写法(`sleep(0.5)` 然后单发一次 `claim`)不行。
- **不写「耗时 < N 秒」**。要证明「没等那件慢事」,就让那件事一直卡着(替身卡在事件上),断言**返回的时候它还卡着**;
  要证明「是并发的」,用会齐。实在要比时间,线画在对照值(不修的话要等多久)的一半。
- **不写「睡一下,确认没发生」**:机器越忙越来不及发生,修复撤掉照样绿。等到一个确定的终点(线程结束、状态落定)再数;
  或者在「决定」发生的那一处当场看(放没放行是 submit 里锁内定的、收不收回执是 ack() 当场定的),或者让那件事一直卡着,
  断言「返回的时候它还卡着」。
- **只换一个模块的钟**:`monkeypatch.setattr(http_retry, "time", module_time(sleep=lambda *_: None))`(`tests/util.module_time`)。
  `monkeypatch.setattr(http_retry.time, "sleep", ...)` 换的是整个进程的 `time.sleep`,同一进程里别的线程也跟着不睡、拿到假钟。
- **落终态之后的收拾**(失败原因抄到生成记录上、关掉这次运行开的浏览器会话)在任务提交之后的 after_commit 里做:
  断言它们用 `tests/util.wait_settled`,不用 `wait_status`。
- **谁起的线程谁收**:测试函数体里起的线程,测完还活着,这条测试会在 teardown 红(`tests/conftest.py`)。
- **读库的测试先 `fresh_client()`**:进程起来时表已经建好(conftest),但里面是前面测试留下的什么,看排在谁后面。
- 前端同理:用 `waitFor` 等条件,`vi.useFakeTimers` 推进计时器;不要 `await new Promise((r) => setTimeout(r, 800))`
  然后断言;模块级的可变状态(测试文件里的 `const config = {...}`、被测模块里的缓存)在 `beforeEach` 里还原 ——
  `vitest --sequence.shuffle` 打乱顺序跑,依赖先后的用例当场就红。

验收这类修法:后端开 `MOSAEL_TEST_THREAD_JITTER=0.3`(每条新线程起步前随机等 0–0.3 秒,见 `backend/tests/thread_jitter.py`),
换几个 `MOSAEL_TEST_THREAD_JITTER_SEED` 各跑几遍;前端 `pnpm vitest run --sequence.shuffle --sequence.seed=<n>` 换几个种子。
CI 每天也这么跑一遍整道门禁(`.github/workflows/chaos.yml`)。

**两道棘轮守着「等时间」的写法,只挡新增**(存量按文件冻在表里,改好一处就把表里的数字改小):

- 后端 `backend/tests/test_tests_wait_for_events_not_time.py`:不在循环里的 `time.sleep` / `asyncio.sleep`(循环里的是轮询间隔,
  不算;替身里「睡一会儿假装在干活」算),和拿一段耗时跟常数比的断言(`assert time.monotonic() - started < N`、`assert elapsed < N`)。
- 前端 `frontend/src/design/testsWaitForConditions.test.ts`(连同 `electron/` 下的测试):一个由 `setTimeout` 去 resolve 的 Promise。

新写的测试碰上它们,先按上面几条改写;真有非这么写不可的(本身就在测超时、测「多快」),把那个文件加进表里,并在那一行写清为什么。

## 结构性约束(棘轮)

**棘轮**指的是只能往一个方向走的检查:存量问题冻结在一份允许清单里,新增会红,修好一处就得
把清单一起改小。它们的共同点是 —— 每一条防的漂移,都**已经真实发生过一次,而且是静默的**。

新增一条:给测试模块加上 `RATCHET = True`(Python)或 `export const RATCHET = true;`
(TypeScript),再跑一次生成脚本,它就会出现在下面。

```bash
python3 scripts/sync-ratchet-docs.py
```

<!-- BEGIN RATCHETS (generated by scripts/sync-ratchet-docs.py — do not edit by hand) -->

共 187 道。清单由脚本生成 —— 给测试加上 `RATCHET` 标记它就会出现在这里。

| 守住什么 | 测试 |
| --- | --- |
| 结构性约束:**适配器读的每个参数键,描述符都得声明。** | `backend/tests/test_adapters_read_only_declared_parameters.py` |
| 结构性约束:**「普通 / 高级」这条分界怎么划都行,但有几种划法一定是错的。** | `backend/tests/test_advanced_split_is_sane.py` |
| 智能体要能做**这个应用能做的事** —— 插件、工作流、剪辑,一样都不少。 | `backend/tests/test_agent_covers_everything.py` |
| 智能体的权限恒等式(ADR 0008 D6) | `backend/tests/test_agent_identity_ratchet.py` |
| 结构性约束:**工具集清单里报出去的每条路径,都得真的存在。** | `backend/tests/test_agent_manifest_paths_exist.py` |
| 工作流有的能力,智能体也要有。 | `backend/tests/test_agent_workflow_parity.py` |
| 结构性约束:**`ai/` 是基础设施,不许认识业务**。 | `backend/tests/test_ai_is_infrastructure.py` |
| 棘轮:**接口 out schema 里的每个字段,都要有人读。** | `backend/tests/test_api_fields_reach_the_screen.py` |
| 棘轮:**请求体里的数必须是有限的**,而这条要在进门那一层挡。 | `backend/tests/test_api_refuses_non_finite_numbers.py` |
| 棘轮:**`async def` 的路由不拿数据库会话。** | `backend/tests/test_async_routes_do_not_touch_the_database.py` |
| 异步任务的轮询:六家共用的那一段。 | `backend/tests/test_async_task_polling.py` |
| 三类撤不回来的操作,同一种判据:默认问你,想让判断者接管就显式打开。 | `backend/tests/test_autopilot_has_no_allowlists.py` |
| 后端自己的多语言。 | `backend/tests/test_backend_i18n.py` |
| 空密钥不发 `Authorization` —— 而且这条规矩**只有一处实现**。 | `backend/tests/test_bearer_header_is_built_in_one_place.py` |
| 每一处 `billable(...)` 都要**说出**自己的幂等键,没有隐式兜底。 | `backend/tests/test_billing_keys_are_deliberate.py` |
| 画板上每一个内容变换都住在内容格上:能力挂在它吃的那几种格子上,生成器挂在它产出的那种空格子上。 | `backend/tests/test_board_abilities.py` |
| 智能体改画板走的是**细粒度算子**,不是重写整份画布。 | `backend/tests/test_board_ops.py` |
| 描述符要和供应商的真实接口对得上。 | `backend/tests/test_capabilities_match_reality.py` |
| 每个批准入口批下的卡都真的落库:智能体删素材之后,**另开一个会话**查,素材确实没了。 | `backend/tests/test_card_approval_lands.py` |
| 选择卡**只在它自己那次对话里出现**。 | `backend/tests/test_card_session_isolation.py` |
| 读目录里那几格文案的地方,**要么翻,要么明说自己在传 key**。 | `backend/tests/test_catalog_labels_are_translated_where_read.py` |
| 结构性约束:**对话补全只有一个实现**。 | `backend/tests/test_chat_single_implementation.py` |
| Clip 的每个可写列,切分 / 剪段 / 撤销重建 / 复制序列时都跟着走。 | `backend/tests/test_clip_fields_are_carried.py` |
| 棘轮:一个会改东西的工具,只在一处声明。 | `backend/tests/test_confirmable_tools_are_declared_once.py` |
| 确认卡上那句话按**读的人**的语言翻,和任务消息同一条规矩。 | `backend/tests/test_confirmation_cards_speak_the_readers_language.py` |
| 一句「另一侧还有一份,必须跟我一致」,必须**点名它归哪个契约**。 | `backend/tests/test_cross_runtime_claims_name_a_contract.py` |
| 数据归属棘轮:表的行创建只能发生在拥有它的领域模块里(ownership.py)。 | `backend/tests/test_data_ownership_ratchet.py` |
| 结构性约束:**供应商声明的每一样能力,都得真有东西去执行它。** | `backend/tests/test_declared_capabilities_have_an_implementation.py` |
| 删工作区、删账号之后,它们的文件不留在盘上;已经留下的孤儿只列出来,管理员确认后才删(SEC-7)。 | `backend/tests/test_deleted_workspaces_leave_no_files.py` |
| 结构性约束:**子字段的值不能比它依赖的父字段活得久。** | `backend/tests/test_dependent_fields_are_declared.py` |
| 棘轮:**桌面端运行时要加载的东西,开发态必须先构建好、并且跟着改动重建。** | `backend/tests/test_dev_mode_builds_what_the_app_loads.py` |
| 棘轮:**文档里指到的代码路径必须真的存在**。 | `backend/tests/test_docs_do_not_point_at_ghosts.py` |
| 切片是实现细节,装配入口是公共 Interface。 | `backend/tests/test_domain_assembly_entries.py` |
| 结构性约束:**领域层不认识 HTTP。** | `backend/tests/test_domain_does_not_raise_http.py` |
| 棘轮:**指向某样东西的节点字段给选择器,不给文本框。** | `backend/tests/test_entity_fields_have_a_picker.py` |
| 每一处 `chat()` 调用都要记账 —— **不能靠调用方记得传 `call=`**。 | `backend/tests/test_every_chat_call_is_billed.py` |
| 棘轮:**每一张会落「进行中」的表,都要说得出重启之后谁来收尾。** | `backend/tests/test_every_in_flight_row_has_someone_to_settle_it.py` |
| 棘轮:**每个节点类型在画布上都有自己的图标**。 | `backend/tests/test_every_node_type_has_an_icon.py` |
| 执行器**真正返回**的键,必须在节点注册表里声明过。 | `backend/tests/test_executor_outputs_are_declared.py` |
| 节点执行器只从运行作用域里读 workspace_id / id / name 三样。 | `backend/tests/test_executors_only_read_run_scope.py` |
| 起 ffmpeg / ffprobe 一律用 `settings.ffmpeg` / `settings.ffprobe`,不写死程序名。 | `backend/tests/test_ffmpeg_comes_from_settings.py` |
| 字段用哪种专用控件,由**字段声明**点名(`editor`),不由界面按「节点类型 + 字段名」认。 | `backend/tests/test_field_editors_are_declared.py` |
| 结构性约束:**字段说明不能只是把标签再说一遍。** | `backend/tests/test_field_help_says_something_new.py` |
| 口癖词表的后端一侧:跑 contracts/filler-word-cases.json。 | `backend/tests/test_filler_word_parity.py` |
| 结构性约束:**自由文本字段必须声明成 `template`。** | `backend/tests/test_free_text_fields_are_templates.py` |
| 打包版的后端**不是一个 Python 解释器**,也**没有 .py 源文件在盘上**。 | `backend/tests/test_frozen_build_is_not_a_python_interpreter.py` |
| 棘轮:**多能力供应商下,认不出、也没标过能力的模型不出现在任何生成入口里。** | `backend/tests/test_generation_capabilities_need_evidence.py` |
| 时间线上有 GIF 时,取当前帧和导出都要跑得通。 | `backend/tests/test_gif_on_timeline_renders.py` |
| 这台电脑上的文件是**部署主人的** —— 读一个用户给出的本机路径,只在一处判,每个入口都算数。 | `backend/tests/test_host_files_belong_to_the_deployment_owner.py` |
| 棘轮:**执行体写任务状态走 finish_job,不直接 `job.status = …`**。 | `backend/tests/test_job_status_goes_through_finish_job.py` |
| 建了 job 就得让总线派发它,不许自己起线程。 | `backend/tests/test_jobs_are_dispatched_by_the_bus.py` |
| 要发很久的响应(文件、事件流)**不攥着数据库连接**。 | `backend/tests/test_long_responses_release_the_session.py` |
| 挪一个标记不是一次「执行版本」。 | `backend/tests/test_markers_do_not_make_revisions.py` |
| 每个只读的列表 / 详情工具,都在**有数据**的工作区上真跑一遍。 | `backend/tests/test_mcp_read_tools_with_data.py` |
| 冒烟测试:**每个工具发出去的载荷,后端接得住。** | `backend/tests/test_mcp_tool_payloads.py` |
| 棘轮:**跑过一次的迁移,身体不能再改。** | `backend/tests/test_migration_bodies_are_frozen.py` |
| 内置的模型上限表:形状、优先级、以及「宁可报小」那条。 | `backend/tests/test_model_limits.py` |
| 内嵌子图(循环体 / subgraph)**体内看得见什么**,由节点自己声明一次(`body_scope`)。 | `backend/tests/test_nested_body_scope_is_declared_once.py` |
| 工作流引擎同时占的连接数,必须由**池子的容量**决定,而不是三个相乘的常数。 | `backend/tests/test_nested_graphs_stay_inside_the_pool.py` |
| 棘轮:**新加的迁移,必须带一条喂它旧形状数据的测试。** | `backend/tests/test_new_migrations_come_with_a_test.py` |
| 吞掉异常不许再变多。 | `backend/tests/test_no_new_silent_swallows_on_the_clone_path.py` |
| 报错不许再按位置裁子进程的输出。 | `backend/tests/test_no_new_tail_cutting_error_messages.py` |
| 棘轮:节点**声明的输出**和执行体**真正返回的键**是同一批。 | `backend/tests/test_node_outputs_match_the_executor.py` |
| 对象存储是**一个插件、五个服务商选项**,各家的差异只住在 providers.py 那一张表里。 | `backend/tests/test_object_storage_plugin.py` |
| 官方模板建出来的图:画布上看到的连线,就是引擎真正等的先后和真正会跑的节点。 | `backend/tests/test_official_templates_hold_together.py` |
| 棘轮:插件字段的说明里写着「可以不填」,清单里就得声明 `required: false`。 | `backend/tests/test_optional_plugin_fields_are_not_required.py` |
| 付过钱的远端生成,只有两种结束方式:远端给出终态,或者用户取消。 | `backend/tests/test_paid_generations_are_never_abandoned.py` |
| 宿主把一份**文件**交给插件。 | `backend/tests/test_plugin_inputs.py` |
| 插件清单里给人看的文字必须能跟着界面语言走。 | `backend/tests/test_plugin_manifest_i18n.py` |
| 插件节点在**每一条**校验路径上都认得出来,而不只是保存和运行那两条。 | `backend/tests/test_plugin_nodes_are_known_everywhere.py` |
| 插件节点的表单也要能分「普通 / 高级」。 | `backend/tests/test_plugin_nodes_support_advanced.py` |
| 插件的 README 要能在官网上渲染出来。 | `backend/tests/test_plugin_readme_renders.py` |
| 插件市场索引必须和插件清单对得上。 | `backend/tests/test_plugin_registry_in_sync.py` |
| 棘轮:我们自己发的插件,清单里的每个工具都写了名字(`label`,中英各一份)。 | `backend/tests/test_plugin_tool_labels.py` |
| 内置的官方价目表:形状、查表规则、中转的借价规则。 | `backend/tests/test_price_reference.py` |
| 私有的发布账号与浏览器池档案,**管**只认主人 —— 共享出去是借给人用,不是交给人管。 | `backend/tests/test_private_identities_are_managed_by_their_owner.py` |
| 私有的发布账号与浏览器池档案,只有主人和被共享到的人能**用** —— 在用的那一刻查,每个入口都算数。 | `backend/tests/test_private_identities_need_their_owner.py` |
| 棘轮:下划线开头的名字不跨包引用。 | `backend/tests/test_private_names_stay_in_their_package.py` |
| 结构性约束:**清过缓存之后,在飞的那次探测不算数。** | `backend/tests/test_probe_generations.py` |
| 结构性约束:**每一处模块级可变状态都在 docs/PROCESS_STATE.md 里有交代**。 | `backend/tests/test_process_state_inventory.py` |
| Provider 的能力 Interface、供应商 Adapter 和 Registry 不能重新混成一层。 | `backend/tests/test_provider_architecture.py` |
| 棘轮:**每个发布状态都要被归到首页那三档里的一档**,不多不少。 | `backend/tests/test_publish_statuses_are_all_classified.py` |
| 结构性约束:**docs/CONVENTIONS.md 的棘轮清单与代码一致**。 | `backend/tests/test_ratchet_docs_in_sync.py` |
| 引用表(record_references):JSON 里点名的别的记录,派生成一张有索引的表(见 db/references)。 | `backend/tests/test_record_references.py` |
| 撤掉的模型不留残影:代码里不再有它们的 id、档案名和 Adapter。 | `backend/tests/test_removed_models_leave_no_trace.py` |
| 棘轮:**路由里写死的报错原文(`HTTPException(detail="…")`)只减不增。** | `backend/tests/test_route_details_are_not_hardcoded.py` |
| 一次运行用私有的东西,要**点运行的人**和**被执行那一版图的担保人**都过得了闸。 | `backend/tests/test_runs_act_with_the_revision_authors_authority.py` |
| 用户在「模型设置」里填的每一格,**两条执行通道上都要有人读它**。 | `backend/tests/test_runtime_fields_reach_both_channels.py` |
| 「这个本机引擎跑不跑得起来」只有一种回答方式:**起子进程 import 一次**。 | `backend/tests/test_runtime_readiness_is_an_import_probe.py` |
| 模型上加了列,就得有迁移把它加到**已存在的库**上。 | `backend/tests/test_schema_migrations_cover_the_models.py` |
| 棘轮:**加了一次性迁移,`DATABASE_SCHEMA_VERSION` 就要加一** —— 老版本靠它拒绝打开新版本迁过的库。 | `backend/tests/test_schema_version_follows_the_migrations.py` |
| 密钥不该明文落盘。 | `backend/tests/test_secrets_at_rest.py` |
| 设置 API 只是统一 URL 前缀，不是一个能吞下所有设置领域的模块。 | `backend/tests/test_settings_route_boundaries.py` |
| 东西删了,它的共享记录也得跟着走。 | `backend/tests/test_sharing_forgets_on_delete.py` |
| sidecar 发得出的每一种事件,后端都要有一个分支接它。 | `backend/tests/test_sidecar_events_have_consumers.py` |
| 棘轮:**协议请求方向上声明的每个字段,sidecar 那侧都要真的读它。** | `backend/tests/test_sidecar_requests_have_readers.py` |
| 说「唯一实现 / 唯一入口 / 只有一处」的注释,要么点名守着它的检查,要么进存量名单。 | `backend/tests/test_single_point_claims_name_their_guard.py` |
| 棘轮:**官网文档两种语言要对得上,而且别把数目写死错**。 | `backend/tests/test_site_docs_stay_in_sync.py` |
| 结构性约束:**「有哪几种输入素材角色」只有一个产地。** | `backend/tests/test_source_roles_have_one_home.py` |
| `sqlite3.connect()` 不许直接当 `with` 用 —— 那个 with 管事务,不关连接。 | `backend/tests/test_sqlite_connections_are_closed.py` |
| 取当前帧走的是**渲染那条路**,不是抓预览的画布。 | `backend/tests/test_still_frame_goes_through_render.py` |
| 外部命令只从一个口子出去。 | `backend/tests/test_subprocess_has_one_door.py` |
| 棘轮:测试里「睡一下再看」「耗时 < N 秒」只减不增 —— 测试等事件、等条件,不等时间。 | `backend/tests/test_tests_wait_for_events_not_time.py` |
| 文本 I/O 必须**自己说清用什么编码**,不能问平台要。 | `backend/tests/test_text_io_never_inherits_the_platform_encoding.py` |
| 知识库整块删掉了。 | `backend/tests/test_the_knowledge_base_is_gone.py` |
| 「能对时间线做什么」只有**一份**数据,而且它说的是实话。 | `backend/tests/test_timeline_ops_have_one_list.py` |
| 工具定义加系统提示,不超过本机回退窗口的六成 —— 每轮都重发、又压不掉的那一块,得有个明说的上限。**按每一处量**。 | `backend/tests/test_tool_definitions_budget.py` |
| 结构性约束:**docs/MCP.md 的工具清单与代码一致**。 | `backend/tests/test_tool_docs_in_sync.py` |
| 面向用户的节点说明和占位里**不摆模板写法**(`{{…}}`)。 | `backend/tests/test_ui_copy_has_no_template_syntax.py` |
| 结构性约束:**记进操作日志的每一种操作,都要登记它的逆操作。** | `backend/tests/test_undo_registry.py` |
| 结构性约束:**记账只有一个入口**。 | `backend/tests/test_usage_single_entry.py` |
| 两道只减不增的棘轮:**领域层不提交事务**、**授权不写在路由里**(见 core/unit_of_work)。 | `backend/tests/test_use_case_boundaries_ratchet.py` |
| 棘轮:后端报给人看的错误**不写死中文句子**。 | `backend/tests/test_user_facing_errors_are_translated.py` |
| 结构性约束:`ai/runtime/workers/` 下的脚本**不许 import app.***。 | `backend/tests/test_workers_run_under_another_interpreter.py` |
| 棘轮:工作流跑失败时那句话,也得跟着读的人的语言走。 | `backend/tests/test_workflow_errors_speak_your_language.py` |
| 条件字段的后端一侧：跑 contracts/workflow-field-activation.json。 | `backend/tests/test_workflow_field_activation_parity.py` |
| 「一定不会跑」与「会跑的节点引用了它」的后端一侧:跑 contracts/workflow-never-run-cases.json。 | `backend/tests/test_workflow_never_run_parity.py` |
| 棘轮:**从 config 拿实体 id 的节点,必须把它收进本工作流的工作区**。 | `backend/tests/test_workflow_nodes_stay_in_their_workspace.py` |
| 「引用了一个节点没有的输出」的后端一侧:跑 contracts/workflow-output-reference-cases.json。 | `backend/tests/test_workflow_output_reference_parity.py` |
| 开始节点选项参数「值不在选项里」的后端一侧:跑 contracts/workflow-start-option-cases.json。 | `backend/tests/test_workflow_start_option_parity.py` |
| 写权限是**写出来的**,不是从请求方法推出来的。 | `backend/tests/test_write_permission_is_explicit.py` |
| | |
| 素材缓存的键:取数可以细,失效必须粗。 | `frontend/src/api/queryKeys.test.ts` |
| 结构性约束:**会发请求的按钮必须反映它自己的进行中状态**。 | `frontend/src/app/buttonPending.test.ts` |
| 结构性约束:**装智能体正文的滚动容器,横向也要锁死。** | `frontend/src/app/chatScroll.test.ts` |
| **会裁切的盒子不能用 `leading-none`。** | `frontend/src/app/clippedText.test.ts` |
| `createContext` 所在的模块不许引 UI 组件。 | `frontend/src/app/contextIdentity.test.ts` |
| 自定义 CSS 能不能压过应用样式,全看**注入的那个 `<style>` 排在哪**。 | `frontend/src/app/customCss.dom.test.tsx` |
| 界面文案表里**不出现模板写法**(`{{…}}`)。 | `frontend/src/app/messages.noTemplateSyntax.test.ts` |
| 文案表里**不留没人用的条目**。 | `frontend/src/app/messages.unused.test.ts` |
| 页面**按需加载**,不许被直接 import 回主包。 | `frontend/src/app/pageChunks.test.ts` |
| 棘轮:**画布连线长什么样,只在 components/app/canvasEdges 一处说。** | `frontend/src/components/app/canvasEdges.test.ts` |
| 棘轮:**每块 React Flow 画布的删除键都走 useCanvasDeleteKey**。 | `frontend/src/components/app/useCanvasDeleteKey.test.ts` |
| 按钮的尺寸刻度只能来自 token,不能在调用点重定义。 | `frontend/src/components/ui/buttonScale.test.ts` |
| 棘轮:**按钮、输入框、下拉触发器的高度只有一个出处**(control-size.ts)。 | `frontend/src/components/ui/controlSize.test.ts` |
| 智能体时间线的字号**只有一个出处**。 | `frontend/src/design/agentTypeScale.test.ts` |
| 棘轮:**接口的路径只写在 `api/domains/*` 里**,而且这个数字只减不增。 | `frontend/src/design/apiSeam.test.ts` |
| Tailwind 任意选择器里的 BEM 类名,`__` 必须写成 `\_\_`。 | `frontend/src/design/arbitrarySelectors.test.ts` |
| 去某一张画板只走 `lib/deepLink` 的 `openBoard`,没人再手写 `#/boards?board=…`。 | `frontend/src/design/boardNavigation.test.ts` |
| 「画布操控方式」(触控板 / 鼠标)只有一种样子:components/app/CanvasInputModeMenu。 | `frontend/src/design/canvasInputMode.test.ts` |
| 同一行里的控件要一样高。 | `frontend/src/design/controlRhythm.test.ts` |
| 可编辑的富文本框(tiptap)要有读屏念得出的名字:`aria-label`,外加 `role="textbox"`、`aria-multiline`。 | `frontend/src/design/editorNames.test.ts` |
| 输入框和下拉触发器的高度只能来自 `size` 档位,不能在调用点用 className 改。 | `frontend/src/design/fieldScale.test.ts` |
| 锁了行轴就得锁列轴 —— 只写 `grid-rows` 会让隐式列按 max-content 定尺。 | `frontend/src/design/gridAxes.test.ts` |
| 只有图标的按钮必须有名字:读屏念的 `aria-label`,和悬停时看得见的说明。 | `frontend/src/design/iconButtons.test.ts` |
| 「导入」「导出」的图标方向和字对得上:导入是箭头**进来**,导出是箭头**出去**。 | `frontend/src/design/importExportIcons.test.ts` |
| 挨着一个值、一行说明的次要动作走 Button 的 `variant="inline"`(行内动作),不摆正文字号的按钮。 | `frontend/src/design/inlineActions.test.ts` |
| 键帽只有一种长相:`<kbd>` 只在 components/ui/kbd.tsx 里写。 | `frontend/src/design/keycaps.test.ts` |
| 棘轮:**底下那几层不许认识功能模块**。 | `frontend/src/design/layering.test.ts` |
| 同级元素的重复间距只由父容器控制。 | `frontend/src/design/layoutRhythm.test.ts` |
| 菜单和选值下拉的宽度只在共用组件里定,调用方不写。 | `frontend/src/design/menuWidths.test.ts` |
| 动效只用一套刻度,并且尊重「减少动态」。 | `frontend/src/design/motion.test.ts` |
| 界面里不用原生 `<select>`,也不用浏览器自带的媒体控件条(`<audio controls>` / `<video controls>`)。 | `frontend/src/design/nativeControls.test.ts` |
| 悬停说明不用原生 `title`。 | `frontend/src/design/nativeTitles.test.ts` |
| 在跑的时候点不了的按钮,要让人看得出它在跑:转圈 + `aria-busy`,不能只是变灰。 | `frontend/src/design/pendingButtons.test.ts` |
| 仓库链接只能指向 **main**,而且只能指向真实存在的路径。 | `frontend/src/design/repoLinks.test.ts` |
| 选项来自服务端的下拉,要么走 OptionPicker(过阈值自动换成可搜索的那版),要么给出理由。 | `frontend/src/design/searchableLists.test.ts` |
| 渲染外来数据的那几块各自有错误边界(components/app/errorBoundary 的 SectionBoundary):出错只换掉自己。 | `frontend/src/design/sectionBoundaries.test.ts` |
| 加载占位一律走 components/ui/skeleton 的扫光,不再有各写各的 animate-pulse 灰块。 | `frontend/src/design/skeletons.test.ts` |
| 棘轮:测试里拿真计时器「等 N 毫秒」只减不增 —— 测试等条件(`waitFor` / `findBy*`),要推时间就用假计时器。 | `frontend/src/design/testsWaitForConditions.test.ts` |
| 截断的字悬停看得到全文:截断一律走 `Truncate`。 | `frontend/src/design/truncatedText.test.ts` |
| 界面字号走 token,不写死像素。 | `frontend/src/design/typeScale.test.ts` |
| 棘轮:界面上给人看的字**走文案表**(`app/messages.ts` 的中英两份),不在组件里写死中文。 | `frontend/src/design/uiTextIsTranslated.test.ts` |
| tokens.css 里给全局兜底的那几条规则,**必须写在 @layer 里面**。 | `frontend/src/design/unlayeredGlobals.test.ts` |
| 第三方组件的样式表**必须进主包**,而且**必须进 vendor 层**。 | `frontend/src/design/vendorStyles.test.ts` |
| 画板上每一块格子面板都套同一个壳(BoardComposerShell),不再各写各的外框。 | `frontend/src/features/boards/composerShell.test.ts` |
| 棘轮:**画布上的叠放顺序不许在调用处现挑一个数。** | `frontend/src/features/canvasLayers.test.ts` |
| 配音完成后要刷**哪些**缓存。 | `frontend/src/features/editor/dubRefresh.test.ts` |
| 剪辑台上的分段 tab 只有一种长相。 | `frontend/src/features/editor/editorTabRhythm.test.ts` |
| 画不出来时的那块提示,必须在监视器的**最上层**。 | `frontend/src/features/editor/playback/previewOverlayLayer.test.ts` |
| 字幕翻译的引擎选择必须真的传到后端。 | `frontend/src/features/editor/subtitleTranslateEngine.test.ts` |
| 转写正跑着的时候,逐字稿面板不能说「还没有转写结果」。 | `frontend/src/features/editor/transcriptBusyState.test.ts` |
| 功能模块之间**不得互相依赖**。 | `frontend/src/features/featureBoundaries.test.ts` |
| 弹层的横向必须锁死。 | `frontend/src/features/media/urlImportLayout.test.ts` |
| 设置页里的一项是**一行**,不是一张带边框的卡片。 | `frontend/src/features/settings/rowsNotCards.test.ts` |
| 设置组件自己拥有纵向节奏，调用方不能再从外面叠加一层。 | `frontend/src/features/settings/spacingContract.test.ts` |
| **连线指向的口,卡片上一定画着。** | `frontend/src/features/workflows/canvasPorts.dom.test.tsx` |
| 棘轮:**节点检查器不认识任何具体节点**。 | `frontend/src/features/workflows/nodeInspectorIsNodeAgnostic.test.ts` |
| 官方模板打开就是一张连好的图:画布的就绪检查里没有「未连接到流程」的节点,也没有被引用着却不会跑的。 | `frontend/src/features/workflows/officialTemplateCopies.test.ts` |
| 每个接点在中英文界面上都叫一个人话名字,同一个节点的同一侧不撞名。 | `frontend/src/features/workflows/portsHaveHumanNames.test.ts` |
| **运行时拼出来的说明里也不出现 `{{…}}`**:引用一律说成「节点标题 · 输出」。 | `frontend/src/features/workflows/refsShownAsNames.dom.test.tsx` |
| 官方工作流的名字和介绍**只写一处**。 | `frontend/src/features/workflows/workflowTemplateText.test.ts` |
| 拖柄长什么样,**全应用只有一份定义**。 | `frontend/src/lib/dragHandle.test.ts` |
| 参数控件由**模型的描述符**决定,不由 kind 写死。 | `frontend/src/lib/generationCapabilities.test.ts` |
| 结构性约束:**生成模型选择器不拿清单第一项当默认** —— 落在存着的那个、用户设的默认,或者什么都不选。 | `frontend/src/lib/generationPickerDefault.test.ts` |
| 「还没测过」不能显示成「跑不起来」。 | `frontend/src/lib/runtimeChecked.test.ts` |
| 后端时间戳**只在 `lib/time.parseServerTime` 一处**补时区。 | `frontend/src/lib/time.test.ts` |
| 无边框窗顶栏给系统按钮让位的规则,**只能有一份**。 | `frontend/src/lib/windowChrome.test.ts` |
| 自定义 CSS 的文件这一侧:文件在哪、监听盯的是什么。 | `electron/system/customCss.test.ts` |

<!-- END RATCHETS -->

---

## 契约(contracts/)

跨实现的一致性不靠注释,靠 `contracts/` 下的可执行规约:同一份语料前后端各跑一遍,两边答案
必须一样。预览与导出的画面一致性就是这么钉住的。

一句「另一侧还有一份,必须跟我一致」的注释,必须点名它归哪个契约 —— 否则这件事要不要进契约,
就取决于有没有人正好读到那句注释,而注意力不是机制(棘轮:
`backend/tests/test_cross_runtime_claims_name_a_contract.py`)。

详见 [contracts/README.md](../contracts/README.md)。
