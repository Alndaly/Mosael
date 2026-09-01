# Maintenance Hotspots

这份记录只覆盖已经显出维护风险、但不适合一次性大拆的区域。目标是把浅 Module 逐步深化:
小 Interface 后面藏更多行为,让改动有 Locality,让测试有稳定 Seam。

## Chrome 扩展边界

`browser-extension/` 有三个运行世界，不能为了少一层消息把它们揉在一起：

- `page-bridge.ts` 在页面主世界，只读站点播放器/字幕对象；不得持有 Open Studio token。
- `content.ts` 在隔离世界，负责页面 DOM、时间跳转和播放器可见矩形；不得渲染产品 UI。
- `sidepanel.ts` 是 Chrome Side Panel，持有 Open Studio 会话并调用后端；不得读取站点 Cookie。

站点字幕响应先收敛为 `TranscriptCue {start,end,text}`，再进入 UI。YouTube / B 站字段变化时只改各自
Adapter 与测试，不要让站点 JSON 形状穿进侧栏。后端 CORS 的 Origin 正则必须继续限制为 32 位 a-p
扩展 id，不能换成 `chrome-extension://.*` 或 `*`；CORS 也不能代替 Bearer 会话与工作区鉴权。

改动扩展时至少运行：

```bash
pnpm --dir browser-extension test
pnpm --dir browser-extension typecheck
pnpm --dir browser-extension build
cd backend && uv run pytest -q tests/test_browser_extension_cors.py
```

## Provider 分类 — ✅ 已解决(2026-09-01)

原目录同时混有供应商分类(`comfyui` / `evolink`)和能力分类(`image` / `speech` / `video`)，公共
`__init__.py` 又同时持有契约、具体 Adapter 导入和注册，新增引擎时必须先猜它该按哪条轴归档。

现在分成三个有 Depth 的 Module：

- `providers/contracts/`：按能力定义 Interface；
- `providers/adapters/`：平台/企业命名空间 → 产品协议族 → 能力文件；Adapter 边界由凭据与协议决定；
- `providers/registry.py`：唯一装配入口，拒绝重复注册。

领域调用方只依赖 `app.ai.providers` 公共 Interface。`test_provider_architecture.py` 固定依赖方向，防止
契约反向依赖 Adapter、领域直接选择 Adapter 或根目录再次混入供应商文件。

ByteDance 已作为命名校准：方舟生成在 `bytedance/ark/`，火山语音与播客在
`bytedance/volcano/`。`bytedance` / `volcano` / `volcano-podcast` 仍是兼容的连接 id，不因目录重排迁移。
阿里云图像、视频和语音共享百炼 DashScope 协议族，统一在 `alibaba/dashscope/`，不再把企业名
直接当成含混的协议目录。
Evolink、ComfyUI 使用同一生成协议跨图像/视频，保留单一 `generation.py`，避免浅层复制。

## 1. 发布执行器:平台 Adapter seam

**Files**

- `electron/publish/adapters.ts`
- `electron/publish/selectors.ts`
- `electron/publish/pageDriver.ts`
- `electron/publish/publishWorker.ts`

**Problem**

发布执行器是 Electron 侧的**卫星进程**,经发布专用 **worker 协议**和后端**事实源**同步状态。
这里的方向没问题;风险在本地实现的 Module 过浅:

- `adapters.ts` 曾同时承载 `PublishAdapter` Interface、平台页面选择器契约、四个平台 Adapter 实现。
- `pageDriver.ts` 是通用 WebContents Driver,但已经长出小红书等平台命名 helper,说明平台知识开始反向泄漏。
- `publishWorker.ts` 同时处理 claim/report、并发、前台占用、截图、失败分类和单任务执行脚本。

**Completed**

- 已把平台页面选择器契约抽到 `electron/publish/selectors.ts`。这是第一条低风险 seam:
  平台页面 DOM 变化现在可以独立 review,不用在 1000 行 Adapter 实现里找常量。
- 已按平台拆到 `electron/publish/adapters/*.ts`,`electron/publish/adapters.ts` 只保留统一装配入口
  `createAdapter`。调用方不感知文件布局,新增平台也不再扩大既有平台 Implementation。
- 已把小红书等平台 helper 移回对应 Adapter。`PageDriver` 只保留导航、DOM 探测、可信输入、文件、
  cookie、诊断与截图这些通用浏览器能力。

**Remaining slice**

1. 抽出 `runPublishTask(...)` Module:`publishWorker.ts` 目前仍同时拥有轮询/并发和单任务的状态回报、
   截图、blocked 映射。抽出后让 worker 只编排,并给单任务执行形成一个稳定测试 surface。

## 2. 前端全局样式 — ✅ 已解决(2026-07-22)

原 10k 行 `styles.css` 已全部内联为 TSX Tailwind v4 类(仅剩 ~40 行 portal 覆盖)。
Interface 从「全局 class 名 + cascade」变成了「设计刻度」——间距/圆角/色板约定见
`docs/ARCHITECTURE.md` 的前端关键约定。遗留风险转移到下面第 3 条(Tailwind v4 行为陷阱)。

## 3. Tailwind v4 行为陷阱(防回潮)

两个已踩实、已修、但**极易在新代码里复发**的坑:

- **`space-y` 对 inline 子元素是 no-op**:v4 把间距落在前一个子元素的 `margin-bottom` 上,
  Label 等 inline 元素的竖向 margin 无布局效果(v3 落在下一个块级兄弟的 margin-top 上才碰巧能用)。
  纵向堆叠一律 `grid gap-*` / `flex flex-col gap-*`。FormItem 已是 grid+gap。
- **`translate-*` 类与行内 `transform` 叠加**:v4 把 translate 类编译成独立的 `translate` CSS 属性,
  与行内 `transform` 是叠加关系而非覆盖 → 双重位移(字幕曾因此左漂半个画框)。
  定位由行内样式负责的元素(subtitleCss、拖拽 transform 等),className 里不得再写任何 translate/inset 定位类。

## 4. 超大 feature 文件

`WorkflowsView.tsx`(4086 行,还在长)、`EditorView.tsx`(1305)、`timeline/Timeline.tsx`(1.2k)。

按**内聚度**过一遍之后(2026-08-25 重新量过),结论和最初的判断不一样 —— 行数不是判据:

| | 行 | 查询 | state | 判断 |
| --- | --- | --- | --- | --- |
| `Timeline` | 1197 | **0** | 6 | 大而内聚,不拆 |
| `NodeInspector` | 904 | 9 | **1** | 纯渲染,904 行是**宽度**不是混乱,不拆 |
| `WorkflowEditor` | 1123 | 6 | 14 | 见下 |
| `Editor` | ~~1143~~ 925 | **37** | ~~7~~ 3 | 面板摆放已抽走;剩下的是序列变更 |

`WorkflowEditor` 曾被判定为"最该拆的那个"。重新量之后:它的 state 分四组,而**「图数据」那组
(nodes/edges/dirty/runJobId)被引用 106 次**,其余三组加起来 36 次 —— 也就是说它其实也是
「大而内聚」,只是额外粘了几块小东西。已抽走一块(`useCanvasPosture`,见下),其余三组全拆完
最多再收回百来行,换不来结构上的改变。

**已做**:`useCanvasPosture` —— 是否已 fitView / 视口动过几次 / 正不正在平移。抽它的理由不是
让文件变短(只少了 5 行),是那三个 state 和工作流没有一点关系,混在一起时读的人要先分辨
`viewportTick` 是业务概念还是渲染细节。

**已做**:`useEditorPanels` —— 哪个页签、各栏多宽、窗口够不够宽。和 `useCanvasPosture` 同一
类东西:讲的是**这个人怎么用这个工具**,不是这一刻在剪什么。抽的时候顺手合了两组抄重的边界
数字,并把「读盘兜底」和「拖动夹范围」分开(合成一个 `Number(v) || fallback` 时,把栏位拖到
宽度恰好为 0 会弹回默认宽而不是收到最小值 —— 拖得越狠反而越宽)。`useEditorPanels.test.ts`
钉住了这个区分。

**`Editor` 还剩 37 处 useQuery/useMutation**,其中约 30 条是同一件事:对当前序列做一次编辑
(插入/移动/裁剪/删除/分割/调速/变换…),共用 `applySequence` / `settleWith` /
`resyncAfterFailedDrag` 三个回调。这是一个内聚的组 —— 该整组抽成 `useSequenceMutations`,
而不是按"面板编排 / 变换与合成"那样横着切。低优先,顺手做。

> 教训:「这个文件太大了」不是一条可执行的判据。**查询数与 state 分组**才是 —— 前者说明它
> 承担了多少件事,后者说明那些事彼此相不相干。

### 4.1 三个数据装配文件 — 第一阶段已完成（2026-09-01）

`models.py`、`api/schemas/__init__.py`、`api/client.ts` 曾分别混放所有领域的 Implementation，修改画板
或调度需要在三个大文件里寻找对应块。现在 browser、publish、jobs/task-events、notifications、
scheduler、workflows、boards 已按同一领域边界完成三侧切片，稳定 Interface 仍是：

- `app.db.models`
- `app.api.schemas`
- `@/api/client`

这轮同时消除了调度页 8 处直接拼路由、重复的 job 获取函数、手写 notification schema，以及 boards
对 schema 装配入口的潜在循环依赖。完成后的聚合文件约为 1154 / 1858 / 930 行。

**Remaining**：继续拆时只选已经存在领域 Module、具有独立路由和测试面的实体；不要为了清零聚合文件
按行数机械搬运。优先候选是 assets/media、timeline/sequences 与 provider configuration。每个切片必须
保留统一重导出，并扩展后端 metadata/身份测试与前端 client 装配测试。

## 5. 预览与导出 — ✅ 已按契约收口(2026-07-28)

画面语义曾在两侧各写一份、各自绿测试、断言却相反,产出用户可见的成片不一致。现在可见层 / z 序 /
base 归属由 [`contracts/scene-cases.json`](../contracts/scene-cases.json) 双侧钉死,单侧改语义会让
两边 CI 一起红。**改这块必须先改语料**(见 `contracts/README.md`)。

调色是**有意**允许两侧不同的(ffmpeg 权威、预览近似),不要试图把它也拉进契约——那只会逼导出
放弃色阶曲线与 3D LUT。理由见 [ADR-0004](adr/0004-preview-export-parity-by-contract.md)。

## 6. `_migrate_*` 会持续堆积

运行时没有迁移框架,已装机的表结构变更全靠 `app/db/migrations.py` 里的 `_migrate_*` 链,而它只增不减。
退休判据写在 [ARCHITECTURE.md](ARCHITECTURE.md):引入时间早于**最早仍支持的 Release** 即可删。
每次停止支持某个旧版本时顺手清一轮,否则 `init_db()` 会慢慢长成考古现场。

**删之前必须核对发布时间**(`gh release list` 的时间是 UTC,git log 默认本地时区,边界很容易算反),
以及那一版实际用的数据目录/库文件名——删错的代价是用户打开看到空工作室。

## 7. 兼容垫片会**持续**制造真 bug — ✅ 已清除(2026-08-04)

上一次改名(旧名 → Open Studio)留下的一批"单向兼容垫片"曾经出过下面这些**功能性**问题,
全都不是文案问题:

- 建发布账号仍造旧前缀的登录分区 → 每个新账号一出生就是"待迁移的旧数据"
- npm dev 脚本认旧环境变量名而壳认新的 → 设新变量会让后端与壳连到**不同端口**
- 前端写旧前缀的 localStorage 键,而启动时的迁移每次把它搬走 → tab 状态反复迁移
- 一个断言在前缀改名后变成在防一个**已不存在**的名字,真正的碰撞面无人看守
- i18n 提示还在描述已被删除的回退路径 → UI 对用户撒谎

**垫片已全部删除**:环境变量前缀、数据目录/库文件改名、登录分区改名、worker 头名、工作流导入
格式、插件清单名、localStorage 键迁移、向量集合名 —— 连同它们的测试。

留下的教训,比那份清单更重要:

- **垫片的成本不在它自己,在它制造的"两种写法都行"**。只要两种都读得通,新代码就会随机长出
  旧的那一种,而它在读取期永远不报错。
- **同一个字段有两个读法,即使没有垫片也会发生**。插件的入口曾经是:清单模块读 `runtime.entry`,
  执行器自己读顶层 `entry` —— 中间靠调用方现搭一个 `{"_path", "entry"}` 的假清单粘着。两边都
  "对",谁都没坏,直到有人按现行清单写了个插件:装得上、跑不动,报的还是「未声明 entry」。
  **判据是形状的主人只有一个**:执行器要的是目录和入口这两样东西,不是"一份清单",让它直接
  要那两样,第二个读法就没有存在的地方了。
- **单向垫片也有半衰期**。它是迁移的一部分,不是架构的一部分 —— 迁完就该有人来删。判据是
  "还有没有处在旧形态的装机",而那是个能问清楚的问题。
- **改名要连生成物一起改**:后端默认值/字段改了要重跑 `cd frontend && pnpm gen:api`,
  `pyproject.toml` 的包名改了要重跑 `uv lock` —— 否则旧名会从生成文件里长回来。

## 8. 打包产物的初始化顺序:类型和单测都看不见

pi-ai 0.82 重排模块后,`api/*.lazy` 入口一旦被 esbuild 打进单文件,`createModels()` 会在
`ModelsImpl` 所在的惰性块初始化之前就跑,于是**每一轮对话**都报 `is not a constructor` ——
而源码正确、tsc 全绿、822 个后端测试全绿。这类故障只有把产物真正跑起来才看得见。

- 从 `@earendil-works/pi-ai/compat` 引入(它在包的 `sideEffects` 白名单里,不会被摇掉),
  不要用 `api/*.lazy`。换入口即绿,是**入口**问题不是版本问题。
- `agent-sidecar/test/bundle.smoke.mjs` 已接进发版 CI。它要求**正面证据**(必须走到发起网络
  请求),而不是「某个错误串没出现」—— 后者会把「进程一启动就崩」也判成通过,我就这么骗过
  自己一次。任何只做否定断言的冒烟都要按这条重写。

## 9. 授权规则一旦有第二个入口,就必须收敛成一份

确认卡现在有两个入口:HTTP 路由(bearer token)和飞书卡片(open_id → 账号绑定)。身份来源不同
是合理的,但「能不能批、批了会发生什么」只能有一份实现(`authorize_and_approve`)。

一度是两边各抄一遍。那种状态下**今天是一致的**,但谁往路由里加第四道校验,另一条就会静默漏掉
—— 在授权路径上,静默漏掉等于越权。`tests/test_feishu_card_confirmation.py` 打桩共用函数、
断言两个入口都经过它,把这件事钉住。

以后再加入口(比如 Slack、命令行)照此办理:入口只负责认身份和翻译错误。

## 10. `-webkit-app-region: drag` 会在页面之前吃掉鼠标事件

**症状与病因隔了三层**,我为此连着给出两个错误诊断(原生 `title` tooltip、窗口边缘热区),都改错了地方。

现象是「并排对比」里**第一张缩略图**的 hover 态一会儿在一会儿没有;真正的线索是用户那句
「第一张图片横向中间的位置无法被鼠标选中」——那条竖带正好压在 56px 图标侧栏的 x 区间上,而侧栏是
`-webkit-app-region: drag`。

拖拽区由 Blink 计算好交给 OS,**在页面拿到事件之前**就被消费:z-index 多高、盖在多上面、有没有
`pointer-events` 都不管用,只有显式的 `-webkit-app-region: no-drag` 能从中减掉一块。

- 任何覆盖到顶栏 / 侧栏区域的全屏叠加层,根元素都要写 `[.is-desktop_&]:[-webkit-app-region:no-drag]`,
  自身需要拖窗的子区域(如叠加层自己的工具条)再 `drag` 回来。
- **浏览器预览里复现不出来**——没有 Electron 就没有拖拽区。这类问题只能在桌面端验证;
  在预览里反复"验证通过"只会把诊断带偏,我就是这么浪费了两轮。

## 11. pi 的凭据字段名不是 OAuth 规范里的那几个

`provider_quota` 六家解析器**全部**取不到令牌、UI 一律显示「尚未授权登录」,而档案明明是已授权的。
原因是取键取的是 `access_token` / `api_key`(OAuth / OpenAI 的习惯写法),而 pi 的 CredentialStore
存的是 `{type:"oauth", access, refresh, expires}` 与 `{type:"api_key", key}`。

- 读凭据一律经 `_TOKEN_KEYS`(已含两套写法),不要在新代码里再写一次字面量键名。
- `expires` 是**epoch 毫秒**,不是秒、也不是"还剩多少秒"。按秒比会让所有令牌看起来都过期了 55 年。
- 这类"字段名对不上"的故障**类型全绿、单测全绿**,因为两侧都在自说自话。判据只有一条:
  拿真实凭据跑一次。

## 12. 同一个常量在 sidecar 和后端各写了一份

`FALLBACK_CONTEXT_WINDOW = 32000`(`agent-sidecar/src/pi.ts` ↔ `backend/app/ai/agent/host.py`)与
`CHARS_PER_TOKEN = 3.5`(`compaction.ts` ↔ `domain/context_meter.py`)。

不是疏忽:整理决策必须在 sidecar 里做(它才拿得到消息与 usage),而水位显示必须在后端算(前端只认
REST)。但**改一处不改另一处**的后果是隐性的——前端说「剩余 40%」,而 sidecar 已经按另一套数字
整理过了,用户看到的和实际发生的对不上,还没有任何报错。

改这两个值时**两侧一起改**,并在 PR 里说明。将来若要收口,方向是让后端从 sidecar 拿一次配置,
而不是再抄第三份。

## 13. 视觉输入格式归一化 — ✅ 已收口(2026-08-31)

`analysis.service.analyze_asset` 原本会先用 `browser_compatible_image` 把 HEIC 等格式转成模型可消费的
JPEG；无限画布 `boards._look_at` 却直接读原文件，并把所有非 PNG 后缀标成 `image/jpeg`。因此同一张
HEIC 在素材分析入口能成功，在画布「看图」入口却以错误 MIME 和原始字节送给模型；WebP 也会被错误
标成 JPEG。

画布现已复用 `app.media.image_preview.browser_compatible_image`：

- HEIC/HEIF 等容器由随应用打包的 `pillow-heif/libheif` 解码，生成并缓存派生 JPEG，原件不动；
- JPEG/PNG/WebP/GIF/AVIF 保留原始字节并携带真实 MIME；
- 转换失败时只跳过这一份素材，与视频抽帧失败保持相同的尽力而为语义。

这个 Seam 有足够的 Depth：素材预览、缩略图、智能体附件、素材分析和无限画布都只学习一个 Interface，
格式支持的修改具有 Locality。画布回归测试钉住 HEIC 的真实 JPEG 字节和 MIME，以及 WebP 原字节与
真实 MIME；素材分析已有独立 HEIC 回归。这里不能只检查“系统里有 ffmpeg”：Linux 发行版常裁掉 HEIC
demuxer，二进制存在不代表具备该能力。回归还会禁用 ffmpeg 路径，确保安装包使用自带解码器。图片数量、
编码大小和视频输入仍由各传输 Adapter 按自身协议
限制，不强行塞进格式归一化 Module。

## 14. `analyze_asset` 有两种调用身份，不能共用一套选模假设

普通 HTTP/MCP 请求与 AI Studio 工具回连虽然进入同一个路由，却不是同一种身份语义：

- 普通请求没有 `agent_session_id`，按素材分析配置选择 `direct` 模型；
- 智能体工具使用短期 service token，`AuthSession.agent_session_id` 是当前连接、模型、工作区与
  `analysis_video_mode` 的事实源；不能相信工具参数自报 profile/model/mode；
- 当前连接是 API Key 时走后端 `direct` Adapter；是订阅/OAuth 时走无工具、无记忆的 `gateway`，
  不需要也不允许用虚构的 `base_url` 修复；
- Gateway 只接受图片 block，不接受原生视频。`auto` / `frames` 发送均匀采样帧(传输层最多保留 8 张)
  与已有转写；显式 `native` 必须失败并建议抽帧，不能暗中换模式；
- sidecar 必须依据当前模型元数据接受视觉输入。模型不支持图片时明确失败，不能丢掉帧后只分析文字。

这里最危险的回归不是请求失败，而是**静默换模型**：工具身份丢失后回落到独立选模器，用户选 Kimi
却可能在另一连接上付费。回归测试至少要覆盖 session-bound OAuth 模型、视频帧确实进入 Gateway、
会话 mode 覆盖工具参数，以及 OAuth `native` 的明确错误。

## 15. 画布节点状态属于节点，不属于选中面板

图片/视频/便签/音频节点的提示词、模型、参数、引用素材与任务状态都落在 `BoardItem.form` /
`BoardItem.run`。选中面板只编辑这份数据，不能另存一份组件局部状态后在二次点击时重新推导；否则
占位文案会变化、失败节点会继续转圈、刷新后也无法恢复轮询。

服务端 `normalize_canvas` 负责旧字段迁移，`_keep_arrived_results` 负责在 stale autosave 晚到时保住
任务终态。改画布序列化或任务回执至少覆盖：失败立即停 loading、重新打开仍保留表单、成功/失败终态
不被旧快照覆盖、来源素材已删时创建任务前就给出明确错误。连线命中范围应覆盖可见 `+` 号，而不是只
覆盖 React Flow 默认的细边界。

状态视觉必须读统一的 `itemRunStatus`：idle 中性、queued 等待、running 动态主色、succeeded 成功色、
failed 错误色、cancelled 虚线弱化；即使节点已有旧产物，重跑失败也要在节点外壳上看得出来。表单的
“重置”有两层：产物版本变化后从 `BoardItem.form` 重新水合组件局部状态；成功后由领域层清空已消费的
一次性输入（prompt、手动引用素材），同时保留模型等稳定选择。失败/取消不能清空，拖动和逐字保存更
不能参与 reset key，否则会丢失光标和重试输入。同步便签写作也必须把 running/succeeded/failed 写进
`BoardItem.run`，不能只让提交按钮转圈。
正文中的 `@` 引用还要把 TipTap JSON 存进 `form.prompt_document`；`prompt` 只是模型所需纯文本，
`mentioned_asset_ids` 只说明引用了谁，两者都无法单独恢复 chip 在句子中的位置。
引用在文档结构中是不可拆的 `assetRef` 原子节点，视觉使用“小缩略图 + 素材名”的紧凑胶囊；不要把它
降级成普通文本，否则重新聚焦节点后会丢失素材身份与预览能力。
节点内的排队、运行和失败文案必须同时给内容 grid `min-w-0`、给文本 `overflow-wrap:anywhere`；供应商
错误常带连续 URL/请求 ID，只做 `line-clamp` 会裁高度，却不会阻止长 token 把内容盒撑出节点宽度。
画板视频时长的离散值和整数区间统一呈现为参数行 `Pick`：区间要展开 min..max 的每个整数，不能用原生
`number` spinner（视觉不统一），也不能只列端点（会丢掉区间中合法的时长）。
生成面板要给模型与参数留出稳定宽度；参数触发器不能参与 flex shrink，空间仍不足时让参数组换行，不能
把模型、画幅、分辨率、时长分别压成一串省略号。节点上方操作条与下方生成面板的控件密度应保持一致。
上下浮层到节点边框的距离统一读取 `BOARD_NODE_PANEL_OFFSET`；新增面板不能直接在 `NodeToolbar` 上写
`offset` 数字，否则上方操作条和下方表单会再次出现一边疏、一边密。

视频转 GIF 是另一条相同的数据归属规则：源视频只读，新 GIF 记录 `derived_from_asset_id` 与转换参数；
素材页右键和工作流节点必须汇到同一个领域函数，不能各自拼 ffmpeg 命令。

## 16. 弹窗宽度必须按“不可信长文本”设计

供应商错误常同时包含 URL、JSON、request id 与无空格错误码。普通中文句子能换行，不代表这些内容也
能换；只给段落 `break-words`，而 flex/grid 子项仍是默认 `min-width:auto`，弹窗一样会被 min-content
撑宽。

- `DialogContent` 的实际宽度必须限制在 `100vw - 2rem`，`ModalShell` 与滚动 body 都要 `min-w-0`，
  body 只允许纵向滚动。
- 业务弹窗采用与 Revornix 一致的三段结构：外壳 `overflow-hidden`，header/footer 分别
  `sticky top-0` / `sticky bottom-0` 且有与中段同源的半透明 `popover` 背景、backdrop blur 与
  分隔线，只有 body 滚动。body 的 `py-5`
  是焦点环安全区，不是可删的装饰间距；删成只有 `pb-*` 后，第一个输入框的蓝色顶边会再次被
  overflow 裁掉。实现统一落在 `components/app/modals.tsx`，业务弹窗不要各自拼结构。
- `CommandDialog` 虽然不使用业务三段式，外层也必须保持 `bg-popover/90 + backdrop-blur-xl`，内部
  `Command` 使用透明背景；否则内部的默认 `bg-popover` 会把外层透明度完全盖掉。录制器这类 footer
  左侧有说明、右侧有主按钮的弹窗，须在单个 `w-full` 包装层上显式设置 `items-center justify-between`，
  不能只依赖通用 footer 的右对齐。
- 展示服务端错误的正文使用 `whitespace-pre-wrap [overflow-wrap:anywhere]`：保留有意义的换行，同时
  允许长 URL/JSON 在任意位置折行。
- 事件时间线、子任务列表等嵌套 grid 的内容列必须是 `minmax(0,1fr)`，对应子项也要 `min-w-0`；只在
  最内层补断词规则无法修复父级固有宽度。

## 17. 生成描述符不能替未知模型猜能力

能力目录、Adapter、三个生成界面与 MCP 是一条契约链：

- `known_capabilities_for` 只给提交校验使用；精确查不到表示平台不知道，不能套用同 vendor 的第一项；
- `capabilities_for` 给 UI/MCP 的未知模型返回 `parameter_keys: []`，仍可提交提示词，但不自动发送尺寸、
  时长、画幅或素材；前端必须区分“字段缺失的旧描述符”和“明确为空”；
- Adapter 只翻译已声明参数。新增 `request.parameters.get("x")` 时，必须同时声明 `x` 并让 UI/MCP
  能表达它；编辑专属等模式级参数在契约支持模式范围前不要伪装成全模型参数；
- `supports_audio` 只表示输出可能有声音，只有 `supports_generate_audio` / `boolean_parameters` 才能
  生成开关；枚举放 `parameter_choices`，分辨率限定时长放 `duration_by_resolution`；
- 外链和素材库文件是同一个领域角色，必填、上限、互斥和搭伴校验必须同时计数。

回归至少运行 `test_generation_capability_contract.py`、`test_capabilities_match_reality.py`、
`test_adapters_read_only_declared_parameters.py` 与前端 `generationCapabilities.test.ts`。供应商结果下载
必须走 `media_transfer`，不得复用携带 API 凭据的提交客户端去请求预签名对象存储地址。

## 18. 音色创建入口必须共享录音与弹窗生命周期

设置页“新建音色”和剪辑页“上传克隆”是同一个领域动作：两者都产生参考音频 `File` 并调用
`uploadVoice`，所以统一使用 `features/voice/VoiceCreationDialogs.tsx`。剪辑页“从说话人”需要项目素材和
Transcript，保留独立 `VoiceFromSpeakerDialog`，但不能退回侧栏内联表单；内联会改变列表与空状态高度，
也让窄侧栏同时承担表单布局。

麦克风只由 `useReferenceAudioRecorder` 持有。修改时至少验证：权限拒绝与录音器不可用文案不同；小于
有效阈值的空录音不覆盖已选文件；取消/关闭/卸载会停止所有 tracks；实际 MIME 决定文件扩展名；设置页
和剪辑页都能打开带 sticky footer 的同一上传/录制弹窗。“从说话人”弹窗还要验证素材切换后清空旧的
speaker，且没有 Transcript 时给出明确原因。

剪辑页的音色库区域必须由 `engine === "clone"` 整体守卫（标题、卡片、空状态、编辑表单、创建弹窗
一起控制），不能只隐藏选择框。远程引擎使用 `/api/tts/voices` 返回的供应商目录；回归测试需要覆盖从
本地克隆切到远程引擎后，本地音色库与创建动作全部消失。

## 19. 供应商连接表单不能重新混入模型默认

`provider_profiles` 已没有 `default_model`；预设里 `storage=default_model` 仅用于创建连接时调用
`provider_models.upsert` 加入第一条模型记录。编辑弹窗必须通过 `fieldsForMode` 隐藏它，不能让用户误以为
改的是能力默认。真正的默认在 `provider_defaults`，真正的模型增删改在 `ProviderModelList`。

Endpoint 标签描述供应商连接协议，不描述用户碰巧从哪个能力分区打开弹窗。尤其百炼一条连接横跨
chat/image/video/tts，固定写“对话 Endpoint”会在 AI 视频页制造错误语义；应使用供应商级名称，并在
hint 说明各 Adapter 如何把兼容地址归一到原生 API 根。

## 20. 工作区智能体入口必须共享会话壳与布局语义

剪辑、工作流和创意画板都渲染 `components/agent/CanvasAgentChat.tsx`。这不是三个相似聊天框，而是
同一会话池在三个工作上下文里的入口：只有 `contextLine`、空态文案与输入示例不同。消息流、附件、
队列、确认卡、上下文水位、会话创建/删除/切换只能在共享壳里维护。

- 停靠态必须参与业务页 grid/flex 布局，是一列真实宽度；只有悬浮态可以 fixed overlay。否则剪辑页
  打开助手就会盖住监看器，且面板宽度变化无法被时间线布局感知。
- 左上角直接显示当前会话名称，由 `AgentSessionSwitcher` 提供搜索和切换。标题可省略，点击面保持
  扁平；不要恢复“AI 助手 + 带框下拉”两套并列标题。
- 切会话前必须中止旧 SSE、清空本地流态再写入 selection key；创建会话要先播种 React Query 缓存，
  否则列表重拉的空窗会回落到旧会话。
- 新的工作区入口只能传上下文并复用组件，不能复制 `CanvasAgentChat`。回归至少覆盖：当前标题、搜索、
  空结果、切换、中止旧流，以及 docked 根节点无外框且占据布局列。

## Verification rule

每个 slice 至少跑:

- `pnpm build:publisher` when touching `electron/publish/**`
- `cd frontend && pnpm exec tsc -b --noEmit && pnpm vitest run` when touching frontend
- `cd backend && ./.venv/bin/python -m pytest -q` when touching backend — **跑满,别只跑相关文件**:
  测试间的隔离缺陷(线程写进正被重建的库、状态串台)只在满载和特定顺序下才现形,单文件全绿说明不了什么
- `pnpm --dir agent-sidecar test:bundle` when touching sidecar deps or its build config
- `cd website && pnpm build` when touching 官网或文档(它不在 release CI 里,坏了不会有人告诉你)
- targeted browser smoke only when the change affects actual platform page driving
- **桌面端**(不是浏览器预览)when the change touches 拖拽区 / 无边框窗 / 内嵌浏览器 —— 见第 10 条
- **拿真实凭据跑一次** when the change touches 供应商凭据、令牌刷新或额度解析 —— 见第 11 条
