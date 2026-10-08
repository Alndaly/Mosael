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
    // 前台会话的页面列表(左侧那一列):都作用在前台那个会话上,渲染层不点名要哪个会话。
    publishSwitchPage: "publish:switchPage",
    publishClosePage: "publish:closePage",
    publishReorderPages: "publish:reorderPages",
    publishNewPage: "publish:newPage",
    publishPagesInset: "publish:pagesInset",
    // 页面列表展开 / 收起 / 临时展开:拍下前台网页的画面、把原生视图挪开 / 放回(列表在那张画面上变形)。
    publishSnapshotPage: "publish:snapshotPage",
    publishCoverPage: "publish:coverPage",
    // Mosael 的整窗浮层(看大图)亮着:前台网页挪到窗口外,浮层收起再放回(见 accountViews 的 ForegroundHideReason)。
    publishOverlay: "publish:overlay",
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
  }),
  send: Object.freeze({
    titleOverlay: "mosael:title-overlay",
    systemStatus: "system:status",
    systemNotify: "system:notify",
    locale: "mosael:locale",
    // 内嵌浏览器外壳里的悬停说明交给浮层视图画在网页上面 / 收起(见 publish/floatLayer.ts)。
    floatShow: "float:show",
    floatHide: "float:hide",
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

//: 画布上的节点号(当前显示的那一层图里的,可能是子图里的)、根图上的节点号(应用表单的标记只认根图)
const CANVAS_NODE = /^-?\d{1,10}$/;
const ROOT_NODE = /^\d{1,9}$/;
//: 从根图往里走的节点路径(`12:5`:根图 12 号节点那个子图里面的 5 号;ADR 0042 智能体指节点的写法),最多 16 层
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
    } else {
      out.node = editNode(op.node, "node", channel);
      if (kind === "set_widget") {
        out.widget = editName(op.widget, "widget", channel);
        out.value = editValue(op.value, "value", channel);
      } else if (kind === "set_title") {
        out.title = editName(op.title, "title", channel);
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
 * - setMarks:根图节点号 → 一个对象(那个节点上的 `properties.mosael`),和图上的 `extra.mosael`(对象或 null);
 * - locate:节点号加子图的 id(那一层里的编号),或者不给子图、节点写成从根图往里走的路径(`12:5`);
 * - readGraph:不带别的(整张图交给智能体读,ADR 0042;后端排的工作台动作也经这里查过才进桥,见 browserWorker);
 * - runControls:`phase` 只能是 before / after(「运行」前后照前端的「生成后怎样」换种子);
 * - applyOps:智能体改图的一批(见 parseEditOps);openWorkflow:在新标签页开一张(见 parseOpenWorkflow)。两样都是后端排的
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
    onlyKeys(call, ["op", "ops"], channel);
    const ops = parseEditOps(call.ops, channel);
    if (!ops.length) throw new TypeError(`${channel}: ops must not be empty`);
    return { partition, call: { op, ops } };
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
    onlyKeys(call, ["op", "marks"], channel);
    const marks = record(call.marks, channel);
    onlyKeys(marks, ["nodes", "extra"], channel);
    const nodes = record(marks.nodes, channel);
    const entries = Object.entries(nodes);
    if (entries.length > 1000) throw new TypeError(`${channel}: too many marked nodes`);
    for (const [id, own] of entries) {
      if (!ROOT_NODE.test(id)) throw new TypeError(`${channel}: marks.nodes keys must be top-level node ids`);
      record(own, channel);
    }
    const extra = marks.extra === null || marks.extra === undefined ? null : record(marks.extra, channel);
    if (JSON.stringify({ nodes, extra }).length > MAX_MARKS_CHARS) throw new TypeError(`${channel}: marks are too big`);
    return { partition, call: { op, marks: JSON.parse(JSON.stringify({ nodes, extra })) } };
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

/** 页面列表开合:前台视图左侧让出的像素宽。 */
function parsePagesInset(value) {
  const channel = IPC.invoke.publishPagesInset;
  const payload = record(value, channel);
  onlyKeys(payload, ["left"], channel);
  const left = payload.left;
  if (typeof left !== "number" || !Number.isFinite(left) || left < 0 || left > 4000) {
    throw new TypeError(`${channel}: left must be a number between 0 and 4000`);
  }
  return { left };
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
  const rect = record(payload.rect, channel);
  const { x, y, width, height } = rect;
  if (!finiteIn(x, -10_000, 10_000) || !finiteIn(y, -10_000, 10_000) || !finiteIn(width, 0, 4_000) || !finiteIn(height, 0, 4_000)) {
    throw new TypeError(`${channel}: rect must be a bounded rectangle`);
  }
  const root = record(payload.root, channel);
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
  return { id, html: payload.html, rect: { x, y, width, height }, root: { className: root.className, style: root.style, attributes: { ...attributes } } };
}

/** 收起哪一条(不给 id 就是不管哪条都收)。 */
function parseFloatHide(value) {
  const channel = IPC.send.floatHide;
  const payload = record(value ?? {}, channel);
  onlyKeys(payload, ["id"], channel);
  if (payload.id === undefined) return { id: null };
  return { id: requiredString(payload, "id", channel) };
}

/** 把前台网页挪开 / 放回(页面列表在它的画面上变形)。 */
function parseCoverPage(value) {
  const channel = IPC.invoke.publishCoverPage;
  const payload = record(value, channel);
  onlyKeys(payload, ["covered"], channel);
  if (typeof payload.covered !== "boolean") throw new TypeError(`${channel}: covered must be a boolean`);
  return { covered: payload.covered };
}

/** Mosael 的整窗浮层亮着 / 收起:前台网页挪开 / 放回。 */
function parseOverlay(value) {
  const channel = IPC.invoke.publishOverlay;
  const payload = record(value, channel);
  onlyKeys(payload, ["up"], channel);
  if (typeof payload.up !== "boolean") throw new TypeError(`${channel}: up must be a boolean`);
  return { up: payload.up };
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
  parseComfyNavigation,
  parseComfyWorkbenchCall,
  parseComfyWorkbenchOpen,
  parseImageUrls,
  parseLocale,
  parseNewPage,
  parsePageId,
  parsePageOrder,
  parsePagesInset,
  parseCoverPage,
  parseOverlay,
  parseFloatShow,
  parseFloatHide,
  parsePanelId,
  parsePanelMuted,
  parsePanelLayout,
  parsePickPath,
  parsePublishTarget,
  parseReadMode,
  parseRegionSelection,
  parseSaveDownload,
  parseSystemStatus,
  parseTaskNotice,
  parseTitleOverlay,
  parseToolsInset,
  parseUrlRequest,
};
