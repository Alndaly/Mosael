/**
 * ComfyUI 工作台的桥(ADR 0038 §3):画布是那台 ComfyUI 自己的(内嵌视图),Mosael 的面板画在旁边。两边怎么通话:
 *
 * - **主进程往这个视图注入一段写死的脚本**(`workbenchInstallScript`),定义一个带版本号的 `window.__mosaelWorkbench`:探测能力、
 *   读当前选中的节点(类型、widget 名字和值)、把一个值填进某个 widget(先查它在下拉里)、`refreshComboInNodes`、导出当前图
 *   (界面格式 + `graphToPrompt` 的 API 格式 + 前端的 `clientId`)、有没有没存的改动、执行保存命令、把应用表单的标记写到画布的
 *   节点上;订阅前端 `api` 的 `executing` / `executed` / `progress` / `execution_error` 等事件,存进一个有上限的队列。
 * - **只拉不推**:主进程大约每 300ms 取一次(`poll`:队列、选中、脏标记、能力),页面里没有任何能调到 Mosael 的口子。
 * - 渲染层要做的事(填值、导出、保存……)经契约里的解析器逐项校验,再由主进程把**数据**以 JSON 编码嵌进写死的调用脚本
 *   (`workbenchCallScript`)—— 渲染层送不进代码;每段脚本先核对来源,视图停在别的站点就什么都不做。
 * - 页面和自定义节点的脚本在同一个世界里,所以从页面拿到的一律当**提示**:形状不对的丢掉、字符串截断、数组有上限
 *   (`parseWorkbenchPoll` / `parseWorkbenchExport`);定论(这次跑出了什么、哪张来自哪个节点)以插件读的历史为准。
 *
 * 用到的前端名字(1.53.10 里查过):`window.app`、`app.canvas.selected_nodes`、`node.widgets[].value / options.values / setValue`、
 * `app.refreshComboInNodes`、`app.graphToPrompt`、`app.rootGraph`、`app.api`(EventTarget,`clientId`)、
 * `app.extensionManager.workflow.activeWorkflow`(`path` / `isModified` / `isTemporary` / `changeTracker`)、
 * `app.extensionManager.command`(`Comfy.SaveWorkflow`)。每个调用先探测,缺了只关掉那一样(能力表里是 false)。
 */

/** 桥的版本:页面里已经有同一版的就不再注入;形状变了加一。 */
export const WORKBENCH_VERSION = 1;

/** 队列里最多留几条事件(没人取的时候丢最老的)。 */
export const MAX_EVENTS = 200;

/** 保存用的前端命令(和 ComfyUI 菜单「工作流 → 保存」、Ctrl+S 同一条)。 */
export const SAVE_COMMAND = "Comfy.SaveWorkflow";

/** 渲染层能让桥做的事(轮询是主进程自己的,不在这里)。 */
export type WorkbenchCall =
  | { op: "setWidget"; node: string; widget: string; value: string | number | boolean }
  | { op: "refreshCombos" }
  | { op: "export" }
  | { op: "save" }
  | { op: "setMarks"; marks: { nodes: Record<string, Record<string, unknown>>; extra: Record<string, unknown> | null } };

/** 页面里定义 `window.__mosaelWorkbench` 的脚本。回 installed / present(同一版已经在)/ elsewhere / notReady。 */
export function workbenchInstallScript(origin: string): string {
  return `(() => {
  if (location.origin !== ${JSON.stringify(origin)}) return "elsewhere";
  const VERSION = ${WORKBENCH_VERSION};
  const existing = window.__mosaelWorkbench;
  if (existing && existing.version === VERSION) return "present";
  // 别的版本(或者页面自己占了这个名字):定义不上(那一格不可改),这一页就当桥不在
  if ("__mosaelWorkbench" in window) return "conflict";
  const app = window.app;
  if (!app || !app.extensionManager) return "notReady";
  const text = (value, limit) => (typeof value === "string" ? value.slice(0, limit)
    : typeof value === "number" && Number.isFinite(value) ? String(value) : "");
  const queue = [];
  const push = (event) => {
    queue.push(event);
    if (queue.length > ${MAX_EVENTS}) queue.splice(0, queue.length - ${MAX_EVENTS});
  };
  const api = app.api;
  const nodeOf = (detail) => (detail && typeof detail === "object" ? text(detail.display_node || detail.node, 40) : text(detail, 40));
  const listen = (type, pick) => {
    if (!api || typeof api.addEventListener !== "function") return false;
    api.addEventListener(type, (event) => {
      try {
        const picked = pick(event && event.detail);
        if (picked) push(Object.assign({ type, at: Date.now() }, picked));
      } catch (error) {
        // 一条事件的形状不对:丢掉,不影响下一条
      }
    });
    return true;
  };
  const listening = [
    listen("execution_start", (d) => ({ promptId: text(d && d.prompt_id, 100) })),
    listen("executing", (d) => ({ promptId: text(d && d.prompt_id, 100), node: nodeOf(d) })),
    listen("progress", (d) => d && ({ promptId: text(d.prompt_id, 100), node: text(d.node, 40),
      value: Number(d.value) || 0, max: Number(d.max) || 0 })),
    listen("executed", (d) => d && ({ promptId: text(d.prompt_id, 100), node: nodeOf(d) })),
    listen("execution_cached", (d) => d && ({ promptId: text(d.prompt_id, 100) })),
    listen("execution_success", (d) => ({ promptId: text(d && d.prompt_id, 100) })),
    listen("execution_error", (d) => d && ({ promptId: text(d.prompt_id, 100), node: text(d.node_id, 40),
      nodeType: text(d.node_type, 200), message: text(d.exception_message, 1000) })),
    listen("execution_interrupted", (d) => ({ promptId: text(d && d.prompt_id, 100) })),
  ].every(Boolean);
  const workflows = () => app.extensionManager.workflow;
  const commands = () => app.extensionManager.command;
  const hasCommand = (id) => {
    const store = commands();
    return Boolean(store && typeof store.execute === "function" && Array.isArray(store.commands) &&
      store.commands.some((one) => one && one.id === id));
  };
  const canvasGraph = () => (app.canvas && app.canvas.graph) || app.graph;
  const rootGraph = () => app.rootGraph || app.graph;
  const nodesOf = (graph) => (graph ? (Array.isArray(graph.nodes) ? graph.nodes : Array.isArray(graph._nodes) ? graph._nodes : []) : []);
  const findNode = (graph, id) => nodesOf(graph).find((node) => node && String(node.id) === String(id)) || null;
  const valuesOf = (widget) => {
    const values = widget && widget.options ? widget.options.values : undefined;
    try {
      return typeof values === "function" ? values(widget) : values;
    } catch (error) {
      return undefined;
    }
  };
  const plainValue = (value) => (typeof value === "string" ? value.slice(0, 4000)
    : (typeof value === "number" && Number.isFinite(value)) || typeof value === "boolean" ? value : null);
  const describe = (node) => ({
    id: text(String(node.id), 40),
    type: text(node.comfyClass || node.type, 200),
    title: text(node.title, 200),
    widgets: (Array.isArray(node.widgets) ? node.widgets : []).slice(0, 64).map((widget) => ({
      name: text(widget && widget.name, 200),
      type: text(widget && widget.type, 40),
      value: plainValue(widget && widget.value),
      combo: Array.isArray(valuesOf(widget)),
    })),
  });
  const selected = () => {
    const canvas = app.canvas;
    const map = canvas && canvas.selected_nodes;
    return map && typeof map === "object" ? Object.values(map).filter(Boolean) : [];
  };
  const tracker = () => {
    const store = workflows();
    const active = store && store.activeWorkflow;
    return active && active.changeTracker;
  };
  const touched = (graph) => {
    try {
      if (graph && typeof graph.setDirtyCanvas === "function") graph.setDirtyCanvas(true, true);
      const changes = tracker();
      if (changes && typeof changes.captureCanvasState === "function") changes.captureCanvasState();
      else if (changes && typeof changes.checkState === "function") changes.checkState();
    } catch (error) {
      // 画布照样改了;脏标记由前端下次自己核对
    }
  };
  const capabilities = () => {
    const store = workflows();
    return {
      selection: Boolean(app.canvas && app.canvas.selected_nodes),
      setWidget: Boolean(app.canvas),
      refreshCombos: typeof app.refreshComboInNodes === "function",
      export: typeof app.graphToPrompt === "function",
      dirty: Boolean(store && "activeWorkflow" in store),
      save: hasCommand(${JSON.stringify(SAVE_COMMAND)}),
      events: listening,
      marks: Boolean(rootGraph()),
    };
  };
  const norm = (value) => String(value).replace(/\\\\/g, "/");
  const bridge = {
    version: VERSION,
    poll() {
      const store = workflows();
      const active = store && store.activeWorkflow;
      const nodes = selected();
      return {
        version: VERSION,
        capabilities: capabilities(),
        workflow: active ? { path: text(active.path, 600), name: text(active.filename, 300),
          temporary: Boolean(active.isTemporary), modified: Boolean(active.isModified) } : null,
        selection: { count: nodes.length, node: nodes.length === 1 ? describe(nodes[0]) : null },
        clientId: text(api && (api.clientId || api.initialClientId), 100),
        events: queue.splice(0, queue.length),
      };
    },
    setWidget(id, name, value) {
      const graph = canvasGraph();
      const node = findNode(graph, id);
      if (!node) return { error: "noNode" };
      const widget = (Array.isArray(node.widgets) ? node.widgets : []).find((one) => one && one.name === name);
      if (!widget) return { error: "noWidget" };
      let next = value;
      const values = valuesOf(widget);
      if (Array.isArray(values)) {
        const found = values.find((one) => one === value) ?? values.find((one) => norm(one) === norm(value));
        if (found === undefined) return { error: "notInList" };
        next = found;
      }
      if (typeof widget.setValue === "function") {
        widget.setValue(next, { e: undefined, node, canvas: app.canvas });
      } else {
        const before = widget.value;
        widget.value = next;
        if (typeof widget.callback === "function") widget.callback(next, app.canvas, node);
        if (typeof node.onWidgetChanged === "function") node.onWidgetChanged(name, next, before, widget);
      }
      touched(graph);
      return { ok: true, value: plainValue(widget.value) };
    },
    async refreshCombos() {
      await app.refreshComboInNodes();
      return { ok: true };
    },
    async exportGraph() {
      const result = await app.graphToPrompt();
      return JSON.parse(JSON.stringify({ workflow: result && result.workflow, prompt: result && result.output,
        clientId: text(api && (api.clientId || api.initialClientId), 100) }));
    },
    save() {
      // 不等它:存一张没起过名的,前端会在画布上弹框问名字。存没存成,下一次轮询的脏标记说
      Promise.resolve(commands().execute(${JSON.stringify(SAVE_COMMAND)})).catch(() => undefined);
      return { ok: true };
    },
    setMarks(marks) {
      const graph = rootGraph();
      const missing = Object.keys(marks.nodes).filter((id) => !findNode(graph, id));
      if (missing.length) return { error: "noNode", nodes: missing.slice(0, 20) };
      for (const node of nodesOf(graph)) {
        if (!node) continue;
        const own = marks.nodes[String(node.id)];
        if (own) {
          if (!node.properties || typeof node.properties !== "object") node.properties = {};
          node.properties.mosael = own;
        } else if (node.properties && typeof node.properties === "object" && "mosael" in node.properties) {
          delete node.properties.mosael;
        }
      }
      if (marks.extra) {
        if (!graph.extra || typeof graph.extra !== "object") graph.extra = {};
        graph.extra.mosael = marks.extra;
      } else if (graph.extra && typeof graph.extra === "object") {
        delete graph.extra.mosael;
      }
      touched(graph);
      return { ok: true };
    },
  };
  Object.defineProperty(window, "__mosaelWorkbench", { value: Object.freeze(bridge), configurable: false, writable: false });
  return "installed";
})()`;
}

/** 主进程自己的轮询(不经渲染层)。 */
export function workbenchPollScript(origin: string): string {
  return callShell(origin, "return bridge.poll();");
}

/** 渲染层要做的一件事:数据经 JSON 编码嵌进去,只调桥上固定的那几个方法。 */
export function workbenchCallScript(origin: string, call: WorkbenchCall): string {
  const data = JSON.stringify(call);
  const body = {
    setWidget: "return bridge.setWidget(call.node, call.widget, call.value);",
    refreshCombos: "return await bridge.refreshCombos();",
    export: "return await bridge.exportGraph();",
    save: "return bridge.save();",
    setMarks: "return bridge.setMarks(call.marks);",
  }[call.op];
  return callShell(origin, `const call = ${data};\n    ${body}`);
}

function callShell(origin: string, body: string): string {
  return `(async () => {
  if (location.origin !== ${JSON.stringify(origin)}) return { error: "elsewhere" };
  const bridge = window.__mosaelWorkbench;
  if (!bridge || bridge.version !== ${WORKBENCH_VERSION}) return { error: "missing" };
  try {
    ${body}
  } catch (error) {
    return { error: "failed", message: String((error && error.message) || error).slice(0, 500) };
  }
})()`;
}

// ---- 页面交回来的,一律当提示:规整 ---------------------------------------------------------

export interface WorkbenchCapabilities {
  selection: boolean;
  setWidget: boolean;
  refreshCombos: boolean;
  export: boolean;
  dirty: boolean;
  save: boolean;
  events: boolean;
  marks: boolean;
}

export interface WorkbenchWidget {
  name: string;
  type: string;
  value: string | number | boolean | null;
  combo: boolean;
}

export interface WorkbenchNode {
  id: string;
  type: string;
  title: string;
  widgets: WorkbenchWidget[];
}

export interface WorkbenchEvent {
  type: string;
  at: number;
  promptId: string;
  node: string;
  value?: number;
  max?: number;
  nodeType?: string;
  message?: string;
}

export interface WorkbenchState {
  capabilities: WorkbenchCapabilities;
  /** 画布上开着的那一张:`path` 是 `workflows/` 下的相对路径(没存过的是空串) */
  workflow: { path: string; name: string; temporary: boolean; modified: boolean } | null;
  selection: { count: number; node: WorkbenchNode | null };
  clientId: string;
  events: WorkbenchEvent[];
}

const CAPABILITIES: (keyof WorkbenchCapabilities)[] = ["selection", "setWidget", "refreshCombos", "export", "dirty", "save",
  "events", "marks"];
const EVENT_TYPES = new Set(["execution_start", "executing", "progress", "executed", "execution_cached", "execution_success",
  "execution_error", "execution_interrupted"]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown, limit: number) => (typeof value === "string" ? value.slice(0, limit) : "");
const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : 0);

/**
 * 一次轮询的回答。形状不对回 null(这一拍当没看到)。工作流的路径去掉前端的 `workflows/` 前缀;不在 `workflows/` 下的(前端
 * 自己的临时路径)当没存过。
 */
export function parseWorkbenchPoll(raw: unknown): WorkbenchState | null {
  if (!isRecord(raw) || raw.version !== WORKBENCH_VERSION || !isRecord(raw.capabilities)) return null;
  const reported = raw.capabilities;
  const capabilities = Object.fromEntries(
    CAPABILITIES.map((key) => [key, reported[key] === true]),
  ) as unknown as WorkbenchCapabilities;
  let workflow: WorkbenchState["workflow"] = null;
  if (isRecord(raw.workflow)) {
    const path = str(raw.workflow.path, 600);
    const saved = path.startsWith("workflows/") && path.toLowerCase().endsWith(".json") && raw.workflow.temporary !== true;
    workflow = {
      path: saved ? path.slice("workflows/".length) : "",
      name: str(raw.workflow.name, 300),
      temporary: !saved,
      modified: raw.workflow.modified === true,
    };
  }
  const selection = isRecord(raw.selection) ? raw.selection : {};
  const node = isRecord(selection.node) ? parseNode(selection.node) : null;
  const events = (Array.isArray(raw.events) ? raw.events : []).slice(-MAX_EVENTS).flatMap((one): WorkbenchEvent[] => {
    if (!isRecord(one) || !EVENT_TYPES.has(str(one.type, 40))) return [];
    const event: WorkbenchEvent = { type: str(one.type, 40), at: num(one.at), promptId: str(one.promptId, 100), node: str(one.node, 40) };
    if (event.type === "progress") Object.assign(event, { value: num(one.value), max: num(one.max) });
    if (event.type === "execution_error") Object.assign(event, { nodeType: str(one.nodeType, 200), message: str(one.message, 1000) });
    return [event];
  });
  return {
    capabilities,
    workflow,
    selection: { count: Math.max(0, Math.min(10_000, Math.floor(num(selection.count)))), node },
    clientId: /^[A-Za-z0-9_-]{1,100}$/.test(str(raw.clientId, 100)) ? str(raw.clientId, 100) : "",
    events,
  };
}

function parseNode(raw: Record<string, unknown>): WorkbenchNode | null {
  const id = str(raw.id, 40);
  if (!/^-?\d{1,10}$/.test(id)) return null;
  const widgets = (Array.isArray(raw.widgets) ? raw.widgets : []).slice(0, 64).flatMap((one): WorkbenchWidget[] => {
    if (!isRecord(one) || !str(one.name, 200)) return [];
    const value = one.value;
    return [{
      name: str(one.name, 200),
      type: str(one.type, 40),
      value: typeof value === "string" ? value.slice(0, 4000)
        : (typeof value === "number" && Number.isFinite(value)) || typeof value === "boolean" ? value : null,
      combo: one.combo === true,
    }];
  });
  return { id, type: str(raw.type, 200), title: str(raw.title, 200), widgets };
}

/** 导出的当前图:界面格式要有 `nodes`、API 图每个节点要有 `class_type`,整张不超过上限。不对回 null。 */
export const MAX_EXPORT_CHARS = 40 * 1024 * 1024;

export interface WorkbenchExport {
  workflow: Record<string, unknown>;
  prompt: Record<string, unknown>;
  clientId: string;
}

export function parseWorkbenchExport(raw: unknown): WorkbenchExport | null {
  if (!isRecord(raw) || !isRecord(raw.workflow) || !Array.isArray(raw.workflow.nodes) || !isRecord(raw.prompt)) return null;
  for (const node of Object.values(raw.prompt)) {
    if (!isRecord(node) || typeof node.class_type !== "string" || !isRecord(node.inputs)) return null;
  }
  if (JSON.stringify(raw.workflow).length + JSON.stringify(raw.prompt).length > MAX_EXPORT_CHARS) return null;
  const clientId = str(raw.clientId, 100);
  return { workflow: raw.workflow, prompt: raw.prompt, clientId: /^[A-Za-z0-9_-]{1,100}$/.test(clientId) ? clientId : "" };
}

/** 别的调用的回答:成了 / 一个原因码(noNode、noWidget、notInList、missing、elsewhere、failed)。 */
export type WorkbenchCallResult =
  | { ok: true; value?: string | number | boolean | null; export?: WorkbenchExport }
  | { ok: false; error: string; message?: string; nodes?: string[] };

const ERRORS = new Set(["noNode", "noWidget", "notInList", "missing", "elsewhere", "failed", "notReady", "closed"]);

export function parseWorkbenchResult(call: WorkbenchCall, raw: unknown): WorkbenchCallResult {
  if (isRecord(raw) && typeof raw.error === "string") {
    const error = ERRORS.has(raw.error) ? raw.error : "failed";
    const nodes = Array.isArray(raw.nodes) ? raw.nodes.map((one) => str(one, 40)).filter(Boolean).slice(0, 20) : undefined;
    return { ok: false, error, ...(raw.message ? { message: str(raw.message, 500) } : {}), ...(nodes ? { nodes } : {}) };
  }
  if (call.op === "export") {
    const exported = parseWorkbenchExport(raw);
    return exported ? { ok: true, export: exported } : { ok: false, error: "failed", message: "malformed export" };
  }
  if (!isRecord(raw) || raw.ok !== true) return { ok: false, error: "failed" };
  if (call.op === "setWidget") {
    const value = raw.value;
    return { ok: true, value: typeof value === "string" ? value.slice(0, 4000)
      : (typeof value === "number" && Number.isFinite(value)) || typeof value === "boolean" ? value : null };
  }
  return { ok: true };
}
