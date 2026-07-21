# Maintenance Hotspots

这份记录只覆盖已经显出维护风险、但不适合一次性大拆的区域。目标是把浅 Module 逐步深化:
小 Interface 后面藏更多行为,让改动有 Locality,让测试有稳定 Seam。

## 1. 发布执行器:平台 Adapter seam

**Files**

- `electron/publish/adapters.ts`
- `electron/publish/selectors.ts`
- `electron/publish/pageDriver.ts`
- `electron/publish/worker.ts`

**Problem**

发布执行器是 Electron 侧的**卫星进程**,经发布专用 **worker 协议**和后端**事实源**同步状态。
这里的方向没问题;风险在本地实现的 Module 过浅:

- `adapters.ts` 曾同时承载 `PublishAdapter` Interface、平台页面选择器契约、四个平台 Adapter 实现。
- `pageDriver.ts` 是通用 WebContents Driver,但已经长出小红书等平台命名 helper,说明平台知识开始反向泄漏。
- `worker.ts` 同时处理 claim/report、并发、前台占用、截图、失败分类和单任务执行脚本。

**Started**

- 已把平台页面选择器契约抽到 `electron/publish/selectors.ts`。这是第一条低风险 seam:
  平台页面 DOM 变化现在可以独立 review,不用在 1000 行 Adapter 实现里找常量。

**Next slices**

1. 把 `BilibiliAdapter` + B 站专属 DOM script 移到 `electron/publish/adapters/bilibili.ts`,
   `createAdapter` 保持行为不变。
2. 把 `PageDriver` 里的平台命名 helper 移回对应平台 Adapter,让 Driver 只保留导航、CSS/text 探测、输入事件、CDP 文件上传、截图、取消。
3. 抽出 `runPublishTask(...)` Module: `worker.ts` 只留轮询/并发;单条任务的状态回报、截图、blocked 映射集中到一个测试 surface。

## 2. 前端全局样式:视觉 Module ownership

**Files**

- `frontend/src/app/styles.css`
- `frontend/src/app/main.tsx`
- feature views under `frontend/src/features/`

**Problem**

`styles.css` 接近 10k LOC,Interface 实际上是“所有全局 class 名 + cascade 顺序 + specificity”。
这让它成为浅 Module:改发布页或工作流浮窗时,需要担心编辑器、设置、AI Studio 的全局选择器。

**Safe direction**

不要一次性移动大量 CSS。按 owned visual Module 迁移:

1. app shell/chrome
2. shared primitives/forms
3. editor/monitor/timeline
4. workflow canvas + workflow AI assistant
5. publish
6. agent/tool confirmation cards
7. responsive/appearance overlays

**Next slice**

先给泛用表单布局换名。`.wf-field`、`.task-create-form` 已被 publish/scheduler/batch/settings 复用,
名字却还像 workflow/task 私有 class。下一步应新增 generic alias,迁移一个非 workflow 调用方,
旧 class 暂留一轮,避免视觉大震荡。

## Verification rule

每个 slice 至少跑:

- `pnpm build:publisher` when touching `electron/publish/**`
- `cd frontend && pnpm exec tsc -b --noEmit && pnpm vitest run` when touching frontend
- targeted browser smoke only when the change affects actual platform page driving
