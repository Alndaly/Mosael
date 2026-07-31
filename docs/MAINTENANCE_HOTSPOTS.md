# Maintenance Hotspots

这份记录只覆盖已经显出维护风险、但不适合一次性大拆的区域。目标是把浅 Module 逐步深化:
小 Interface 后面藏更多行为,让改动有 Locality,让测试有稳定 Seam。

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

**Started**

- 已把平台页面选择器契约抽到 `electron/publish/selectors.ts`。这是第一条低风险 seam:
  平台页面 DOM 变化现在可以独立 review,不用在 1000 行 Adapter 实现里找常量。

**Next slices**

1. 把 `BilibiliAdapter` + B 站专属 DOM script 移到 `electron/publish/adapters/bilibili.ts`,
   `createAdapter` 保持行为不变。
2. 把 `PageDriver` 里的平台命名 helper 移回对应平台 Adapter,让 Driver 只保留导航、CSS/text 探测、输入事件、CDP 文件上传、截图、取消。
3. 抽出 `runPublishTask(...)` Module: `publishWorker.ts` 只留轮询/并发;单条任务的状态回报、截图、blocked 映射集中到一个测试 surface。

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

`WorkflowsView.tsx`(2.7k 行)、`EditorView.tsx`(1.3k)、`Timeline.tsx`(1.2k)。

按函数量过一遍之后,这三个要分开看 —— **大而内聚**的不必拆:`Timeline` 虽然 1.0k+,但只有
6 个 state、3 个 effect、**0 个查询**,主体是交互数学与绘制,拆开反而更难读。真正该拆的是
`WorkflowEditor`(929 行 / **15 个 state**:图编辑、面板开关、重命名删除弹窗、画布几何、
内嵌视图就绪状态混在一起)和 `Editor`(954 行 / **38 处 useQuery/useMutation**)。
切分方向:画布 / 节点检查器 / 节点表单;面板编排 / 变换与合成 / mutations。
低优先,顺手做,不专项大拆。

## 5. 预览与导出 — ✅ 已按契约收口(2026-07-28)

画面语义曾在两侧各写一份、各自绿测试、断言却相反,产出用户可见的成片不一致。现在可见层 / z 序 /
base 归属由 [`contracts/scene-cases.json`](../contracts/scene-cases.json) 双侧钉死,单侧改语义会让
两边 CI 一起红。**改这块必须先改语料**(见 `contracts/README.md`)。

调色是**有意**允许两侧不同的(ffmpeg 权威、预览近似),不要试图把它也拉进契约——那只会逼导出
放弃色阶曲线与 3D LUT。理由见 [ADR-0004](adr/0004-preview-export-parity-by-contract.md)。

## 6. `_migrate_*` 会持续堆积

运行时没有迁移框架,已装机的表结构变更全靠 `app/core/db.py` 里的 `_migrate_*` 链,而它只增不减。
退休判据写在 [ARCHITECTURE.md](ARCHITECTURE.md):引入时间早于**最早仍支持的 Release** 即可删。
每次停止支持某个旧版本时顺手清一轮,否则 `init_db()` 会慢慢长成考古现场。

**删之前必须核对发布时间**(`gh release list` 的时间是 UTC,git log 默认本地时区,边界很容易算反),
以及那一版实际用的数据目录/库文件名——删错的代价是用户打开看到空工作室。

## 7. 更名的残留会**持续**制造真 bug,不只是不好看

「Mibu → Open Studio」改了名却没同步的地方,已经出过下面这些**功能性**问题——全都不是文案问题:

- `create_account` 仍造 `persist:mibu-<id>` 分区 → 每个新发布账号一出生就是"待迁移的旧数据"
- npm dev 脚本只认 `MIBU_BACKEND_PORT`,而 `main.cjs` 只认 `OPEN_STUDIO_BACKEND_PORT` → 设新变量会让后端与壳连到**不同端口**
- `usePersistentTab` 写 `mibu:tab:*`,而 storageMigration 每次启动把它搬走 → tab 状态反复迁移
- 一个断言 `not startswith("persist:mibu-")` 在前缀改名后,变成在防一个**已不存在**的名字,真正的碰撞面无人看守
- i18n 提示还在描述已被删除的「同级 mibu-video venv」回退 → UI 对用户撒谎

**规范名见 [CONTEXT.md 的「命名」段](../CONTEXT.md)**;`MIBU_*` / `persist:mibu-*` / `mibu.*` 键 /
`mibu.plugin.json` / `mibu-workflow` / `mibu_kb_chunks` 是**单向兼容垫片**,只许读、不许在新代码里写。

核验(应当只剩兼容层、其测试与其说明):

```bash
grep -rniE "mibu" . | grep -vE "node_modules|/\.git/|pnpm-lock|publish\.bundle\.cjs|/dist/|/release/|__pycache__|\.tsbuildinfo|/\.codegraph/"
```

**别忘了生成物**:改了后端默认值/字段要重跑 `cd frontend && pnpm gen:api`,改了 `pyproject.toml` 的
包名要重跑 `uv lock`——否则旧名会从生成文件里长回来。

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

## Verification rule

每个 slice 至少跑:

- `pnpm build:publisher` when touching `electron/publish/**`
- `cd frontend && pnpm exec tsc -b --noEmit && pnpm vitest run` when touching frontend
- `cd backend && ./.venv/bin/python -m pytest -q` when touching backend — **跑满,别只跑相关文件**:
  测试间的隔离缺陷(线程写进正被重建的库、状态串台)只在满载和特定顺序下才现形,单文件全绿说明不了什么
- `pnpm --dir agent-sidecar test:bundle` when touching sidecar deps or its build config
- `cd docs-site && pnpm run build` when touching docs-site(它不在 release CI 里,坏了不会有人告诉你)
- targeted browser smoke only when the change affects actual platform page driving
