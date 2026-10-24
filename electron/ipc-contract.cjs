/**
 * The single runtime contract for communication across Electron processes.
 *
 * Grouping by transport is intentional: `invoke` must have one `ipcMain.handle`,
 * `send` one `ipcMain.on`, and `event` flows from main to renderer.  Payloads
 * entering the privileged main process are decoded here before feature handlers
 * receive them.
 */
const IPC = Object.freeze({
  invoke: Object.freeze({
    checkUpdates: "mosael:check-updates",
    // 开发时主进程过期了没有、要求重启(见 dev-staleness.cjs / dev-loop.cjs)。
    mainStatus: "mosael:main-status",
    restartMain: "mosael:restart-main",
    recordingStatus: "recording-permissions:status",
    recordingRequest: "recording-permissions:request",
    recordingOpenSettings: "recording-permissions:open-settings",
    //: macOS 的屏幕录制没有「主动请求」接口:只能靠一次真实抓屏尝试把应用登记进系统授权列表。
    recordingPrepareScreen: "recording-permissions:prepare-screen",
    getOpenAtLogin: "system:getOpenAtLogin",
    setOpenAtLogin: "system:setOpenAtLogin",
    customCssRead: "customCss:read",
    customCssPath: "customCss:path",
    customCssOpen: "customCss:open",
    customCssReveal: "customCss:reveal",
    dataExportDiagnostics: "data:exportDiagnostics",
    dataCreateBackup: "data:createBackup",
    dataApplyRestore: "data:applyRestore",
    // 后端连崩被认输之后,界面上的「重试」请主进程真的重拉它(见 backend-lifecycle 的 retry)。
    backendRetry: "backend:retry",
    // 路径格旁边的「选择…」:系统的选文件 / 选文件夹对话框(见 path-picker.cjs)。
    pickPath: "dialog:pickPath",
    publishLogin: "publish:login",
    publishOpenPage: "publish:openPage",
    publishInspect: "publish:inspect",
    publishNavigate: "publish:navigate",
    publishBack: "publish:back",
    publishForward: "publish:forward",
    publishReload: "publish:reload",
    publishHideView: "publish:hideView",
    publishPanelLayout: "publish:panelLayout",
    publishClosePanel: "publish:closePanel",
    publishPanelMuted: "publish:panelMuted",
    publishPanelsHidden: "publish:panelsHidden",
    // 前台会话的页面列表(左侧那一列):都作用在前台那个会话上,渲染层不点名要哪个会话。
    publishSwitchPage: "publish:switchPage",
    publishClosePage: "publish:closePage",
    publishReorderPages: "publish:reorderPages",
    publishNewPage: "publish:newPage",
    // 页面列表展开 / 收起 / 临时展开:拍下前台网页的画面、把原生视图挪开 / 放回(列表在那张画面上变形)。
    publishSnapshotPage: "publish:snapshotPage",
    // Mosael 的整窗浮层(看大图)亮着:前台网页挪到窗口外,浮层收起再放回(见 accountViews 的 ForegroundHideReason)。
    //: **声明式让位**(P2):浮层说「我要在页面上画东西、要哪种让法」,主进程折算成对原生视图的指令。
    //: 新浮层只接这一条,不必再记得四条老通道各接一次(见 publish/hostLayers)。
    publishHostLayer: "publish:hostLayer",
    // 键盘交给前台网页(顶栏、页面列表里点完之后接着打字的是网页)。
    publishFocusPage: "publish:focusPage",
    browserOpenLogin: "browser:openLogin",
    publishSignOut: "publish:signOut",
    browserClearProfile: "browser:clearProfile",
    // 内嵌 ComfyUI 画布的操控方式(触控板 / 鼠标):只在这个视图里生效,写回服务器的那一下由主进程拦下。
    comfyuiNavigation: "comfyui:navigation",
    // ComfyUI 工作台(ADR 0038 §3):开(注入桥、轮询,视图收起就停)、面板要桥做的一件事。
    comfyuiOpenWorkbench: "comfyui:openWorkbench",
    comfyuiWorkbenchCall: "comfyui:workbenchCall",
    // 浏览器会话顶栏的页面工具:只作用于前台那个内嵌视图(主进程自己认是哪个,渲染层不点名)。
    pageToolsCapture: "pageTools:capture",
    pageToolsRegionStart: "pageTools:regionStart",
    pageToolsRegionFinish: "pageTools:regionFinish",
    pageToolsVideos: "pageTools:videos",
    pageToolsImages: "pageTools:images",
    pageToolsFetchImages: "pageTools:fetchImages",
    pageToolsRead: "pageTools:read",
    pageToolsInset: "pageTools:inset",
    pageToolsSaveDownload: "pageTools:saveDownload",
    // Computer Use P0(ADR 0075):**只读地截 Mosael 自己的窗口**。没有鼠标 / 键盘 / 拖拽 / 滚动,
    // 也不走系统截屏 —— 主进程用 webContents.capturePage() 拍自己,不需要屏幕录制权限。
    // 后端够不着 ipcMain,它经 main.cjs 的回环桥以同一个通道名问(见 domain/agent/computer_use)。
    computerScreenshot: "computer:screenshot",
    computerClick: "computer:click",
    computerType: "computer:type",
    computerScroll: "computer:scroll",
    // 这一轮智能体结束了(后端在回合收尾时发):「被控制中」熄灭,但**不**等于急停 —— 下一轮还能动。
    computerEnd: "computer:end",
    // 急停 / 恢复(ADR 0075 安全 3):全局热键与界面上的按钮都走这里。
    computerStop: "computer:stop",
    computerResume: "computer:resume",
    // 「保存到本地」:系统保存框 + 主进程把字节写到用户当场选的那个位置(见 save-file.cjs)。四步走 ——
    // 开工(弹框)、写一块、收尾(改名到位)、撤掉。分四步而不是一步:素材原文件可以有 2 GiB
    // (见 publish/downloadRules.MAX_DOWNLOAD_BYTES),一条 IPC 消息装不下那么多字节。
    saveFileBegin: "saveFile:begin",
    saveFileWrite: "saveFile:write",
    saveFileEnd: "saveFile:end",
    saveFileAbort: "saveFile:abort",
  }),
  send: Object.freeze({
    titleOverlay: "mosael:title-overlay",
    systemStatus: "system:status",
    systemNotify: "system:notify",
    locale: "mosael:locale",
    // 内嵌浏览器外壳里的悬停说明交给浮层视图画在网页上面 / 收起(见 publish/floatLayer.ts)。
    floatShow: "float:show",
    floatHide: "float:hide",
    // 原生视图在前台时,右下角的提示条交给提示条那一块浮层视图画在网页上面 / 收起(ADR 0051,见 publish/floatLayer.ts)。
    // 登录排障:内嵌视图 preload 把页面自己发出的请求结果(含响应体前 200 字)回传给主进程。
    // 只收微信那两个域,只写结构化日志 —— 见 main.cjs 的 installNetProbeRelay。
    netProbe: "mosael:net-probe",
    toastsShow: "toasts:show",
    toastsHide: "toasts:hide",
  }),
  event: Object.freeze({
    fullscreen: "mosael:fullscreen",
    openTasks: "mosael:open-tasks",
    deepLink: "mosael:deep-link",
    openFiles: "mosael:open-files",
    updateAvailable: "mosael:update-available",
    mainStale: "mosael:main-stale",
    customCss: "mosael:custom-css",
    publishView: "publish:view",
    publishPanels: "publish:panels",
    browserFrame: "browser:frame",
    // 用户在内嵌浏览器里点的下载:进度、下好了、没下成(见 publish/downloads.ts)。
    pageToolsDownload: "pageTools:download",
    // ComfyUI 工作台:主进程轮询画布里的桥看到的(选中、脏标记、能力、事件);state 为 null 是会话结束了。
    comfyuiWorkbench: "comfyui:workbench",
    // 提示条那一块浮层视图上的指针(移动、松开、离开),换算成主窗口的 CSS 坐标交回渲染层,由它点真的那条提示(ADR 0051)。
    toastsPointer: "toasts:pointer",
    // 内嵌网页、工作台画布里按的 ⌘K:主进程截下来交给渲染层开命令面板(ADR 0051)。
    commandPalette: "mosael:command-palette",
    // Computer Use 的「被控制中 / 已急停」状态:{active, stopped}(见 computerUseGuard.cjs)。
    computerUseState: "computer:use-state",
  }),
});

function record(value, channel) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${channel}: payload must be an object`);
  }
  return value;
}

function requiredString(value, key, channel) {
  const text = typeof value[key] === "string" ? value[key].trim() : "";
  if (!text) throw new TypeError(`${channel}: ${key} must be a non-empty string`);
  return text;
}

function parseAuthToken(value, channel) {
  const payload = record(value, channel);
  const token = requiredString(payload, "token", channel);
  if (token.length > 16_384) throw new TypeError(`${channel}: token is too long`);
  return { token };
}

function parseRestoreStage(value) {
  const channel = IPC.invoke.dataApplyRestore;
  const payload = record(value, channel);
  const stageId = requiredString(payload, "stageId", channel);
  if (!/^[a-f0-9]{32}$/.test(stageId)) throw new TypeError(`${channel}: stageId is invalid`);
  return { stageId };
}

function parsePublishTarget(value, channel) {
  const payload = record(value, channel);
  return {
    accountId: requiredString(payload, "accountId", channel),
    platform: requiredString(payload, "platform", channel),
  };
}

function parseUrlRequest(value, channel) {
  const payload = record(value, channel);
  const url = requiredString(payload, "url", channel);
  if (!/^https?:\/\//i.test(url)) throw new TypeError(`${channel}: url must use http(s)`);
  return { url };
}

function parsePanelId(value) {
  const payload = record(value, IPC.invoke.publishClosePanel);
  return { id: requiredString(payload, "id", IPC.invoke.publishClosePanel) };
}

/** 渲染层弹窗开着时请主进程把悬浮面板收起来(原生视图永远压在渲染层之上)。 */
function parsePanelsHidden(value) {
  const channel = IPC.invoke.publishPanelsHidden;
  const payload = record(value, channel);
  if (typeof payload.hidden !== "boolean") {
    throw new TypeError(`${channel}: hidden must be a boolean`);
  }
  return payload.hidden;
}

function parsePanelMuted(value) {
  const channel = IPC.invoke.publishPanelMuted;
  const payload = record(value, channel);
  if (typeof payload.muted !== "boolean") {
    throw new TypeError(`${channel}: muted must be a boolean`);
  }
  return { id: requiredString(payload, "id", channel), muted: payload.muted };
}

/** 悬浮面板的八个缩放手柄(四角 + 四边,罗盘方位)。 */
const PANEL_HANDLES = ["n", "ne", "e", "se", "s", "sw", "w", "nw"];

/**
 * 面板几何的一次改动:`{ x, y }` 是拖标题条挪位置;带 `handle` 的是拖手柄缩放,
 * `x/y/width/height` 是指针要的矩形(不带约束,主进程按比例与边界去夹)。
 *
 * **认不出的字段一律拒收**,不「半懂地执行」。渲染层由 vite 热更新,主进程只在启动时加载这份
 * 契约 —— 开发时两边不是同一版是常态。上一版解析器只挑自己认识的键、悄悄丢掉新加的 `handle`,
 * 于是新渲染层的「拖这个手柄缩放」被旧主进程当成「挪到这里 + 改宽」执行:拖角、拖边时整张卡片
 * 跟着平移(2026-10 用户在没重启的开发应用里撞到)。拒收让这种错位当场报错,一眼看得出是版本对不上。
 */
function parsePanelLayout(value) {
  const channel = IPC.invoke.publishPanelLayout;
  const payload = record(value, channel);
  const allowed = payload.handle === undefined ? ["x", "y"] : ["handle", "x", "y", "width", "height"];
  for (const key of Object.keys(payload)) {
    if (!allowed.includes(key)) throw new TypeError(`${channel}: unexpected field ${key}`);
  }
  const number = (key) => {
    if (typeof payload[key] !== "number" || !Number.isFinite(payload[key])) {
      throw new TypeError(`${channel}: ${key} must be a finite number`);
    }
    return payload[key];
  };
  if (payload.handle === undefined) return { x: number("x"), y: number("y") };
  if (!PANEL_HANDLES.includes(payload.handle)) {
    throw new TypeError(`${channel}: handle must be one of ${PANEL_HANDLES.join(", ")}`);
  }
  return { handle: payload.handle, x: number("x"), y: number("y"), width: number("width"), height: number("height") };
}

function parseBrowserLogin(value) {
  const channel = IPC.invoke.browserOpenLogin;
  const payload = record(value, channel);
  const partition = requiredString(payload, "partition", channel);
  if (!partition.startsWith("persist:pool-")) {
    throw new TypeError(`${channel}: partition must start with persist:pool-`);
  }
  const { url } = parseUrlRequest(payload, channel);
  return {
    partition,
    url,
    name: typeof payload.name === "string" ? payload.name.trim() : "",
    proxy: typeof payload.proxy === "string" && payload.proxy.trim() ? payload.proxy.trim() : null,
    // 视图还开着就接着用,不导航(见 AccountViewManager.openView)。
    resume: payload.resume === true,
    //: 档案钉的浏览器身份;只认这两档,别的一律当没填(跟着平台规矩走)。
    identity: payload.identity === "chrome" || payload.identity === "electron" ? payload.identity : null,
  };
}

/** 清掉一个通用档案的登录数据。和 parseBrowserLogin 同一道闸:只认 persist:pool-* 分区。 */
function parseBrowserProfile(value) {
  const channel = IPC.invoke.browserClearProfile;
  const payload = record(value, channel);
  const partition = requiredString(payload, "partition", channel);
  if (!partition.startsWith("persist:pool-")) {
    throw new TypeError(`${channel}: partition must start with persist:pool-`);
  }
  return { partition };
}

/** 内嵌 ComfyUI 画布的操控方式:连接 id(分区照样由这里拼)和两种方式之一。 */
function parseComfyNavigation(value) {
  const channel = IPC.invoke.comfyuiNavigation;
  const payload = record(value, channel);
  onlyKeys(payload, ["connectionId", "mode"], channel);
  return { partition: comfyPartition(payload, channel), mode: oneOf(payload, "mode", ["trackpad", "mouse"], channel) };
}

/**
 * 开 ComfyUI 工作台(工作流库里打开一张、「新建」都走这里)。分区**由这里按连接 id 拼**(`persist:pool-comfyui-<id>`),
 * 渲染层点不了别的分区(发布账号、别的档案)。`path` 给了就打开那一张 —— 路径和宿主同一套规矩(workflows/ 里的相对路径、
 * .json 结尾、不带 ..、隐藏段和 Windows 不收的字符),只会作为字符串嵌进主进程写死的那段脚本(见 publish/comfyEditor.ts);
 * `fresh` 是新建一张;两样都不给就回到画布上开着的那张。
 */
function parseComfyWorkbenchOpen(value) {
  const channel = IPC.invoke.comfyuiOpenWorkbench;
  const payload = record(value, channel);
  onlyKeys(payload, ["connectionId", "url", "name", "path", "fresh"], channel);
  const path = payload.path === undefined || payload.path === null ? null : comfyWorkflowPath(payload.path, channel);
  if (payload.fresh !== undefined && typeof payload.fresh !== "boolean") throw new TypeError(`${channel}: fresh must be a boolean`);
  const fresh = payload.fresh === true;
  if (path && fresh) throw new TypeError(`${channel}: path and fresh are exclusive`);
  return { ...comfyConnection(payload, channel), path, fresh };
}

//: 画布上的节点号(当前显示的那一层图里的,可能是子图里的)。
//: 三种节点形状都归 **`contracts/node-shapes.json`**(`canvas_node` / `any_node` / `subgraph_path`),
//: 逐条用例由 `electron/ipc-contract.test.ts` 读那份文件跑;Python 侧读的是同一份
//: (`backend/tests/test_node_shapes_parity.py`)。跨语言各写一份正则,语料只有一份。
const CANVAS_NODE = /^-?\d{1,10}$/;
//: **文件 / 执行图里的节点号**:`12` 是根图上的、`12:5` 是根图 12 号那个子图里面的 5 号、`12:5:3` 再往里一层
//: (ADR 0042 §6 的写法)。应用表单的项、`marks.nodes` 的键都按它 —— 子图里面的节点一样放得进表单。
//: 和宿主 `backend/app/domain/workflow_library.py` 的 `_ANY_NODE` 是**同一套判据** —— 契约里是 `any_node`
//: (那一处和这一处在契约里各是一个 `implementations` 落点)。
const ANY_NODE = /^\d{1,9}(?::\d{1,9})*$/;
//: 从根图往里走的节点路径(`12:5`:根图 12 号节点那个子图里面的 5 号;ADR 0042 智能体指节点的写法),最多 16 层。
//: 定位(`locate`)走的是**画布上那一层**的节点号,可以是负的 —— 和 `ANY_NODE` 不是同一个空间,别混用。
//: 契约里是 `subgraph_path`:**它不收裸的 `12`**(那一半归上面的 `CANVAS_NODE`),和 `canvas_path`
//: (`canvas_edit._PATH` / `workbench_agent._NODE_REF` / 前端 `nodeRefs.NODE_REF`)只差这一点下界 ——
//: 那处既成的差异记在契约的 `divergence` 里。
const NODE_PATH = /^-?\d{1,10}(?::\d{1,10}){1,16}$/;
//: 子图的 id(前端给的是 UUID 那样的串)
const SUBGRAPH_ID = /^[A-Za-z0-9_-]{1,64}$/;
//: 写进画布的标记最大多大(整份;和宿主那一侧一个节点 2 MB 的上限同一个量级)
const MAX_MARKS_CHARS = 8 * 1024 * 1024;
//: 智能体改图(ADR 0042 第二步):一批最多几条、整批多大、一格值多长;新标签页里载入的一整张图多大(模板几百 KB)
const MAX_EDIT_OPS = 200;
const MAX_EDIT_CHARS = 2 * 1024 * 1024;
const MAX_EDIT_VALUE = 20000;
const MAX_OPEN_GRAPH_CHARS = 16 * 1024 * 1024;
//: 这一批里新加的节点的临时名字
const TEMP_NODE = /^\$[A-Za-z0-9_]{1,32}$/;
const CANVAS_GROUP = /^g[1-9]\d*$/;
const GROUP_COLOR = /^#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?$/;
//: 智能体对话的 id(后端的会话 id 是 32 位十六进制;留宽一点,只挡形状)
const AGENT_SESSION_ID = /^[A-Za-z0-9_-]{1,64}$/;
//: 一批改动每一种带哪些字段(插件 canvas_edit 规整过的那一份;字段的形状下面逐项查)
const EDIT_OPS = {
  add_node: ["op", "layer", "id", "type", "widgets", "title", "near"],
  remove_node: ["op", "layer", "node"],
  connect: ["op", "layer", "from", "to"],
  disconnect: ["op", "layer", "to"],
  set_widget: ["op", "layer", "node", "widget", "value"],
  set_title: ["op", "layer", "node", "title"],
  set_position: ["op", "layer", "node", "x", "y"],
  add_group: ["op", "layer", "title", "x", "y", "width", "height", "color"],
  set_group: ["op", "layer", "group", "title", "x", "y", "width", "height", "color"],
  remove_group: ["op", "layer", "group"],
  mode: ["op", "layer", "node", "mode"],
  add_io: ["op", "layer", "side", "name", "type"],
  remove_io: ["op", "layer", "side", "name"],
  promote: ["op", "layer", "node", "widget", "name"],
  unpromote: ["op", "layer", "node", "widget"],
  to_subgraph: ["op", "layer", "nodes", "name"],
  unpack: ["op", "layer", "node"],
};

/** 一段名字(控件、口、类型、标题):非空、不带控制字符、有上限。 */
function editName(value, key, channel, limit = 200) {
  if (typeof value !== "string" || !value || value.length > limit || /[\x00-\x1f]/.test(value)) {
    throw new TypeError(`${channel}: ${key} must be a name`);
  }
  return value;
}

/** 指一个节点:那一层里的编号,或者这一批里新加的临时名字。 */
function editNode(value, key, channel) {
  if (typeof value !== "string" || !(CANVAS_NODE.test(value) || TEMP_NODE.test(value))) {
    throw new TypeError(`${channel}: ${key} must be a node id or a temporary name`);
  }
  return value;
}

function editGroup(value, key, channel) {
  if (typeof value !== "string" || !CANVAS_GROUP.test(value)) throw new TypeError(`${channel}: ${key} must be a group ref like g1`);
  return value;
}

function editCoordinate(value, key, channel, positive = false) {
  if (typeof value !== "number" || !Number.isFinite(value) || Math.abs(value) > 1_000_000 || (positive && value <= 0)) {
    throw new TypeError(`${channel}: ${key} must be a finite ${positive ? "positive size" : "coordinate"} within 1000000`);
  }
  return value;
}

/** 一格控件的值:文字(有上限)、有限的数、布尔。 */
function editValue(value, key, channel) {
  const ok = (typeof value === "string" && value.length <= MAX_EDIT_VALUE) || (typeof value === "number" && Number.isFinite(value)) ||
    typeof value === "boolean";
  if (!ok) throw new TypeError(`${channel}: ${key} must be a string, a finite number or a boolean`);
  return value;
}

/** 连线的一头:`{node, name}`,node 是节点、临时名字,或子图边界的 `@in` / `@out`。 */
function editEnd(value, key, channel) {
  const end = record(value, channel);
  onlyKeys(end, ["node", "name"], channel);
  if (end.node !== "@in" && end.node !== "@out") editNode(end.node, `${key}.node`, channel);
  return { node: end.node, name: editName(end.name, `${key}.name`, channel) };
}

/**
 * 写标记、改图之前要核对的那一张(桥在页面里比):`key` 是读的时候开着的那张(轮询报的 key,前端仓库里的路径),`revision`
 * 是它那时改过几回(非负整数)。两样写进画布的调用都**必须**带着 —— 不说写给哪一张,就不写。
 */
function parseExpect(value, channel) {
  const expect = record(value, channel);
  onlyKeys(expect, ["key", "revision"], channel);
  if (typeof expect.key !== "string" || !expect.key || expect.key.length > 600 || /[\x00-\x1f]/.test(expect.key)) {
    throw new TypeError(`${channel}: expect.key must be the workflow key`);
  }
  if (!Number.isSafeInteger(expect.revision) || expect.revision < 0) {
    throw new TypeError(`${channel}: expect.revision must be a non-negative integer`);
  }
  return { key: expect.key, revision: expect.revision };
}

/**
 * 智能体改图的一批(ADR 0042 第二步,插件 canvas_edit 规整过的)。每一条只认 EDIT_OPS 里那几个字段,逐项查形状;
 * 节点在不在、口对不对、类型配不配由桥在页面里再查一遍(一条不对整批不改)。
 */
function parseEditOps(value, channel) {
  if (!Array.isArray(value) || value.length > MAX_EDIT_OPS) throw new TypeError(`${channel}: ops must be a list of at most ${MAX_EDIT_OPS}`);
  if (JSON.stringify(value).length > MAX_EDIT_CHARS) throw new TypeError(`${channel}: ops are too big`);
  return value.map((raw) => {
    const op = record(raw, channel);
    const kind = oneOf(op, "op", Object.keys(EDIT_OPS), channel);
    onlyKeys(op, EDIT_OPS[kind], channel);
    const layer = op.layer === undefined || op.layer === null ? null : op.layer;
    if (layer !== null && (typeof layer !== "string" || !SUBGRAPH_ID.test(layer))) throw new TypeError(`${channel}: layer must be a subgraph id`);
    const out = { op: kind, layer };
    if (kind === "add_node") {
      if (typeof op.id !== "string" || !TEMP_NODE.test(op.id)) throw new TypeError(`${channel}: id must be a temporary name like $a`);
      out.id = op.id;
      out.type = editName(op.type, "type", channel);
      const widgets = op.widgets === undefined ? {} : record(op.widgets, channel);
      if (Object.keys(widgets).length > 64) throw new TypeError(`${channel}: too many widgets`);
      out.widgets = Object.fromEntries(Object.entries(widgets).map(([name, one]) => [editName(name, "widget", channel), editValue(one, name, channel)]));
      if (op.title !== undefined) out.title = editName(op.title, "title", channel);
      if (op.near !== undefined) out.near = editNode(op.near, "near", channel);
    } else if (kind === "connect") {
      out.from = editEnd(op.from, "from", channel);
      out.to = editEnd(op.to, "to", channel);
    } else if (kind === "disconnect") {
      out.to = editEnd(op.to, "to", channel);
    } else if (kind === "add_io" || kind === "remove_io") {
      out.side = oneOf(op, "side", ["input", "output"], channel);
      out.name = editName(op.name, "name", channel, 100);
      if (kind === "add_io") out.type = editName(op.type, "type", channel, 100);
    } else if (kind === "to_subgraph") {
      if (!Array.isArray(op.nodes) || !op.nodes.length || op.nodes.length > 500) throw new TypeError(`${channel}: nodes must be a list`);
      out.nodes = op.nodes.map((one) => editNode(one, "nodes", channel));
      if (op.name !== undefined) out.name = editName(op.name, "name", channel, 100);
    } else if (kind === "add_group" || kind === "set_group" || kind === "remove_group") {
      if (kind !== "add_group") out.group = editGroup(op.group, "group", channel);
      if (kind !== "remove_group") {
        out.title = editName(op.title, "title", channel);
        out.x = editCoordinate(op.x, "x", channel);
        out.y = editCoordinate(op.y, "y", channel);
        out.width = editCoordinate(op.width, "width", channel, true);
        out.height = editCoordinate(op.height, "height", channel, true);
        if (typeof op.color !== "string" || !GROUP_COLOR.test(op.color)) throw new TypeError(`${channel}: color must be #RGB or #RRGGBB`);
        out.color = op.color;
      }
    } else {
      out.node = editNode(op.node, "node", channel);
      if (kind === "set_widget") {
        out.widget = editName(op.widget, "widget", channel);
        out.value = editValue(op.value, "value", channel);
      } else if (kind === "set_title") {
        out.title = editName(op.title, "title", channel);
      } else if (kind === "set_position") {
        out.x = editCoordinate(op.x, "x", channel);
        out.y = editCoordinate(op.y, "y", channel);
      } else if (kind === "mode") {
        out.mode = oneOf(op, "mode", [0, 2, 4], channel);
      } else if (kind === "promote" || kind === "unpromote") {
        out.widget = editName(op.widget, "widget", channel);
        if (kind === "promote") out.name = editName(op.name, "name", channel, 100);
      }
    }
    return out;
  });
}

/**
 * 在新标签页开一张(ADR 0042 第二步):`graph`(界面格式,有 `nodes`)加 `name`(标签的名字,不带路径分隔),再改一批 `ops`;
 * 或者只给 `path`,打开存着的那一张(和工作台「打开」同一套路径规矩)。两样不能都给。`openedBy`:是哪段智能体对话开的
 * (后端按凭据认出来的会话 id),主进程留着、不进页面,开好之后随状态报给工作台(ADR 0044 §6)。
 */
function parseOpenWorkflow(call, channel) {
  onlyKeys(call, ["op", "graph", "name", "path", "ops", "openedBy"], channel);
  const path = call.path === undefined || call.path === null ? null : comfyWorkflowPath(call.path, channel);
  const graph = call.graph === undefined || call.graph === null ? null : record(call.graph, channel);
  if (Boolean(path) === Boolean(graph)) throw new TypeError(`${channel}: give either graph or path`);
  if (graph && (!Array.isArray(graph.nodes) || JSON.stringify(graph).length > MAX_OPEN_GRAPH_CHARS)) {
    throw new TypeError(`${channel}: graph must be a UI workflow`);
  }
  const name = call.name === undefined || call.name === "" ? "" : editName(call.name, "name", channel, 120);
  if (/[\\/]/.test(name)) throw new TypeError(`${channel}: name must not contain a path separator`);
  const ops = call.ops === undefined ? [] : parseEditOps(call.ops, channel);
  if (path && ops.length) throw new TypeError(`${channel}: ops only go with a new graph`);
  const opened = { op: "openWorkflow", graph: graph ? JSON.parse(JSON.stringify(graph)) : null, name, path, ops };
  if (call.openedBy === undefined) return opened;
  if (typeof call.openedBy !== "string" || !AGENT_SESSION_ID.test(call.openedBy)) {
    throw new TypeError(`${channel}: openedBy must be an agent session id`);
  }
  return { ...opened, openedBy: call.openedBy };
}

/**
 * 工作台面板要桥做的一件事。**只认这几种,每一种的字段逐项校验**;数据随后由主进程以 JSON 编码嵌进写死的调用脚本,
 * 渲染层送不进代码:
 *
 * - setWidget:节点号、widget 名字(不带控制字符)、值(字符串 / 有限的数 / 布尔);下拉里有没有它由桥查;
 * - refreshCombos / export / save:不带别的;
 * - setMarks:节点号(根图上的 `12`,或子图里面的 `12:5`,见 `ANY_NODE`)→ 一个对象(那个节点上的 `properties.mosael`),
 *   和图上的 `extra.mosael`(对象或 null),外加写给哪一张(`expect`,见 parseExpect);
 * - locate:节点号加子图的 id(那一层里的编号),或者不给子图、节点写成从根图往里走的路径(`12:5`);
 * - readGraph:不带别的(整张图交给智能体读,ADR 0042;后端排的工作台动作也经这里查过才进桥,见 browserWorker);
 * - runControls:`phase` 只能是 before / after(「运行」前后照前端的「生成后怎样」换种子);
 * - applyOps:智能体改图的一批(见 parseEditOps)和改给哪一张(`expect`);openWorkflow:在新标签页开一张(见 parseOpenWorkflow)。两样都是后端排的
 *   工作台动作经执行器送进来的(ADR 0042 第二步),照样逐项查过。
 */
function parseComfyWorkbenchCall(value) {
  const channel = IPC.invoke.comfyuiWorkbenchCall;
  const payload = record(value, channel);
  onlyKeys(payload, ["connectionId", "call"], channel);
  const partition = comfyPartition(payload, channel);
  const call = record(payload.call, channel);
  const op = oneOf(call, "op", ["setWidget", "refreshCombos", "export", "save", "setMarks", "locate", "readGraph", "runControls",
    "applyOps", "openWorkflow"], channel);
  if (op === "applyOps") {
    onlyKeys(call, ["op", "ops", "expect"], channel);
    const ops = parseEditOps(call.ops, channel);
    if (!ops.length) throw new TypeError(`${channel}: ops must not be empty`);
    return { partition, call: { op, ops, expect: parseExpect(call.expect, channel) } };
  }
  if (op === "openWorkflow") return { partition, call: parseOpenWorkflow(call, channel) };
  if (op === "setWidget") {
    onlyKeys(call, ["op", "node", "widget", "value"], channel);
    if (typeof call.node !== "string" || !CANVAS_NODE.test(call.node)) throw new TypeError(`${channel}: node must be a node id`);
    if (typeof call.widget !== "string" || !call.widget || call.widget.length > 200 || /[\x00-\x1f]/.test(call.widget)) {
      throw new TypeError(`${channel}: widget must be a widget name`);
    }
    const v = call.value;
    const ok = (typeof v === "string" && v.length <= 4000) || (typeof v === "number" && Number.isFinite(v)) || typeof v === "boolean";
    if (!ok) throw new TypeError(`${channel}: value must be a string, a finite number or a boolean`);
    return { partition, call: { op, node: call.node, widget: call.widget, value: v } };
  }
  if (op === "setMarks") {
    onlyKeys(call, ["op", "marks", "expect"], channel);
    const marks = record(call.marks, channel);
    onlyKeys(marks, ["nodes", "extra"], channel);
    const nodes = record(marks.nodes, channel);
    const entries = Object.entries(nodes);
    if (entries.length > 1000) throw new TypeError(`${channel}: too many marked nodes`);
    for (const [id, own] of entries) {
      if (!ANY_NODE.test(id)) {
        throw new TypeError(`${channel}: marks.nodes keys must be node ids (12, or a subgraph path like 12:5)`);
      }
      record(own, channel);
    }
    const extra = marks.extra === null || marks.extra === undefined ? null : record(marks.extra, channel);
    if (JSON.stringify({ nodes, extra }).length > MAX_MARKS_CHARS) throw new TypeError(`${channel}: marks are too big`);
    return { partition, call: { op, marks: JSON.parse(JSON.stringify({ nodes, extra })), expect: parseExpect(call.expect, channel) } };
  }
  if (op === "locate") {
    onlyKeys(call, ["op", "node", "subgraph"], channel);
    const subgraph = call.subgraph === undefined || call.subgraph === null ? null : call.subgraph;
    if (subgraph !== null && (typeof subgraph !== "string" || !SUBGRAPH_ID.test(subgraph))) {
      throw new TypeError(`${channel}: subgraph must be a subgraph id`);
    }
    const node = typeof call.node === "string" ? call.node : "";
    if (!CANVAS_NODE.test(node) && !(subgraph === null && NODE_PATH.test(node))) {
      throw new TypeError(`${channel}: node must be a node id`);
    }
    return { partition, call: { op, node: call.node, subgraph } };
  }
  if (op === "runControls") {
    onlyKeys(call, ["op", "phase"], channel);
    return { partition, call: { op, phase: oneOf(call, "phase", ["before", "after"], channel) } };
  }
  onlyKeys(call, ["op"], channel);
  return { partition, call: { op } };
}

/** 一个 ComfyUI 连接的内嵌视图:分区按连接 id 拼(渲染层点不了别的分区)、地址只认 http(s)、名字只用来显示。 */
function comfyConnection(payload, channel) {
  const partition = comfyPartition(payload, channel);
  const { url } = parseUrlRequest(payload, channel);
  return { partition, url, name: typeof payload.name === "string" ? payload.name.trim() : "" };
}

/** 连接 id → 它的内嵌视图分区(`persist:pool-comfyui-<id>`)。id 只许是普通的 id,拼不出别的分区。 */
function comfyPartition(payload, channel) {
  const connectionId = requiredString(payload, "connectionId", channel);
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(connectionId)) {
    throw new TypeError(`${channel}: connectionId must be a plain id`);
  }
  return `persist:pool-comfyui-${connectionId}`;
}

/** workflows/ 里的相对路径:.json 结尾、不带 ..、隐藏段和 Windows 不收的字符(和宿主同一套规矩)。 */
function comfyWorkflowPath(value, channel) {
  const path = typeof value === "string" ? value.trim() : "";
  const segments = path.split("/");
  const badSegment = (one) =>
    !one || one.startsWith(".") || one !== one.trim() || /[\x00-\x1f<>:"|?*\\]/.test(one);
  if (!path || !path.toLowerCase().endsWith(".json") || path.length > 500 || segments.some(badSegment)) {
    throw new TypeError(`${channel}: path must be a workflow path under workflows/`);
  }
  return path;
}

/** 只认这几个键,多一个就拒(理由同 parsePanelLayout:渲染层热更新、主进程不重启时两边常常不是同一版)。 */
function onlyKeys(payload, allowed, channel) {
  for (const key of Object.keys(payload)) {
    if (!allowed.includes(key)) throw new TypeError(`${channel}: unexpected field ${key}`);
  }
}

function oneOf(payload, key, options, channel) {
  if (!options.includes(payload[key])) throw new TypeError(`${channel}: ${key} must be one of ${options.join(", ")}`);
  return payload[key];
}

/** 截屏:可见区域 / 整页长图(框选走 regionStart / regionFinish 两步)。 */
function parseCaptureMode(value) {
  const channel = IPC.invoke.pageToolsCapture;
  const payload = record(value, channel);
  onlyKeys(payload, ["mode"], channel);
  return { mode: oneOf(payload, "mode", ["visible", "full"], channel) };
}

/**
 * 截 Mosael 自己的窗口:载荷可以整个不给 —— **没有窗口可选**,能截的只有应用主窗口。
 * (曾经还有一个 `publish` 发布器窗口,但发布器早就不是独立窗口了,那一档是死分支。)
 *
 * `scale` 不在这里 —— 缩放是后端把图交给模型之前做的事(见 domain/agent/computer_use),
 * 主进程只负责拍一张原图。渲染层送不进来的字段(路径、分区、脚本)一律拒收。
 */
function parseComputerScreenshot(value) {
  const channel = IPC.invoke.computerScreenshot;
  const payload = value === undefined || value === null ? {} : record(value, channel);
  onlyKeys(payload, [], channel);
  return {};
}

/**
 * 点一下 Mosael 自己的窗口:坐标是**页面 CSS 像素**(左上角为原点),和 `capturePage` 拍出来的
 * 图同一个坐标系(缩放在后端做,见 domain/agent/computer_use)。按钮只认左/右,连点只认 1/2。
 */
function parseComputerClick(value) {
  const channel = IPC.invoke.computerClick;
  const payload = record(value, channel);
  onlyKeys(payload, ["x", "y", "button", "clickCount"], channel);
  const coordinate = (key) => {
    const n = payload[key];
    if (!Number.isInteger(n) || n < 0) throw new TypeError(`${channel}: ${key} must be a non-negative integer`);
    return n;
  };
  const button = payload.button === undefined ? "left" : payload.button;
  if (button !== "left" && button !== "right") throw new TypeError(`${channel}: button must be "left" or "right"`);
  const clickCount = payload.clickCount === undefined ? 1 : payload.clickCount;
  if (clickCount !== 1 && clickCount !== 2) throw new TypeError(`${channel}: clickCount must be 1 or 2`);
  return { x: coordinate("x"), y: coordinate("y"), button, clickCount };
}

/**
 * 在 Mosael 自己的窗口里滚动:`dy` 是滚轮格数(正 = 往下,负 = 往上);可选 `x`/`y` 指定指针位置
 * (不给就落在窗口正中 —— Chromium 的滚轮事件要一个位置)。坐标同样是页面 CSS 像素。
 */
function parseComputerScroll(value) {
  const channel = IPC.invoke.computerScroll;
  const payload = record(value, channel);
  onlyKeys(payload, ["dy", "x", "y"], channel);
  const dy = payload.dy;
  if (!Number.isInteger(dy) || dy === 0 || Math.abs(dy) > 30) {
    throw new TypeError(`${channel}: dy must be a non-zero integer between -30 and 30 (wheel notches)`);
  }
  const point = (key) => {
    if (payload[key] === undefined) return null;
    const n = payload[key];
    if (!Number.isInteger(n) || n < 0) throw new TypeError(`${channel}: ${key} must be a non-negative integer`);
    return n;
  };
  return { dy, x: point("x"), y: point("y") };
}

/** 往 Mosael 自己的窗口里输入一段文字(输入到当前焦点,走 `webContents.insertText`)。 */
function parseComputerType(value) {
  const channel = IPC.invoke.computerType;
  const payload = record(value, channel);
  onlyKeys(payload, ["text"], channel);
  const text = payload.text;
  if (typeof text !== "string" || !text) throw new TypeError(`${channel}: text must be a non-empty string`);
  if (text.length > 2000) throw new TypeError(`${channel}: text must be at most 2000 characters`);
  return { text };
}

/**
 * 一条让位声明:`{id, kind, active}`(inset 另带 `width`)。`id` 是声明者自己的名字(同一 id 后写覆盖),
 * `kind` 只能是 region / cover / overlay / panels / inset —— 不认识的让法直接拒:悄悄忽略等于
 * 「浮层被网页盖住、还查不出为什么」。
 */
function parseHostLayer(value) {
  const channel = IPC.invoke.publishHostLayer;
  const payload = record(value, channel);
  onlyKeys(payload, ["id", "kind", "active", "width", "side"], channel);
  const id = String(payload.id || "").trim();
  if (!id) throw new TypeError(`${channel}: id is required`);
  const kinds = ["region", "cover", "overlay", "panels", "inset"];
  if (!kinds.includes(payload.kind)) throw new TypeError(`${channel}: kind must be one of ${kinds.join(", ")}`);
  if (typeof payload.active !== "boolean") throw new TypeError(`${channel}: active must be a boolean`);
  const out = { id, kind: payload.kind, active: payload.active };
  if (payload.width !== undefined) {
    if (!Number.isInteger(payload.width) || payload.width < 0) throw new TypeError(`${channel}: width must be a non-negative integer`);
    out.width = payload.width;
  }
  if (payload.side !== undefined) {
    if (payload.side !== "left" && payload.side !== "right") throw new TypeError(`${channel}: side must be "left" or "right"`);
    out.side = payload.side;
  }
  return out;
}

/**
 * 框选的结果:冻结画面上的矩形,按画面的**比例**给(0–1)—— 显示尺寸只有渲染层知道,原图尺寸只有
 * 主进程知道,比例是两边都不用猜的那个量。`selection: null` 是取消。
 */
function parseRegionSelection(value) {
  const channel = IPC.invoke.pageToolsRegionFinish;
  const payload = record(value, channel);
  onlyKeys(payload, ["selection"], channel);
  if (payload.selection === null) return { selection: null };
  const rect = record(payload.selection, channel);
  onlyKeys(rect, ["x", "y", "width", "height"], channel);
  const fraction = (key, min) => {
    const n = rect[key];
    if (typeof n !== "number" || !Number.isFinite(n) || n < min || n > 1) {
      throw new TypeError(`${channel}: selection.${key} must be a number between ${min} and 1`);
    }
    return n;
  };
  const selection = { x: fraction("x", 0), y: fraction("y", 0), width: fraction("width", 0), height: fraction("height", 0) };
  if (selection.x + selection.width > 1.000001 || selection.y + selection.height > 1.000001) {
    throw new TypeError(`${channel}: selection must stay inside the frame`);
  }
  return { selection };
}

/** 取图:地址清单。主进程只取最近一次列图里出现过的地址(见 publish/pageImages.fetchImages)。 */
function parseImageUrls(value) {
  const channel = IPC.invoke.pageToolsFetchImages;
  const payload = record(value, channel);
  onlyKeys(payload, ["urls"], channel);
  const urls = payload.urls;
  if (!Array.isArray(urls) || urls.length === 0 || urls.length > 120) {
    throw new TypeError(`${channel}: urls must be a list of 1–120 addresses`);
  }
  for (const url of urls) {
    if (typeof url !== "string" || url.length > 4096 || !/^https?:\/\//i.test(url)) {
      throw new TypeError(`${channel}: every url must be an http(s) address`);
    }
  }
  return { urls };
}

/** 读正文:整页 / 选中的文字。 */
function parseReadMode(value) {
  const channel = IPC.invoke.pageToolsRead;
  const payload = record(value, channel);
  onlyKeys(payload, ["mode"], channel);
  return { mode: oneOf(payload, "mode", ["article", "selection"], channel) };
}

/** 侧栏开合:前台视图右侧让出的像素宽。 */
function parseToolsInset(value) {
  const channel = IPC.invoke.pageToolsInset;
  const payload = record(value, channel);
  onlyKeys(payload, ["right"], channel);
  const right = payload.right;
  if (typeof right !== "number" || !Number.isFinite(right) || right < 0 || right > 4000) {
    throw new TypeError(`${channel}: right must be a number between 0 and 4000`);
  }
  return { right };
}

/** 页面列表里的一页:主进程给的 id(网页的数字编号)。 */
function pageId(value, channel) {
  if (typeof value !== "string" || !/^\d{1,10}$/.test(value)) throw new TypeError(`${channel}: page id is invalid`);
  return value;
}

function parsePageId(value, channel) {
  const payload = record(value, channel);
  onlyKeys(payload, ["id"], channel);
  return { id: pageId(payload.id, channel) };
}

/** 拖动重排:整份新次序(和主进程手上的一一对上才认,见 PageList.reorder)。 */
function parsePageOrder(value) {
  const channel = IPC.invoke.publishReorderPages;
  const payload = record(value, channel);
  onlyKeys(payload, ["ids"], channel);
  if (!Array.isArray(payload.ids) || payload.ids.length === 0 || payload.ids.length > 50) {
    throw new TypeError(`${channel}: ids must be a list of page ids`);
  }
  return { ids: payload.ids.map((id) => pageId(id, channel)) };
}

/** 新建页面:地址栏里敲的那段(主进程按地址栏同一套归一:补协议、不像网址就去搜)。 */
function parseNewPage(value) {
  const channel = IPC.invoke.publishNewPage;
  const payload = record(value, channel);
  onlyKeys(payload, ["url"], channel);
  const url = requiredString(payload, "url", channel);
  if (url.length > 2000) throw new TypeError(`${channel}: url is too long`);
  return { url };
}


const FLOAT_ROOT_ATTRIBUTE = /^(?:data-[a-z0-9-]+|lang|dir)$/;

function finiteIn(value, min, max) {
  return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
}

/**
 * 一条交给浮层视图画的说明:渲染层自己渲染出来的 HTML(有长度上限)、它在窗口里的矩形、根元素上和外观有关的
 * 那几样(class、style、data-*、lang、dir —— 别的属性一律不收)。
 */
function parseFloatShow(value) {
  const channel = IPC.send.floatShow;
  const payload = record(value, channel);
  onlyKeys(payload, ["id", "html", "rect", "root"], channel);
  const id = requiredString(payload, "id", channel);
  if (id.length > 64) throw new TypeError(`${channel}: id is too long`);
  if (typeof payload.html !== "string" || payload.html.length > 65_536) throw new TypeError(`${channel}: html must be a string under 64 KiB`);
  return { id, html: payload.html, rect: floatRect(payload.rect, channel), root: floatRoot(payload.root, channel) };
}

/** 浮层画在主窗口哪一块(CSS 像素),有界。 */
function floatRect(value, channel) {
  const rect = record(value, channel);
  const { x, y, width, height } = rect;
  if (!finiteIn(x, -10_000, 10_000) || !finiteIn(y, -10_000, 10_000) || !finiteIn(width, 0, 4_000) || !finiteIn(height, 0, 4_000)) {
    throw new TypeError(`${channel}: rect must be a bounded rectangle`);
  }
  return { x, y, width, height };
}

/** 主窗口根元素上和外观有关的那几样(主题、字体、语言),浮层页照着设;别的属性一律不收。 */
function floatRoot(value, channel) {
  const root = record(value, channel);
  onlyKeys(root, ["className", "style", "attributes"], channel);
  if (typeof root.className !== "string" || root.className.length > 4_096) throw new TypeError(`${channel}: root className is invalid`);
  if (typeof root.style !== "string" || root.style.length > 16_384) throw new TypeError(`${channel}: root style is invalid`);
  const attributes = record(root.attributes, channel);
  const entries = Object.entries(attributes);
  if (entries.length > 32) throw new TypeError(`${channel}: too many root attributes`);
  for (const [name, text] of entries) {
    if (!FLOAT_ROOT_ATTRIBUTE.test(name) || typeof text !== "string" || text.length > 1_024) {
      throw new TypeError(`${channel}: root attribute ${name} is not allowed`);
    }
  }
  return { className: root.className, style: root.style, attributes: { ...attributes } };
}

/**
 * 提示条那一块:渲染层把右下角整块提示条(Sonner 的 section)序列化好交过来。`rect` 是它在主窗口里该占的那一块(CSS 像素):
 * 从最上面那条提示的左上角到窗口右下角 —— 提示条是贴着窗口右下角摆的,浮层视图的右下角也得是窗口的右下角。
 */
function parseToastsShow(value) {
  const channel = IPC.send.toastsShow;
  const payload = record(value, channel);
  onlyKeys(payload, ["html", "rect", "root"], channel);
  if (typeof payload.html !== "string" || payload.html.length > 262_144) {
    throw new TypeError(`${channel}: html must be a string under 256 KiB`);
  }
  return { html: payload.html, rect: floatRect(payload.rect, channel), root: floatRoot(payload.root, channel) };
}

/** 收起哪一条(不给 id 就是不管哪条都收)。 */
function parseFloatHide(value) {
  const channel = IPC.send.floatHide;
  const payload = record(value ?? {}, channel);
  onlyKeys(payload, ["id"], channel);
  if (payload.id === undefined) return { id: null };
  return { id: requiredString(payload, "id", channel) };
}



/**
 * 把一份下好的下载存进素材库:存到哪个服务器、哪个工作区、以谁的身份 —— 这些只有渲染层知道。
 * 令牌只用在这一次请求的头里(和 parseAuthToken 同一个长度上限)。
 */
function parseSaveDownload(value) {
  const channel = IPC.invoke.pageToolsSaveDownload;
  const payload = record(value, channel);
  onlyKeys(payload, ["id", "server", "token", "workspaceId", "projectId"], channel);
  const id = requiredString(payload, "id", channel);
  if (!/^[0-9a-f-]{36}$/.test(id)) throw new TypeError(`${channel}: id is invalid`);
  const server = requiredString(payload, "server", channel);
  if (server.length > 2000 || !/^https?:\/\/[^\s/]+/i.test(server)) {
    throw new TypeError(`${channel}: server must be an http(s) address`);
  }
  const { token } = parseAuthToken(payload, channel);
  const workspaceId = requiredString(payload, "workspaceId", channel);
  if (workspaceId.length > 64) throw new TypeError(`${channel}: workspaceId is too long`);
  const projectId = payload.projectId ?? null;
  if (projectId !== null && (typeof projectId !== "string" || !projectId || projectId.length > 64)) {
    throw new TypeError(`${channel}: projectId must be null or an id`);
  }
  return { id, server, token, workspaceId, projectId };
}

function parseTitleOverlay(value) {
  const channel = IPC.send.titleOverlay;
  const payload = record(value, channel);
  return {
    color: requiredString(payload, "color", channel),
    symbolColor: requiredString(payload, "symbolColor", channel),
  };
}

function parseSystemStatus(value) {
  const channel = IPC.send.systemStatus;
  const payload = record(value, channel);
  const runningJobs = payload.runningJobs;
  if (!Number.isInteger(runningJobs) || runningJobs < 0) {
    throw new TypeError(`${channel}: runningJobs must be a non-negative integer`);
  }
  const progress = payload.progress;
  if (progress !== undefined && progress !== null &&
      (typeof progress !== "number" || !Number.isFinite(progress) || progress < 0 || progress > 1)) {
    throw new TypeError(`${channel}: progress must be null or a number between 0 and 1`);
  }
  return { runningJobs, ...(progress === undefined ? {} : { progress }) };
}

function parseTaskNotice(value) {
  const channel = IPC.send.systemNotify;
  const payload = record(value, channel);
  return {
    title: requiredString(payload, "title", channel),
    body: typeof payload.body === "string" ? payload.body : "",
  };
}

/** 路径、标题这类可选的短字符串:不是字符串或空白是 ""(超长的拒掉,别让渲染层往原生对话框里塞一大段)。 */
function optionalText(payload, key, channel, limit) {
  const text = typeof payload[key] === "string" ? payload[key].trim() : "";
  if (text.length > limit) throw new TypeError(`${channel}: ${key} is too long`);
  return text;
}

/**
 * 「选择…」要一个什么样的对话框:`kind` 是 directory / file;`title`、`defaultPath`(从哪儿开始,格子里现在的值)可选;
 * `filters` 只给选文件用,扩展名只收字母数字(`exe`、`py`),最多几组。
 */
function parsePickPath(value) {
  const channel = IPC.invoke.pickPath;
  const payload = record(value, channel);
  if (payload.kind !== "directory" && payload.kind !== "file") {
    throw new TypeError(`${channel}: kind must be directory or file`);
  }
  const raw = payload.filters === undefined ? [] : payload.filters;
  if (!Array.isArray(raw) || raw.length > 8) throw new TypeError(`${channel}: filters must be a short array`);
  const filters = raw.map((one) => {
    const filter = record(one, channel);
    const extensions = Array.isArray(filter.extensions) ? filter.extensions : [];
    if (extensions.length === 0 || extensions.length > 16 || !extensions.every((ext) => typeof ext === "string" && /^(\*|[A-Za-z0-9]{1,16})$/.test(ext))) {
      throw new TypeError(`${channel}: filter extensions are invalid`);
    }
    return { name: requiredString(filter, "name", channel).slice(0, 80), extensions };
  });
  return {
    kind: payload.kind,
    title: optionalText(payload, "title", channel, 200),
    defaultPath: optionalText(payload, "defaultPath", channel, 4096),
    filters,
  };
}

/** 「保存到本地」一块字节的上限(8 MiB)。一次一块才走得通:素材原文件可以有 2 GiB(见 publish/downloadRules.MAX_DOWNLOAD_BYTES),
 *  而一条 IPC 消息装不下那么多字节(见 save-file.cjs);渲染层那边也按同一个数攒块(见 lib/download)。 */
const MAX_SAVE_CHUNK = 8 * 1024 * 1024;

/**
 * 「保存到本地」的第一步:一个建议文件名。**只有它** —— 目标路径由保存框产生,渲染层送不进任何一个
 * 路径字符串(见 save-file.cjs)。名字里的路径分隔符和系统不收的字符在这里不收:`..`、`a/b` 这种
 * 交上去只会让保存框的默认目录跑偏。
 */
function parseSaveFileBegin(value) {
  const channel = IPC.invoke.saveFileBegin;
  const payload = record(value, channel);
  onlyKeys(payload, ["name"], channel);
  const name = requiredString(payload, "name", channel);
  if (name.length > 300) throw new TypeError(`${channel}: name is too long`);
  if (/[\\/]/.test(name)) throw new TypeError(`${channel}: name must not be a path`);
  if (/[\x00-\x1f]/.test(name)) throw new TypeError(`${channel}: name must not contain control characters`);
  return { name };
}

/** 一次保存会话的 id(主进程发的手柄,见 save-file.cjs)。 */
function saveFileId(payload, channel) {
  const id = requiredString(payload, "id", channel);
  if (!/^[0-9a-f-]{36}$/.test(id)) throw new TypeError(`${channel}: id is invalid`);
  return id;
}

/**
 * 「保存到本地」的第二步:一块字节。**收 Uint8Array(和 Buffer)、也收 ArrayBuffer** —— 经 contextBridge +
 * IPC 过来的是结构化克隆的字节,认这两种形状就够;别的形状不收,免得主进程去猜一个对象是什么。
 */
function parseSaveFileChunk(value) {
  const channel = IPC.invoke.saveFileWrite;
  const payload = record(value, channel);
  onlyKeys(payload, ["id", "bytes"], channel);
  const id = saveFileId(payload, channel);
  const raw = payload.bytes;
  const bytes = raw instanceof Uint8Array ? raw : raw instanceof ArrayBuffer ? new Uint8Array(raw) : null;
  if (!bytes) throw new TypeError(`${channel}: bytes must be a Uint8Array or an ArrayBuffer`);
  if (bytes.byteLength > MAX_SAVE_CHUNK) throw new TypeError(`${channel}: a chunk is at most ${MAX_SAVE_CHUNK} bytes`);
  return { id, bytes };
}

/** 「保存到本地」的收尾 / 撤销:只带那个手柄。 */
function parseSaveFileId(value, channel) {
  const payload = record(value, channel);
  onlyKeys(payload, ["id"], channel);
  return { id: saveFileId(payload, channel) };
}

/**
 * 渲染层的界面语言(`<html lang>` 上那个值,如 `en-US`)。主进程只认 zh / en,归一在
 * i18n.cjs 里做;这里只保证它是一个像样的语言标签,不是任意长的字符串。
 */
function parseLocale(value) {
  const channel = IPC.send.locale;
  const payload = record(value, channel);
  const locale = requiredString(payload, "locale", channel);
  if (!/^[A-Za-z]{2,8}([-_][A-Za-z0-9]{1,8})*$/.test(locale)) {
    throw new TypeError(`${channel}: locale must be a language tag`);
  }
  return { locale };
}

module.exports = {
  IPC,
  parseAuthToken,
  parseRestoreStage,
  parseBrowserLogin,
  parseBrowserProfile,
  parseCaptureMode,
  parseComputerClick,
  parseHostLayer,
  parseComputerScreenshot,
  parseComputerScroll,
  parseComputerType,
  parseComfyNavigation,
  parseComfyWorkbenchCall,
  parseComfyWorkbenchOpen,
  parseImageUrls,
  parseLocale,
  parseNewPage,
  parsePageId,
  parsePageOrder,
  parseFloatShow,
  parseFloatHide,
  parseToastsShow,
  parsePanelId,
  parsePanelMuted,
  parsePanelLayout,
  parsePickPath,
  parsePublishTarget,
  parseReadMode,
  parseRegionSelection,
  parseSaveDownload,
  parseSaveFileBegin,
  parseSaveFileChunk,
  parseSaveFileId,
  parseSystemStatus,
  parseTaskNotice,
  parseTitleOverlay,
  parseToolsInset,
  parseUrlRequest,
};
