# 0111 — macOS 灵动岛用独立 NSPanel,并为 ActivityKit 留出 Provider

- 状态:已采纳
- 日期:2026-11-25

## 背景

任务中心需要把「正在跑、刚完成、刚失败」摆在 macOS 顶部。要求是**看起来像系统灵动岛**,
不是 Mosael 窗口内部的一颗 React 元素。

Apple 的平台事实有两层:

- macOS 26 的 Live Activities 只中继 iPhone 上已有的活动;原生 Mac App 不能发起。
- 原生 Mac App 的 ActivityKit 直到 **macOS 27.3 Beta** 才开放;Xcode 27.2 的 SDK 仍把
  `ActivityAttributes`、`ActivityConfiguration`、`DynamicIsland` 标成 macOS unavailable。
- 在此之前,NotchNook / Boring Notch / NotchBay 这类工具都用**无边框 NSPanel** 浮层:
  `level = .statusBar`、`collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]`,
  用 `NSScreen.safeAreaInsets` / `auxiliaryTopLeftArea` 取刘海几何。

## 决策

### 1. 当前版本用独立 NSPanel

- helper 是随包分发的独立 Mach-O 进程,不是 Electron 窗口,也不是主窗口里的 DOM。
- 主进程经 stdin 每行一份 JSON 快照推送活动;helper 经 stdout 回传 `{"type":"open","id"}`。
- 面板不进入 Dock,不抢焦点;鼠标只在岛体和展开区域命中,其他像素点穿到菜单栏。
- 顶部中间是硬件刘海:用一个 even-odd 的 mask 把它挖掉,黑色岛体从左右菜单栏延伸到下方展开列表,
  中间没有描边、没有第二层卡片。视觉上是一块。
- 展开用高度 + 透明度弹簧动画,不做位移或缩放;收起同理。

### 2. 数据方向保持单向

任务中心知道「哪个任务刚结束」,所以由它发布活动;系统层只消费,不反查后端。
序列化后的字段只有 `id / state / title / detail / progress / priority`;React 图标和点击回调
不过进程边界。点击事件回到渲染层后按 id 找回发布者的 `onOpen`。

### 3. 未来接 ActivityKit 时替换 Provider,不动上层

当 macOS 27.3 SDK 可用时,新增 `SystemActivityProvider`:

- Swift `ActivityAttributes` + Widget Extension 的 `ActivityConfiguration` / `DynamicIsland`;
- 与当前 NSPanel 共用同一个活动模型与 IPC;
- 旧系统继续走 `NotchPanelProvider`,新系统走系统 Provider。

Widget Extension 需要独立的 App ID / Provisioning Profile,并嵌进 `Mosael.app/Contents/PlugIns`;
这部分只在具备 27.3 SDK 与描述文件后启用,不在当前版本假装支持。

## 后果

- 当前所有支持的 macOS 都能用与 NotchNook 同一路线的岛;不需要 27.3。
- 真系统 ActivityKit 只在 27.3+ 出现;旧系统不会因为新增 widget extension 而启动失败,
  只是继续使用 NSPanel。
- helper 被 `electron-builder` 作为嵌套原生代码签名;包内缺少 helper 时能力静默关闭,
  托盘、通知与任务中心照旧。
