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
 * 智能体(ADR 0042)经同一座桥读画布(`readGraph`)、在画布上指出一个节点(`locate`)、改图(`applyOps`)、在新标签页开一张
 * (`openWorkflow`):调用不是渲染层发的,是后端排、主进程的浏览器执行器领走的工作台动作(见 browserWorker),照同一套解析器
 * (ipc-contract 的 parseComfyWorkbenchCall)查过才进来。
 *
 * **改图的三道守着**(ADR 0042 Consequences):插件先对着 `/object_info` 查过、用户在确认卡上点过「应用」(后端那一侧);到了
 * 页面里**先把每一条都查一遍**(节点在不在、口叫不叫这个名字、类型配不配、下拉里有没有这个值),有一条不对就一样不改;都对才改,
 * 整批夹在前端改动跟踪的 `beforeChange` / `afterChange` 之间,只记**一步**撤销(一次 Ctrl+Z 退回去)。万一改到一半前端还是不让
 * (扩展拒了一根线),把记下的那一步退掉、也不留在「重做」里。新标签页是前端用名字开的临时工作流,桥**从不**存盘。
 *
 * 用到的前端名字(1.53.10 里查过):`window.app`、`app.canvas.selected_nodes`、`node.widgets[].value / options.values / setValue`、
 * `app.refreshComboInNodes`、`app.graphToPrompt`、`app.rootGraph`、`app.api`(EventTarget,`clientId`)、
 * `app.extensionManager.workflow.activeWorkflow`(`path` / `isModified` / `isTemporary` / `changeTracker.activeState`)、
 * `app.extensionManager.command`(`Comfy.SaveWorkflow`)、定位节点用的 `app.canvas.selectItems / selectNode`、
 * `centerOnNode / animateToBounds`、子图的 `rootGraph.subgraphs` 和 `canvas.openSubgraph / setGraph`、那台机器的版本用的
 * `api.getSystemStats`(注入时问一次)、「运行」前后的
 * `widget.beforeQueued / afterQueued` 和 `window.comfyAPI.promotedWidgetControl.applyPromotedWidgetControl`;改图用的
 * `LiteGraph.createNode / isValidConnection`、图的 `add / remove / getLink / removeLink`、节点的 `connect / disconnectInput /
 * getSlotFromWidget / changeMode / setPos`、子图的 `addInput / addOutput / removeInput / removeOutput` 和边界口的 `connect`、
 * `convertToSubgraph / unpackSubgraph`、改动跟踪的 `beforeChange / afterChange / undo`,开新标签用的 `loadGraphData(图, …, 名字)`
 * 和工作流仓库的 `getWorkflowByPath`。每个调用先探测,缺了只关掉那一样(能力表里是 false)。
 *
 * **画布上开着的是哪一张**:用户可能在 ComfyUI 自己的标签栏 / 侧栏里换一张。轮询里的 `workflow.key` 是那一张在前端工作流仓库里的
 * 路径(没存过的也有,形如 `workflows/Unsaved Workflow (2).json`),面板按它认「换了一张」;`revision` 是这一张的图**改过几回**
 * —— 前端自己的改动跟踪(`changeTracker`)每认一次改动就换一份 `activeState`,桥看到换了就加一(选中节点不算改动)。
 */

/**
 * 桥的版本:页面里已经有同一版的就不再注入;形状变了加一。2:轮询报开着的是哪一张、改过几回;能定位节点。
 * 3:「运行」前后照前端自己的「生成后怎样」换种子(runControls)。4:读整张图给智能体(readGraph);定位认从根图往里走的
 * 节点路径(`12:5`),一层层打开子图;轮询报那台 ComfyUI 和它前端的版本(ADR 0042)。5:智能体改图(applyOps:一批改动
 * 先全查一遍再改、只占一步撤销,根图和子图的定义、边界口、提升控件、打包 / 拆开)、在新标签页开一张整图(openWorkflow,
 * 不存盘)(ADR 0042 第二步)。
 */
export const WORKBENCH_VERSION = 5;

/** 一批改动最多几条(和 ipc-contract、插件的 canvas_edit 同一个数)。 */
export const MAX_EDIT_OPS = 200;

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
  | { op: "setMarks"; marks: { nodes: Record<string, Record<string, unknown>>; extra: Record<string, unknown> | null } }
  /**
   * 在画布上找到这个节点:选中、移到画面中间;在子图里的先进那张子图。`subgraph` 是子图定义的 id(`node` 是那一层里的编号);
   * 或者 `subgraph` 为 null、`node` 写成从根图往里走的路径(`12:5`:根图 12 号节点那个子图里面的 5 号),一层层打开。
   */
  | { op: "locate"; node: string; subgraph: string | null }
  /**
   * 智能体读画布(ADR 0042):当前这张的界面格式整图(`graphToPrompt().workflow`,子图的定义在 `definitions.subgraphs` 里)、
   * 选中的节点(画布这一层里的编号)、改没改、画布停在哪一层(子图的 id,根图是 null)、开着的是哪一张。
   */
  | { op: "readGraph" }
  /**
   * 「运行」画布上这张的前后各一次(`before` 导出之前、`after` 任务建好之后):和在 ComfyUI 里点「运行」一样,让每个 widget
   * 走前端自己的 beforeQueued / afterQueued —— 「生成后怎样」是 randomize / increment 的种子在这里换,不然连点两次运行是同一张图。
   */
  | { op: "runControls"; phase: "before" | "after" }
  /**
   * 智能体改当前这张(ADR 0042 第二步):插件规整过的一批(见插件的 canvas_edit)。**先把每一条都查一遍**(节点在不在、口叫不叫
   * 这个名字、类型配不配、下拉里有没有这个值),有一条不对就一样不改、把原因交回去;都对才改,整批只记一步撤销。
   */
  | { op: "applyOps"; ops: WorkbenchEditOp[] }
  /**
   * 在新标签页开一张(ADR 0042 第二步):给 `graph` 就是一张没存过的新工作流(名字是 `name`,和开着的不重名;`ops` 再在上面
   * 改一批),给 `path` 就是打开存着的那一张。都不存盘 —— 存不存是用户的事。
   */
  | { op: "openWorkflow"; graph: Record<string, unknown> | null; name: string; path: string | null; ops: WorkbenchEditOp[] };

/** 改动里指一个节点:那一层里的编号,或者这一批里新加的临时名字(`$a`)。 */
type EditNode = string;
/** 连线的一头:节点(或子图边界的 `@in` / `@out`)加口的名字。 */
interface EditEnd {
  node: EditNode | "@in" | "@out";
  name: string;
}
/** 一条规整过的改动。`layer` 是哪一层:根图是 null,子图是它定义的 id —— 改的是定义,用它的地方一起变。 */
export type WorkbenchEditOp = { layer: string | null } & (
  | { op: "add_node"; id: string; type: string; widgets: Record<string, string | number | boolean>; title?: string; near?: EditNode }
  | { op: "remove_node"; node: EditNode }
  | { op: "connect"; from: EditEnd; to: EditEnd }
  | { op: "disconnect"; to: EditEnd }
  | { op: "set_widget"; node: EditNode; widget: string; value: string | number | boolean }
  | { op: "set_title"; node: EditNode; title: string }
  | { op: "mode"; node: EditNode; mode: 0 | 2 | 4 }
  | { op: "add_io"; side: "input" | "output"; name: string; type: string }
  | { op: "remove_io"; side: "input" | "output"; name: string }
  | { op: "promote"; node: EditNode; widget: string; name: string }
  | { op: "unpromote"; node: EditNode; widget: string }
  | { op: "to_subgraph"; nodes: EditNode[]; name?: string }
  | { op: "unpack"; node: EditNode }
);

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
  //: 那台 ComfyUI 和它前端的版本(助手的页面上下文里写着):注入时问一次 /system_stats,问不到就是空的
  const server = { comfyui: "", frontend: "" };
  if (api && typeof api.getSystemStats === "function") {
    Promise.resolve(api.getSystemStats()).then((stats) => {
      const system = (stats && stats.system) || {};
      const packages = Array.isArray(system.comfy_package_versions) ? system.comfy_package_versions : [];
      const front = packages.find((one) => one && one.name === "comfyui-frontend-package");
      server.comfyui = text(system.comfyui_version, 40);
      server.frontend = text((front && front.installed) || system.required_frontend_version, 40);
    }).catch(() => undefined);
  }
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
  //: 改动跟踪每认一次改动换一份 activeState:换了(或换了一张工作流)就加一
  let seenWorkflow = null;
  let seenState = null;
  let revision = 0;
  const revisionOf = (active) => {
    const state = active && active.changeTracker ? active.changeTracker.activeState : undefined;
    if (active !== seenWorkflow || state !== seenState) {
      seenWorkflow = active;
      seenState = state;
      revision += 1;
    }
    return revision;
  };
  const subgraphOf = (graph, id) => {
    const map = graph && graph.subgraphs;
    return map && typeof map.get === "function" ? map.get(id) || null : null;
  };
  const capabilities = () => {
    const store = workflows();
    const canvas = app.canvas;
    const changes = tracker();
    return {
      selection: Boolean(app.canvas && app.canvas.selected_nodes),
      setWidget: Boolean(app.canvas),
      refreshCombos: typeof app.refreshComboInNodes === "function",
      export: typeof app.graphToPrompt === "function",
      dirty: Boolean(store && "activeWorkflow" in store),
      save: hasCommand(${JSON.stringify(SAVE_COMMAND)}),
      events: listening,
      marks: Boolean(rootGraph()),
      changes: Boolean(changes && "activeState" in changes),
      locate: Boolean(canvas && (typeof canvas.centerOnNode === "function" || typeof canvas.animateToBounds === "function")),
      subgraphs: Boolean(canvas && typeof canvas.openSubgraph === "function" && rootGraph() && rootGraph().subgraphs),
      readGraph: typeof app.graphToPrompt === "function",
      applyOps: Boolean(window.LiteGraph && typeof window.LiteGraph.createNode === "function" && changes &&
        typeof changes.beforeChange === "function" && typeof changes.afterChange === "function" && typeof changes.undo === "function"),
      openWorkflow: Boolean(typeof app.loadGraphData === "function" && store && typeof store.getWorkflowByPath === "function"),
      toSubgraph: Boolean(rootGraph() && typeof rootGraph().convertToSubgraph === "function"),
      unpackSubgraph: Boolean(rootGraph() && typeof rootGraph().unpackSubgraph === "function"),
    };
  };
  const norm = (value) => String(value).replace(/\\\\/g, "/");
  //: ---- 智能体改图(ADR 0042 第二步) ----
  //: 一层图:根图,或者 rootGraph.subgraphs 里的一份定义(改定义 = 用它的地方一起变)
  const layerOf = (layer) => (layer ? subgraphOf(rootGraph(), layer) : rootGraph());
  const widgetOf = (node, name) => (Array.isArray(node.widgets) ? node.widgets.find((one) => one && one.name === name) : null) || null;
  const inputIndex = (node, name) => (Array.isArray(node.inputs) ? node.inputs.findIndex((one) => one && one.name === name) : -1);
  const outputIndex = (node, name) => {
    const outputs = Array.isArray(node.outputs) ? node.outputs : [];
    const exact = outputs.findIndex((one) => one && one.name === name);
    if (exact >= 0) return exact;
    const typed = outputs.map((one, index) => (one && one.type === name ? index : -1)).filter((index) => index >= 0);
    return typed.length === 1 ? typed[0] : -1;
  };
  const comboValue = (widget, value) => {
    const values = valuesOf(widget);
    if (!Array.isArray(values)) return { ok: true, value };
    const found = values.find((one) => one === value) ?? values.find((one) => norm(one) === norm(value));
    return found === undefined ? { ok: false } : { ok: true, value: found };
  };
  const writeWidget = (node, widget, value) => {
    if (typeof widget.setValue === "function") {
      widget.setValue(value, { e: undefined, node, canvas: app.canvas });
      return;
    }
    const before = widget.value;
    widget.value = value;
    if (typeof widget.callback === "function") widget.callback(value, app.canvas, node);
    if (typeof node.onWidgetChanged === "function") node.onWidgetChanged(widget.name, value, before, widget);
  };
  const valid = (from, to) => {
    const check = window.LiteGraph && window.LiteGraph.isValidConnection;
    return typeof check === "function" ? Boolean(check.call(window.LiteGraph, from, to)) : true;
  };
  //: 新节点放哪:挨着指定的(或这一批里和它连上的第一个)节点,往右(它是下游时往左),和已有的节点不叠
  //: LiteGraph 的位置、大小是 Float32Array,不是数组
  const placed = (node) => Boolean(node && node.pos && node.pos.length >= 2);
  const boundsOf = (node) => [node.pos[0], node.pos[1], (node.size && node.size[0]) || 200, (node.size && node.size[1]) || 80];
  const overlaps = (a, b) => a[0] < b[0] + b[2] + 20 && b[0] < a[0] + a[2] + 20 && a[1] < b[1] + b[3] + 20 && b[1] < a[1] + a[3] + 20;
  const place = (graph, node, anchor, downstream) => {
    const [, , width, height] = boundsOf(node);
    let x;
    let y;
    if (anchor) {
      const [ax, ay, aw] = boundsOf(anchor);
      x = downstream ? ax - width - 60 : ax + aw + 60;
      y = ay;
    } else {
      const others = nodesOf(graph).filter((one) => one !== node && placed(one));
      x = others.length ? Math.max(...others.map((one) => boundsOf(one)[0] + boundsOf(one)[2])) + 80 : 0;
      y = others.length ? Math.min(...others.map((one) => boundsOf(one)[1])) : 0;
    }
    for (let tries = 0; tries < 60; tries += 1) {
      const box = [x, y, width, height];
      const hit = nodesOf(graph).find((one) => one !== node && placed(one) && overlaps(box, boundsOf(one)));
      if (!hit) break;
      y = boundsOf(hit)[1] + boundsOf(hit)[3] + 40;
    }
    if (typeof node.setPos === "function") node.setPos(x, y);
    else node.pos = [x, y];
  };
  //: 一批改动先逐条查(不碰画布),查出来的每一条变成一个「怎么改」的步骤;有一条不对就只回原因
  const resolveOps = (ops) => {
    const problems = [];
    const steps = [];
    const temps = new Map();
    const removed = new Set();
    const ioAdded = new Map();
    const ioRemoved = new Set();
    const wired = new Set();
    ops.forEach((op, index) => {
      const fail = (message) => problems.push("#" + (index + 1) + " " + op.op + ": " + message);
      const layer = op.layer || null;
      const graph = layerOf(layer);
      if (!graph) return fail("no subgraph " + layer);
      const key = (id) => (layer || "") + "|" + id;
      const nodeAt = (id) => {
        if (String(id).charAt(0) === "$") {
          const temp = temps.get(id);
          return temp && temp.layer === layer ? temp.node : null;
        }
        return removed.has(key(id)) ? null : findNode(graph, id);
      };
      const ioOf = (side, name) => {
        if (ioRemoved.has(key(side + ":" + name))) return null;
        const listed = (side === "input" ? graph.inputs : graph.outputs) || [];
        const found = Array.isArray(listed) ? listed.find((one) => one && one.name === name) : null;
        if (found) return { type: found.type, linked: Array.isArray(found.linkIds) && found.linkIds.length > 0 };
        return ioAdded.has(key(side + ":" + name)) ? { type: ioAdded.get(key(side + ":" + name)), linked: false } : null;
      };
      const isSubgraph = graph !== rootGraph() && typeof graph.addInput === "function";
      if (op.op === "add_node") {
        if (temps.has(op.id)) return fail("temporary name used twice: " + op.id);
        const node = window.LiteGraph.createNode(op.type);
        if (!node) return fail("no node type " + op.type);
        for (const [name, value] of Object.entries(op.widgets || {})) {
          const widget = widgetOf(node, name);
          if (!widget) return fail("no widget " + name);
          if (!comboValue(widget, value).ok) return fail(name + " = " + value + " is not in its list");
        }
        if (op.near && !nodeAt(op.near)) return fail("no node " + op.near);
        temps.set(op.id, { layer, node, near: op.near || null });
        steps.push((created) => {
          if (op.title) node.title = op.title;
          graph.add(node);
          for (const [name, value] of Object.entries(op.widgets || {})) writeWidget(node, widgetOf(node, name), comboValue(widgetOf(node, name), value).value);
          created[op.id] = { node, graph, near: op.near ? { node: nodeAt(op.near), downstream: false } : null };
        });
        return;
      }
      if (op.op === "add_io" || op.op === "remove_io") {
        if (!isSubgraph) return fail("not a subgraph");
        const existing = ioOf(op.side, op.name);
        if (op.op === "add_io") {
          if (existing) return fail("already has " + op.side + " " + op.name);
          ioAdded.set(key(op.side + ":" + op.name), op.type);
          ioRemoved.delete(key(op.side + ":" + op.name));
          steps.push(() => (op.side === "input" ? graph.addInput(op.name, op.type) : graph.addOutput(op.name, op.type)));
          return;
        }
        if (!existing) return fail("no " + op.side + " " + op.name);
        ioRemoved.add(key(op.side + ":" + op.name));
        steps.push(() => {
          const listed = op.side === "input" ? graph.inputs : graph.outputs;
          const slot = listed.find((one) => one && one.name === op.name);
          if (!slot) throw new Error("no " + op.side + " " + op.name);
          if (op.side === "input") graph.removeInput(slot);
          else graph.removeOutput(slot);
        });
        return;
      }
      if (op.op === "connect") {
        const fromIo = op.from.node === "@in";
        const toIo = op.to.node === "@out";
        if (op.from.node === "@out" || op.to.node === "@in" || (fromIo && toIo)) return fail("bad ends");
        if ((fromIo || toIo) && !isSubgraph) return fail("@in / @out only inside a subgraph");
        let fromType;
        let toType;
        const source = fromIo ? null : nodeAt(op.from.node);
        const target = toIo ? null : nodeAt(op.to.node);
        if (fromIo) {
          const io = ioOf("input", op.from.name);
          if (!io) return fail("no subgraph input " + op.from.name);
          fromType = io.type;
        } else {
          if (!source) return fail("no node " + op.from.node);
          const slot = outputIndex(source, op.from.name);
          if (slot < 0) return fail("node " + op.from.node + " has no output " + op.from.name);
          fromType = source.outputs[slot].type;
        }
        if (toIo) {
          const io = ioOf("output", op.to.name);
          if (!io) return fail("no subgraph output " + op.to.name);
          toType = io.type;
        } else {
          if (!target) return fail("no node " + op.to.node);
          const slot = inputIndex(target, op.to.name);
          if (slot < 0) return fail("node " + op.to.node + " has no input " + op.to.name);
          toType = target.inputs[slot].type;
        }
        if (!valid(fromType, toType)) return fail(fromType + " can't connect to " + toType);
        if (!toIo) wired.add(key(op.to.node + "." + op.to.name));
        steps.push(() => {
          const origin = fromIo ? null : nodeAt(op.from.node);
          const goal = toIo ? null : nodeAt(op.to.node);
          let link;
          if (fromIo) {
            const io = graph.inputs.find((one) => one && one.name === op.from.name);
            link = io.connect(goal.inputs[inputIndex(goal, op.to.name)], goal);
          } else if (toIo) {
            const io = graph.outputs.find((one) => one && one.name === op.to.name);
            link = io.connect(origin.outputs[outputIndex(origin, op.from.name)], origin);
          } else {
            link = origin.connect(outputIndex(origin, op.from.name), goal, inputIndex(goal, op.to.name));
          }
          if (!link) throw new Error("connect refused: " + op.from.node + "." + op.from.name + " -> " + op.to.node + "." + op.to.name);
        });
        return;
      }
      if (op.op === "disconnect") {
        if (op.to.node === "@out") {
          const io = ioOf("output", op.to.name);
          if (!isSubgraph || !io) return fail("no subgraph output " + op.to.name);
          steps.push(() => {
            const slot = graph.outputs.find((one) => one && one.name === op.to.name);
            if (slot) slot.disconnect();
          });
          return;
        }
        const target = nodeAt(op.to.node);
        if (!target) return fail("no node " + op.to.node);
        const slot = inputIndex(target, op.to.name);
        if (slot < 0) return fail("node " + op.to.node + " has no input " + op.to.name);
        if (target.inputs[slot].link == null && !wired.has(key(op.to.node + "." + op.to.name))) return fail(op.to.name + " is not connected");
        wired.delete(key(op.to.node + "." + op.to.name));
        steps.push(() => target.disconnectInput(inputIndex(target, op.to.name)));
        return;
      }
      if (op.op === "to_subgraph") {
        if (typeof graph.convertToSubgraph !== "function") return fail("unsupported");
        const nodes = op.nodes.map(nodeAt);
        if (nodes.some((one) => !one)) return fail("no node " + op.nodes[nodes.findIndex((one) => !one)]);
        steps.push((created) => {
          const result = graph.convertToSubgraph(new Set(nodes));
          if (!result || !result.node) throw new Error("convertToSubgraph failed");
          if (op.name && result.subgraph) result.subgraph.name = op.name;
          created["@subgraph"] = { node: result.node, graph, packed: true };
        });
        return;
      }
      const node = nodeAt(op.node);
      if (!node) return fail("no node " + op.node);
      if (op.op === "remove_node") {
        removed.add(key(op.node));
        if (String(op.node).charAt(0) === "$") temps.delete(op.node);
        steps.push(() => graph.remove(node));
      } else if (op.op === "set_widget") {
        const widget = widgetOf(node, op.widget);
        if (!widget) return fail("node " + op.node + " has no widget " + op.widget);
        const picked = comboValue(widget, op.value);
        if (!picked.ok) return fail(op.widget + " = " + op.value + " is not in its list");
        steps.push(() => writeWidget(node, widgetOf(node, op.widget), picked.value));
      } else if (op.op === "set_title") {
        steps.push(() => {
          node.title = op.title;
        });
      } else if (op.op === "mode") {
        steps.push(() => {
          if (typeof node.changeMode === "function") node.changeMode(op.mode);
          else node.mode = op.mode;
        });
      } else if (op.op === "promote" || op.op === "unpromote") {
        if (!isSubgraph) return fail("not inside a subgraph");
        const widget = widgetOf(node, op.widget);
        const slot = widget && typeof node.getSlotFromWidget === "function" ? node.getSlotFromWidget(widget) : null;
        if (!slot) return fail("node " + op.node + " has no widget " + op.widget);
        if (op.op === "promote") {
          if (slot.link != null) return fail(op.widget + " is already connected");
          if (ioOf("input", op.name)) return fail("subgraph already has input " + op.name);
          ioAdded.set(key("input:" + op.name), String(slot.type ?? widget.type ?? "*"));
          steps.push(() => {
            const input = graph.addInput(op.name, String(slot.type ?? widget.type ?? "*"));
            if (slot.label) input.label = slot.label;
            if (!input.connect(slot, node)) throw new Error("promote failed: " + op.widget);
          });
        } else {
          const link = slot.link != null && typeof graph.getLink === "function" ? graph.getLink(slot.link) : null;
          const source = graph.inputNode && link && String(link.origin_id) === String(graph.inputNode.id) ? graph.inputs[link.origin_slot] : null;
          if (!source) return fail(op.widget + " is not promoted");
          steps.push(() => {
            if (Array.isArray(source.linkIds) && source.linkIds.length > 1) graph.removeLink(link.id);
            else graph.removeInput(source);
          });
        }
      } else if (op.op === "unpack") {
        if (typeof graph.unpackSubgraph !== "function") return fail("unsupported");
        if (!(typeof node.isSubgraphNode === "function" && node.isSubgraphNode())) return fail("node " + op.node + " is not a subgraph");
        steps.push(() => {
          if (!graph.unpackSubgraph(node)) throw new Error("unpackSubgraph failed");
        });
      } else {
        fail("unknown op");
      }
    });
    return { problems, steps };
  };
  //: 查过的一批真改到画布上:只记一步撤销(前端的改动跟踪在 beforeChange / afterChange 之间不记,afterChange 时记一次);
  //: 万一改到一半出错,把记下的那一步退掉(和 Ctrl+Z 同一条路),再把它从「重做」里拿掉 —— 画布回到改之前
  const applyResolved = async (steps) => {
    const changes = tracker();
    const depth = changes.undoQueue.length;
    const created = {};
    let failure = null;
    changes.beforeChange();
    try {
      for (const step of steps) step(created);
      for (const entry of Object.values(created)) {
        if (entry.packed) continue;
        const near = entry.near || neighbour(entry.graph, entry.node);
        place(entry.graph, entry.node, near && near.node, near && near.downstream);
      }
    } catch (error) {
      failure = error;
    } finally {
      changes.afterChange();
    }
    if (failure) {
      if (changes.undoQueue.length > depth) {
        await changes.undo();
        changes.redoQueue.pop();
      }
      return { error: "failed", message: String((failure && failure.message) || failure).slice(0, 500) };
    }
    const canvas = app.canvas;
    if (canvas && typeof canvas.setDirty === "function") canvas.setDirty(true, true);
    return { ok: true, created: Object.fromEntries(Object.entries(created).map(([name, entry]) => [name, text(String(entry.node.id), 40)])) };
  };
  //: 新节点挨着谁:它连着的第一个节点(输入那头的上游、输出那头的下游);指定了 near 的照指定的
  const neighbour = (graph, node) => {
    const find = (id) => (typeof graph.getLink === "function" ? graph.getLink(id) : null);
    for (const input of node.inputs || []) {
      const link = input && input.link != null ? find(input.link) : null;
      const origin = link ? findNode(graph, link.origin_id) : null;
      if (origin) return { node: origin, downstream: false };
    }
    for (const output of node.outputs || []) {
      for (const id of (output && output.links) || []) {
        const link = find(id);
        const target = link ? findNode(graph, link.target_id) : null;
        if (target) return { node: target, downstream: true };
      }
    }
    return null;
  };
  //: 开着的工作流里没人用的名字(workflows/<名字>.json 已经有了就加「 (2)」)
  const freeName = (base) => {
    const store = workflows();
    const clean = (base || "Mosael").replace(/[\\\\/:*?"<>|]/g, " ").trim().slice(0, 120) || "Mosael";
    let name = clean;
    for (let n = 2; store.getWorkflowByPath("workflows/" + name + ".json") && n < 1000; n += 1) name = clean + " (" + n + ")";
    return name;
  };
  const openedInfo = () => {
    const active = workflows().activeWorkflow;
    return active ? { path: text(active.path, 600), name: text(active.filename, 300), temporary: Boolean(active.isTemporary) } : null;
  };
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
          temporary: Boolean(active.isTemporary), modified: Boolean(active.isModified), revision: revisionOf(active) } : null,
        selection: { count: nodes.length, node: nodes.length === 1 ? describe(nodes[0]) : null },
        clientId: text(api && (api.clientId || api.initialClientId), 100),
        server: { comfyui: server.comfyui, frontend: server.frontend },
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
    runControls(phase) {
      // 照 ComfyUI 自己的 app.queuePrompt(1.53.10):提交前每个节点(连同子图里的)的每个 widget 走 beforeQueued,排上之后走
      // afterQueued,提升到子图节点上的那一格交给前端自己的 applyPromotedWidgetControl。没有这些钩子的前端:什么都不做
      const hook = phase === "before" ? "beforeQueued" : "afterQueued";
      const helpers = window.comfyAPI && window.comfyAPI.promotedWidgetControl;
      const promoted = helpers && typeof helpers.applyPromotedWidgetControl === "function"
        ? helpers.applyPromotedWidgetControl : null;
      const visit = (graph, depth) => {
        if (depth > 16) return;
        for (const node of nodesOf(graph)) {
          if (!node) continue;
          if (typeof node.isSubgraphNode === "function" && node.isSubgraphNode() && node.subgraph) visit(node.subgraph, depth + 1);
          for (const widget of Array.isArray(node.widgets) ? node.widgets : []) {
            if (widget && typeof widget[hook] === "function") widget[hook]({ isPartialExecution: false });
          }
          if (promoted) promoted(node, hook);
        }
      };
      visit(rootGraph(), 0);
      touched(rootGraph());
      return { ok: true };
    },
    async readGraph() {
      if (typeof app.graphToPrompt !== "function") return { error: "unsupported", message: "graphToPrompt" };
      const result = await app.graphToPrompt();
      const workflow = result && result.workflow;
      if (!workflow || !Array.isArray(workflow.nodes)) return { error: "failed", message: "graphToPrompt gave no workflow" };
      const canvas = app.canvas;
      const root = rootGraph();
      const store = workflows();
      const active = store && store.activeWorkflow;
      const layer = canvas && canvas.graph && canvas.graph !== root ? text(canvas.graph.id, 64) : "";
      return JSON.parse(JSON.stringify({ ok: true, graph: {
        workflow,
        selection: selected().slice(0, 1000).map((node) => text(String(node.id), 40)),
        modified: Boolean(active && active.isModified),
        layer: layer || null,
        info: active ? { name: text(active.filename, 300), path: text(active.path, 600), temporary: Boolean(active.isTemporary) } : null,
      } }));
    },
    async applyOps(ops) {
      if (!capabilities().applyOps) return { error: "unsupported", message: "applyOps" };
      const { problems, steps } = resolveOps(ops);
      if (problems.length) return { error: "invalid", problems: problems.slice(0, 20) };
      return applyResolved(steps);
    },
    async openWorkflow(request) {
      if (!capabilities().openWorkflow) return { error: "unsupported", message: "openWorkflow" };
      const store = workflows();
      if (request.path) {
        // 存着的那一张:和工作流库「在工作台里打开」同一条路(见 comfyEditor.comfyOpenWorkflowScript)
        if (typeof store.syncWorkflows === "function") await store.syncWorkflows();
        const saved = store.getWorkflowByPath("workflows/" + request.path);
        if (!saved) return { error: "noWorkflow" };
        if (!saved.isLoaded) await saved.load();
        await app.loadGraphData(JSON.parse(JSON.stringify(saved.activeState)), true, true, saved);
        return { ok: true, workflow: openedInfo() };
      }
      // 一张没存过的新工作流:前端用名字开一个临时标签(和打开模板同一条路),不存盘
      const name = freeName(request.name);
      const loaded = await app.loadGraphData(request.graph, true, true, name, { checkForRerouteMigration: false });
      const opened = openedInfo();
      if (loaded === false || !opened || !opened.temporary || opened.path !== "workflows/" + name + ".json") {
        return { error: "failed", message: "the new tab did not open" };
      }
      if (!request.ops || !request.ops.length) return { ok: true, workflow: opened };
      const { problems, steps } = resolveOps(request.ops);
      if (problems.length) return { error: "invalid", problems: problems.slice(0, 20), workflow: opened };
      const applied = await applyResolved(steps);
      if (!applied.ok) return Object.assign(applied, { workflow: opened });
      // 新标签页里搭出来的:画面移到这几个节点上(载入时前端只按载进来的那张图摆过一次视角)
      const canvas = app.canvas;
      const placedNodes = nodesOf(rootGraph()).filter(placed);
      if (placedNodes.length && canvas && canvas.ds && typeof canvas.ds.fitToBounds === "function") {
        const boxes = placedNodes.map(boundsOf);
        const left = Math.min(...boxes.map((one) => one[0]));
        const top = Math.min(...boxes.map((one) => one[1]));
        canvas.ds.fitToBounds([left, top, Math.max(...boxes.map((one) => one[0] + one[2])) - left,
          Math.max(...boxes.map((one) => one[1] + one[3])) - top]);
        if (typeof canvas.setDirty === "function") canvas.setDirty(true, true);
      }
      return { ok: true, workflow: openedInfo(), created: applied.created };
    },
    locate(id, subgraphId) {
      const canvas = app.canvas;
      const root = rootGraph();
      let graph = root;
      const path = String(id).split(":");
      if (!subgraphId && path.length > 1) {
        // 从根图往里走:每一段是这一层里用着子图的那个节点,最后一段是要找的节点(ADR 0042)
        const layers = [];
        for (const part of path.slice(0, -1)) {
          const holder = findNode(graph, part);
          const inner = holder && (holder.subgraph || subgraphOf(root, holder.type));
          if (!inner) return { error: "noNode" };
          layers.push(inner);
          graph = inner;
        }
        const target = findNode(graph, path[path.length - 1]);
        if (!target) return { error: "noNode" };
        if (typeof canvas.openSubgraph !== "function") return { error: "inSubgraph" };
        if (canvas.graph !== root && typeof canvas.setGraph === "function") canvas.setGraph(root);
        for (const inner of layers) if (canvas.graph !== inner) canvas.openSubgraph(inner);
        id = path[path.length - 1];
      } else if (subgraphId) {
        const sub = subgraphOf(root, subgraphId);
        if (!sub || !findNode(sub, id)) return { error: "noNode" };
        if (typeof canvas.openSubgraph !== "function") return { error: "inSubgraph" };
        if (canvas.graph !== sub) canvas.openSubgraph(sub);
        graph = sub;
      } else if (canvas.graph !== root && typeof canvas.setGraph === "function") {
        // 现在停在某张子图里:先回根图
        canvas.setGraph(root);
      }
      const node = findNode(graph, id);
      if (!node) return { error: "noNode" };
      if (typeof canvas.deselectAll === "function") canvas.deselectAll();
      if (typeof canvas.selectItems === "function") canvas.selectItems([node]);
      else if (typeof canvas.selectNode === "function") canvas.selectNode(node, false);
      if (typeof canvas.centerOnNode === "function") canvas.centerOnNode(node);
      else if (typeof canvas.animateToBounds === "function" && node.boundingRect) canvas.animateToBounds(node.boundingRect);
      if (typeof canvas.setDirty === "function") canvas.setDirty(true, true);
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
    locate: "return bridge.locate(call.node, call.subgraph);",
    readGraph: "return await bridge.readGraph();",
    runControls: "return bridge.runControls(call.phase);",
    applyOps: "return await bridge.applyOps(call.ops);",
    openWorkflow: "return await bridge.openWorkflow(call);",
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
  /** 前端的改动跟踪在:轮询报的 `revision` 跟着图上的改动走(缺失项据此自己重新检查) */
  changes: boolean;
  /** 能在画布上定位节点(选中、移到中间) */
  locate: boolean;
  /** 能进子图(定位子图里的节点);没有时只能说「在子图 X 里」 */
  subgraphs: boolean;
  /** 能把整张图交给智能体读(ADR 0042) */
  readGraph: boolean;
  /** 能让智能体改图(一批一步撤销,ADR 0042 第二步) */
  applyOps: boolean;
  /** 能在新标签页开一张整图 / 打开存着的那一张 */
  openWorkflow: boolean;
  /** 这版前端能把几个节点打包成子图 / 把子图拆开(没有就只能在 ComfyUI 里自己点) */
  toSubgraph: boolean;
  unpackSubgraph: boolean;
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
  /**
   * 画布上开着的那一张:`path` 是 `workflows/` 下的相对路径(没存过的是空串);`key` 认的是**哪一张**(前端工作流仓库里的路径,
   * 没存过的也有);`revision` 是这一张的图改过几回(只增,换一张也加一)。
   */
  workflow: { path: string; name: string; temporary: boolean; modified: boolean; key: string; revision: number } | null;
  selection: { count: number; node: WorkbenchNode | null };
  clientId: string;
  /** 那台 ComfyUI 和它前端的版本(如 `0.39.0`、`1.53.10`);还没问到是空串 */
  server: { comfyui: string; frontend: string };
  events: WorkbenchEvent[];
}

const CAPABILITIES: (keyof WorkbenchCapabilities)[] = ["selection", "setWidget", "refreshCombos", "export", "dirty", "save",
  "events", "marks", "changes", "locate", "subgraphs", "readGraph", "applyOps", "openWorkflow", "toSubgraph", "unpackSubgraph"];
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
  const workflow: WorkbenchState["workflow"] = isRecord(raw.workflow)
    ? {
        ...parseOpenWorkflow(raw.workflow),
        modified: raw.workflow.modified === true,
        revision: Math.max(0, Math.floor(num(raw.workflow.revision))),
      }
    : null;
  const selection = isRecord(raw.selection) ? raw.selection : {};
  const node = isRecord(selection.node) ? parseNode(selection.node) : null;
  const server = isRecord(raw.server) ? raw.server : {};
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
    server: { comfyui: version(server.comfyui), frontend: version(server.frontend) },
    events,
  };
}

/** 版本号只收像版本号的(`0.39.0`、`1.53.10-rc1`):它要写进给智能体的上下文里。 */
const version = (value: unknown) => (/^[0-9A-Za-z.+_-]{1,40}$/.test(str(value, 40)) ? str(value, 40) : "");

/** 开着的是哪一张:`path` 去掉前端的 `workflows/` 前缀,不在 `workflows/` 下的(前端自己的临时路径)当没存过;`key` 认哪一张。 */
function parseOpenWorkflow(raw: Record<string, unknown>): { path: string; name: string; temporary: boolean; key: string } {
  const path = str(raw.path, 600);
  const saved = path.startsWith("workflows/") && path.toLowerCase().endsWith(".json") && raw.temporary !== true;
  const name = str(raw.name, 300);
  return { path: saved ? path.slice("workflows/".length) : "", name, temporary: !saved, key: path || name };
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

/**
 * 交给智能体读的整张图(ADR 0042):界面格式的整图(和导出同一个上限)、选中的节点(画布这一层里的编号)、改没改、画布停在
 * 哪一层(子图的 id,根图是 null)、开着的是哪一张。整图本身不在这里拆 —— 摘要、诊断由插件做,这里只核对形状和大小。
 */
export interface WorkbenchGraph {
  workflow: Record<string, unknown>;
  selection: string[];
  modified: boolean;
  layer: string | null;
  info: { path: string; name: string; temporary: boolean; key: string } | null;
}

export function parseWorkbenchGraph(raw: unknown): WorkbenchGraph | null {
  if (!isRecord(raw) || !isRecord(raw.workflow) || !Array.isArray(raw.workflow.nodes)) return null;
  if (JSON.stringify(raw.workflow).length > MAX_EXPORT_CHARS) return null;
  const selection = (Array.isArray(raw.selection) ? raw.selection : []).slice(0, 1000)
    .map((one) => str(one, 40)).filter((one) => /^-?\d{1,10}$/.test(one));
  const layer = str(raw.layer, 64);
  return {
    workflow: raw.workflow,
    selection,
    modified: raw.modified === true,
    layer: /^[A-Za-z0-9_-]{1,64}$/.test(layer) ? layer : null,
    info: isRecord(raw.info) ? parseOpenWorkflow(raw.info) : null,
  };
}

/** 改图、开新标签之后:开着的是哪一张(`path` 是前端的路径,`workflows/` 开头)。 */
export interface WorkbenchOpened {
  path: string;
  name: string;
  temporary: boolean;
}

/**
 * 别的调用的回答:成了 / 一个原因码(noNode、noWidget、notInList、missing、elsewhere、failed、unsupported、invalid、
 * noWorkflow……)。改图成了带 `created`(临时名字 → 建出来的节点号;打包出来的那个子图节点是 `@subgraph`),开新标签带
 * `workflow`;一批里有说不通的回 `invalid` 加每一条的原因(`problems`),画布一样没动。
 */
export type WorkbenchCallResult =
  | { ok: true; value?: string | number | boolean | null; export?: WorkbenchExport; graph?: WorkbenchGraph;
      created?: Record<string, string>; workflow?: WorkbenchOpened }
  | { ok: false; error: string; message?: string; nodes?: string[]; problems?: string[]; workflow?: WorkbenchOpened };

const ERRORS = new Set(["noNode", "noWidget", "notInList", "missing", "elsewhere", "failed", "notReady", "closed", "inSubgraph",
  "unsupported", "invalid", "noWorkflow"]);

function parseOpened(raw: unknown): WorkbenchOpened | undefined {
  if (!isRecord(raw)) return undefined;
  const path = str(raw.path, 600);
  return path ? { path, name: str(raw.name, 300), temporary: raw.temporary === true } : undefined;
}

export function parseWorkbenchResult(call: WorkbenchCall, raw: unknown): WorkbenchCallResult {
  if (isRecord(raw) && typeof raw.error === "string") {
    const error = ERRORS.has(raw.error) ? raw.error : "failed";
    const nodes = Array.isArray(raw.nodes) ? raw.nodes.map((one) => str(one, 40)).filter(Boolean).slice(0, 20) : undefined;
    const problems = Array.isArray(raw.problems) ? raw.problems.map((one) => str(one, 500)).filter(Boolean).slice(0, 20) : undefined;
    const workflow = parseOpened(raw.workflow);
    return { ok: false, error, ...(raw.message ? { message: str(raw.message, 500) } : {}), ...(nodes ? { nodes } : {}),
      ...(problems ? { problems } : {}), ...(workflow ? { workflow } : {}) };
  }
  if (call.op === "export") {
    const exported = parseWorkbenchExport(raw);
    return exported ? { ok: true, export: exported } : { ok: false, error: "failed", message: "malformed export" };
  }
  if (!isRecord(raw) || raw.ok !== true) return { ok: false, error: "failed" };
  if (call.op === "readGraph") {
    const graph = parseWorkbenchGraph(raw.graph);
    return graph ? { ok: true, graph } : { ok: false, error: "failed", message: "malformed graph" };
  }
  if (call.op === "applyOps" || call.op === "openWorkflow") {
    const created = isRecord(raw.created)
      ? Object.fromEntries(Object.entries(raw.created).slice(0, MAX_EDIT_OPS)
        .map(([name, id]) => [str(name, 40), str(id, 40)]).filter(([name, id]) => /^(\$[A-Za-z0-9_]{1,32}|@subgraph)$/.test(name) && /^-?\d{1,10}$/.test(id)))
      : {};
    const workflow = parseOpened(raw.workflow);
    return { ok: true, created, ...(workflow ? { workflow } : {}) };
  }
  if (call.op === "setWidget") {
    const value = raw.value;
    return { ok: true, value: typeof value === "string" ? value.slice(0, 4000)
      : (typeof value === "number" && Number.isFinite(value)) || typeof value === "boolean" ? value : null };
  }
  return { ok: true };
}
