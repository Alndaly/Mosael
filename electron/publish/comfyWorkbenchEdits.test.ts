/**
 * 桥第 5 版:智能体改图(applyOps)、在新标签页开一张(openWorkflow)—— ADR 0042 第二步。
 *
 * 一页假的 ComfyUI 前端,照 1.53.10 里桥碰得到的那几样搭:`LiteGraph.createNode` / `isValidConnection`、根图和子图(加删节点、
 * 连线、`getLink`、子图边界的 `addInput` / `addOutput` / `removeInput` 和口的 `connect`、`convertToSubgraph` /
 * `unpackSubgraph`)、改动跟踪(**和前端一样**:`beforeChange` 计数,`afterChange` 归零时记一步,记的是整张图的样子)、
 * 工作流仓库和 `loadGraphData`(给名字就开一个临时标签)。真前端上的实测见 ADR 0042 第二步的实现记录。
 */
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

import {
  SAVE_COMMAND,
  parseWorkbenchResult,
  workbenchCallScript,
  workbenchInstallScript,
  workbenchPollScript,
  type WorkbenchCall,
  type WorkbenchEditOp,
} from "./comfyWorkbench";

const ORIGIN = "http://127.0.0.1:38188";

interface Slot {
  name: string;
  type: string;
  link?: number | null;
  links?: number[];
  widget?: { name: string };
  label?: string;
}
interface Widget {
  name: string;
  type: string;
  value: unknown;
  options: { values?: unknown[] };
}
interface Link {
  id: number;
  origin_id: number;
  origin_slot: number;
  target_id: number;
  target_slot: number;
  type: string;
}

//: 几种节点的样子(输入 / 输出 / 控件),和 ComfyUI 的定义一致到桥用得着的程度:每格控件都有一个同名的输入口(1.53 起)
const TYPES: Record<string, { inputs: [string, string][]; outputs: [string, string][]; widgets: [string, string, unknown, unknown[]?][] }> = {
  CheckpointLoaderSimple: { inputs: [], outputs: [["MODEL", "MODEL"], ["CLIP", "CLIP"], ["VAE", "VAE"]],
                            widgets: [["ckpt_name", "combo", "a.safetensors", ["a.safetensors", "sdxl/b.safetensors"]]] },
  LoraLoader: { inputs: [["model", "MODEL"], ["clip", "CLIP"]], outputs: [["MODEL", "MODEL"], ["CLIP", "CLIP"]],
                widgets: [["lora_name", "combo", "detail.safetensors", ["detail.safetensors", "pony/style.safetensors"]],
                          ["strength_model", "number", 1]] },
  KSampler: { inputs: [["model", "MODEL"], ["positive", "CONDITIONING"], ["negative", "CONDITIONING"], ["latent_image", "LATENT"]],
              outputs: [["LATENT", "LATENT"]],
              widgets: [["seed", "number", 0], ["steps", "number", 20], ["cfg", "number", 7], ["denoise", "number", 1],
                        ["sampler_name", "combo", "euler", ["euler", "dpmpp_2m"]]] },
  VAEDecode: { inputs: [["samples", "LATENT"], ["vae", "VAE"]], outputs: [["IMAGE", "IMAGE"]], widgets: [] },
  PreviewImage: { inputs: [["images", "IMAGE"]], outputs: [], widgets: [] },
};

class FakeNode {
  id: number | string = -1;
  title = "";
  mode = 0;
  pos = new Float32Array([0, 0]);
  size = new Float32Array([200, 100]);
  graph: FakeGraph | null = null;
  inputs: Slot[];
  outputs: Slot[];
  widgets: Widget[];
  subgraph?: FakeSubgraph;

  constructor(readonly type: string) {
    const spec = TYPES[type] ?? { inputs: [], outputs: [], widgets: [] };
    this.inputs = [...spec.inputs.map(([name, kind]) => ({ name, type: kind, link: null })),
                   ...spec.widgets.map(([name, kind]) => ({ name, type: kind === "combo" ? "COMBO" : "INT", link: null, widget: { name } }))];
    this.outputs = spec.outputs.map(([name, kind]) => ({ name, type: kind, links: [] }));
    this.widgets = spec.widgets.map(([name, kind, value, values]) => ({ name, type: kind, value, options: values ? { values } : {} }));
  }

  connect(slot: number, target: FakeNode, targetSlot: number) {
    return this.graph!.link(this.id as number, slot, target, targetSlot, this.outputs[slot].type);
  }

  disconnectInput(slot: number) {
    const link = this.inputs[slot].link;
    if (link != null) this.graph!.removeLink(link);
  }

  getSlotFromWidget(widget: Widget) {
    return this.inputs.find((one) => one.widget?.name === widget.name);
  }

  changeMode(mode: number) {
    this.mode = mode;
  }

  setPos(x: number, y: number) {
    this.pos[0] = x;
    this.pos[1] = y;
  }

  isSubgraphNode() {
    return Boolean(this.subgraph);
  }
}

class FakeGraph {
  nodes: FakeNode[] = [];
  links = new Map<number, Link>();
  //: 测试用:让下一次连线被拒(真前端里扩展的 onConnectInput 可以这样做)—— 改到一半出错
  refuseNextLink = false;

  constructor(readonly state: { lastNodeId: number; lastLinkId: number }) {}

  add(node: FakeNode) {
    if (node.id === -1) node.id = ++this.state.lastNodeId;
    node.graph = this;
    this.nodes.push(node);
  }

  remove(node: FakeNode) {
    for (const link of [...this.links.values()]) if (link.origin_id === node.id || link.target_id === node.id) this.removeLink(link.id);
    this.nodes = this.nodes.filter((one) => one !== node);
  }

  getNodeById(id: unknown) {
    return this.nodes.find((one) => String(one.id) === String(id)) ?? null;
  }

  getLink(id: number) {
    return this.links.get(id);
  }

  link(originId: number, originSlot: number, target: FakeNode, targetSlot: number, type: string): Link | null {
    if (this.refuseNextLink) {
      this.refuseNextLink = false;
      return null;
    }
    const old = target.inputs[targetSlot].link;
    if (old != null) this.removeLink(old);
    const link = { id: ++this.state.lastLinkId, origin_id: originId, origin_slot: originSlot, target_id: target.id as number,
                   target_slot: targetSlot, type };
    this.links.set(link.id, link);
    target.inputs[targetSlot].link = link.id;
    this.getNodeById(originId)?.outputs[originSlot].links!.push(link.id);
    return link;
  }

  removeLink(id: number) {
    const link = this.links.get(id);
    if (!link) return;
    this.links.delete(id);
    const target = this.getNodeById(link.target_id);
    if (target) target.inputs[link.target_slot].link = null;
    const origin = this.getNodeById(link.origin_id);
    if (origin) origin.outputs[link.origin_slot].links = origin.outputs[link.origin_slot].links!.filter((one) => one !== id);
  }
}

/** 子图(一份定义):边界上的口照前端那样 —— 输入口连到里面一格(它就成了外面节点上的一格控件),输出口从里面接出来。 */
class FakeSubgraph extends FakeGraph {
  inputs: (Slot & { linkIds: number[]; connect: (slot: Slot, node: FakeNode) => Link | null })[] = [];
  outputs: (Slot & { linkIds: number[]; connect: (slot: Slot, node: FakeNode) => Link | null })[] = [];
  inputNode = { id: -10 };
  outputNode = { id: -20 };

  constructor(state: { lastNodeId: number; lastLinkId: number }, readonly id: string, public name: string) {
    super(state);
  }

  addInput(name: string, type: string) {
    const io = {
      name, type, linkIds: [] as number[],
      connect: (slot: Slot, node: FakeNode) => {
        const link = this.link(-10, this.inputs.indexOf(io), node, node.inputs.indexOf(slot), type);
        if (link) io.linkIds.push(link.id);
        return link;
      },
    };
    this.inputs.push(io);
    return io;
  }

  addOutput(name: string, type: string) {
    const io = {
      name, type, linkIds: [] as number[],
      connect: (slot: Slot, node: FakeNode) => {
        const link = { id: ++this.state.lastLinkId, origin_id: node.id as number, origin_slot: node.outputs.indexOf(slot),
                       target_id: -20, target_slot: this.outputs.indexOf(io), type };
        this.links.set(link.id, link);
        slot.links!.push(link.id);
        io.linkIds = [link.id];
        return link;
      },
    };
    this.outputs.push(io);
    return io;
  }

  removeInput(io: FakeSubgraph["inputs"][number]) {
    for (const id of io.linkIds) this.removeLink(id);
    this.inputs = this.inputs.filter((one) => one !== io);
  }

  removeOutput(io: FakeSubgraph["outputs"][number]) {
    for (const id of io.linkIds) this.links.delete(id);
    this.outputs = this.outputs.filter((one) => one !== io);
  }
}

/** 整张图的样子(和前端的改动跟踪一样,比的是序列化出来的那一份)。 */
function serialize(root: FakeGraph): string {
  const one = (graph: FakeGraph) => ({
    nodes: graph.nodes.map((node) => ({ id: node.id, type: node.type, title: node.title, mode: node.mode,
                                         widgets: node.widgets.map((widget) => widget.value), inputs: node.inputs.map((slot) => slot.link) })),
    links: [...graph.links.values()],
    io: graph instanceof FakeSubgraph ? [graph.inputs.map((io) => io.name), graph.outputs.map((io) => io.name)] : [],
  });
  return JSON.stringify([one(root), ...[...((root as unknown as { subgraphs: Map<string, FakeGraph> }).subgraphs?.values() ?? [])].map(one)]);
}

function editingPage() {
  const state = { lastNodeId: 20, lastLinkId: 50 };
  const root = new FakeGraph(state) as FakeGraph & { subgraphs: Map<string, FakeSubgraph>; convertToSubgraph: unknown; unpackSubgraph: unknown };
  const node = (type: string, id: number, x: number, y: number, graph: FakeGraph = root) => {
    const made = new FakeNode(type);
    made.id = id;
    made.setPos(x, y);
    graph.add(made);
    return made;
  };
  const ckpt = node("CheckpointLoaderSimple", 4, 0, 0);
  const sampler = node("KSampler", 3, 400, 0);
  const decode = node("VAEDecode", 8, 800, 0);
  ckpt.connect(0, sampler, 0);
  sampler.connect(0, decode, 0);
  ckpt.connect(2, decode, 1);
  //: 一份子图(根图上 12 号是它的实例):里面一个 KSampler 5,steps 提升在外面
  const subgraph = new FakeSubgraph(state, "8f1c0e2a-9b7d-4c51", "细节");
  const innerSampler = node("KSampler", 5, 0, 0, subgraph);
  const steps = subgraph.addInput("steps", "INT");
  steps.connect(innerSampler.inputs.find((one) => one.name === "steps")!, innerSampler);
  const instance = node("PreviewImage", 12, 0, 300);
  instance.subgraph = subgraph;
  root.subgraphs = new Map([[subgraph.id, subgraph]]);
  root.convertToSubgraph = vi.fn((items: Set<FakeNode>) => {
    const packed = new FakeNode("PreviewImage");
    root.add(packed);
    for (const item of items) root.remove(item);
    return { node: packed, subgraph: { name: "" } };
  });
  root.unpackSubgraph = vi.fn(() => true);

  const app: Record<string, unknown> = {};
  //: 改动跟踪:和 1.53.10 的 ChangeTracker 同一个规矩(beforeChange 计数、afterChange 归零才记、记的时候比整张图)
  const tracker = {
    changeCount: 0,
    undoQueue: [] as string[],
    redoQueue: [] as string[],
    activeState: serialize(root),
    beforeChange: vi.fn(function (this: typeof tracker) { this.changeCount += 1; }),
    afterChange: vi.fn(function (this: typeof tracker) { this.changeCount -= 1; if (!this.changeCount) this.captureCanvasState(); }),
    captureCanvasState: vi.fn(function (this: typeof tracker) {
      if (this.changeCount) return;
      const now = serialize(root);
      if (now === this.activeState) return;
      this.undoQueue.push(this.activeState);
      //: 前端的撤销队列有上限(ChangeTracker.MAX_HISTORY = 50):先 push 再 shift,满了长度不变
      if (this.undoQueue.length > 50) this.undoQueue.shift();
      this.activeState = now;
      this.redoQueue.length = 0;
    }),
    //: 退一步:真前端用 loadGraphData 把上一份整个载回来;这里记下退到了哪一份
    undo: vi.fn(async function (this: typeof tracker) {
      const previous = this.undoQueue.pop();
      if (!previous) return;
      this.redoQueue.push(this.activeState);
      this.activeState = previous;
    }),
  };
  const active = { path: "workflows/人像/古风.json", filename: "古风", isTemporary: false, isModified: false, changeTracker: tracker };
  const known = new Map<string, unknown>([["workflows/人像/古风.json", active], ["workflows/Qwen 编辑.json", { path: "x" }]]);
  const store = {
    activeWorkflow: active as Record<string, unknown>,
    getWorkflowByPath: (path: string) => known.get(path) ?? null,
  };
  const execute = vi.fn(async () => undefined);
  //: 给名字:开一个临时标签,载进那张图(前端 afterLoadNewGraph → createNewTemporary);图里的节点照类型建出来
  const loadGraphData = vi.fn(async (graph: { nodes: { id: number; type: string }[] }, _clean: boolean, _restore: boolean, workflow: unknown) => {
    if (typeof workflow === "string") {
      const fresh = { path: `workflows/${workflow}.json`, filename: workflow, isTemporary: true, isModified: false, changeTracker: tracker };
      known.set(fresh.path, fresh);
      store.activeWorkflow = fresh;
    }
    root.nodes = [];
    root.links.clear();
    for (const one of graph.nodes) node(one.type, one.id, 0, 0);
    tracker.activeState = serialize(root);
    tracker.undoQueue.length = 0;
    return true;
  });
  Object.assign(app, {
    api: { clientId: "c1", addEventListener: () => undefined },
    canvas: { graph: root, selected_nodes: {}, setDirty: vi.fn(), openSubgraph: vi.fn(), centerOnNode: vi.fn(),
              ds: { fitToBounds: vi.fn() } },
    graph: root,
    rootGraph: root,
    graphToPrompt: vi.fn(async () => ({ workflow: { nodes: [] }, output: {} })),
    loadGraphData,
    extensionManager: { workflow: store, command: { commands: [{ id: SAVE_COMMAND }], execute } },
  });
  const LiteGraph = {
    createNode: vi.fn((type: string) => (TYPES[type] ? new FakeNode(type) : null)),
    isValidConnection: (left: string, right: string) => left === right || left === "*" || right === "*",
  };
  const window: Record<string, unknown> = { app, LiteGraph };
  const context = vm.createContext({ window, location: { origin: ORIGIN } });
  const run = <T = unknown>(script: string) => vm.runInContext(script, context) as Promise<T> | T;
  return { app, root, subgraph, ckpt, sampler, decode, innerSampler, instance, tracker, store, execute, loadGraphData, LiteGraph, run };
}

async function installed() {
  const page = editingPage();
  expect(await page.run(workbenchInstallScript(ORIGIN))).toBe("installed");
  return page;
}

const call = (page: ReturnType<typeof editingPage>, one: WorkbenchCall) => page.run(workbenchCallScript(ORIGIN, one));
/** 画布上现在这张的 key 和改过几回(智能体改图之前 readGraph 读到的;改图时原样带上)。 */
const here = async (page: ReturnType<typeof editingPage>) => {
  const { workflow } = (await page.run(workbenchPollScript(ORIGIN))) as { workflow: { path: string; name: string; revision: number } };
  return { key: workflow.path || workflow.name, revision: workflow.revision };
};
const apply = async (page: ReturnType<typeof editingPage>, ops: WorkbenchEditOp[]) =>
  call(page, { op: "applyOps", ops, expect: await here(page) });
const linkInto = (graph: FakeGraph, node: FakeNode, input: string) => graph.getLink(node.inputs.find((one) => one.name === input)!.link!);

describe("桥第 5 版:智能体改图", () => {
  it("能力表报得出改图、开新标签、打包 / 拆开", async () => {
    const page = await installed();
    const raw = (await page.run(workbenchPollScript(ORIGIN))) as { capabilities: Record<string, boolean> };
    expect(raw.capabilities).toMatchObject({ applyOps: true, openWorkflow: true, toSubgraph: true, unpackSubgraph: true });
  });

  it("一批改动(加节点、连线换掉原来那根、改值、改标题、旁路)都改到画布上,只记一步撤销;新节点的编号按临时名字交回去", async () => {
    const page = await installed();
    const result = await apply(page, [
      { op: "add_node", layer: null, id: "$l", type: "LoraLoader", widgets: { lora_name: "pony\\style.safetensors", strength_model: 0.6 } },
      { op: "connect", layer: null, from: { node: "4", name: "MODEL" }, to: { node: "$l", name: "model" } },
      { op: "connect", layer: null, from: { node: "$l", name: "MODEL" }, to: { node: "3", name: "model" } },
      { op: "set_widget", layer: null, node: "3", widget: "steps", value: 30 },
      { op: "set_title", layer: null, node: "3", title: "采样" },
      { op: "mode", layer: null, node: "8", mode: 4 },
    ]);
    expect(result).toEqual({ ok: true, created: { $l: "21" } });
    const lora = page.root.getNodeById(21)!;
    expect(lora.widgets.map((one) => one.value), "下拉的值换成列表里的写法").toEqual(["pony/style.safetensors", 0.6]);
    expect(linkInto(page.root, lora, "model")?.origin_id).toBe(4);
    expect(linkInto(page.root, page.sampler, "model")?.origin_id, "原来 4 → 3 那根被换掉").toBe(21);
    expect(page.sampler.widgets.find((one) => one.name === "steps")!.value).toBe(30);
    expect([page.sampler.title, page.decode.mode]).toEqual(["采样", 4]);
    expect(page.tracker.undoQueue, "整批只记一步撤销").toHaveLength(1);
    expect(page.tracker.beforeChange).toHaveBeenCalledTimes(1);
    expect(page.tracker.captureCanvasState).toHaveBeenCalledTimes(1);
    expect(page.tracker.changeCount).toBe(0);
    // 新节点挨着它的上游(4)放在右边,不和 3 号叠在一起
    expect(lora.pos[0]).toBeGreaterThan(page.ckpt.pos[0]);
    const overlapping = page.root.nodes.filter((one) => one !== lora && Math.abs(one.pos[0] - lora.pos[0]) < 200 && Math.abs(one.pos[1] - lora.pos[1]) < 100);
    expect(overlapping).toEqual([]);
  });

  it("有一条说不通(节点不在、口不叫这个名字、类型不配、下拉里没有、临时名字没起):一样不改,把每一条的原因交回去", async () => {
    const page = await installed();
    const before = JSON.stringify(page.tracker.activeState);
    const steps = page.sampler.widgets.find((one) => one.name === "steps")!;
    const result = await apply(page, [
      { op: "set_widget", layer: null, node: "3", widget: "steps", value: 99 },
      { op: "add_node", layer: null, id: "$k", type: "KSampler", widgets: { sampler_name: "not_there" } },
      { op: "connect", layer: null, from: { node: "4", name: "VAE" }, to: { node: "3", name: "model" } },
      { op: "connect", layer: null, from: { node: "4", name: "MODEL" }, to: { node: "99", name: "model" } },
      { op: "connect", layer: null, from: { node: "$nope", name: "MODEL" }, to: { node: "3", name: "model" } },
      { op: "remove_node", layer: null, node: "8" },
    ]);
    expect(result).toMatchObject({ error: "invalid" });
    expect((result as { problems: string[] }).problems).toEqual([
      "#2 add_node: sampler_name = not_there is not in its list",
      "#3 connect: VAE can't connect to MODEL",
      "#4 connect: no node 99",
      "#5 connect: no node $nope",
    ]);
    expect(steps.value, "前面那条对的也没改").toBe(20);
    expect(page.root.getNodeById(8), "后面那条对的也没改").not.toBeNull();
    expect(page.tracker.beforeChange).not.toHaveBeenCalled();
    expect(page.tracker.undoQueue).toEqual([]);
    expect(JSON.stringify(page.tracker.activeState)).toBe(before);
    expect(parseWorkbenchResult({ op: "applyOps", ops: [], expect: { key: "k", revision: 0 } }, result)).toEqual({
      ok: false, error: "invalid", problems: (result as { problems: string[] }).problems });
  });

  it("查过了、改到一半前端还是不让(扩展拒了一根线):退掉记下的那一步,也不留在「重做」里 —— 画布回到改之前", async () => {
    const page = await installed();
    page.root.refuseNextLink = true;
    const result = await apply(page, [
      { op: "set_widget", layer: null, node: "3", widget: "steps", value: 31 },
      { op: "connect", layer: null, from: { node: "4", name: "MODEL" }, to: { node: "3", name: "model" } },
    ]);
    expect(result).toMatchObject({ error: "failed" });
    expect(page.tracker.undo).toHaveBeenCalledTimes(1);
    expect(page.tracker.undoQueue).toEqual([]);
    expect(page.tracker.redoQueue, "改了一半的那份不能再被「重做」出来").toEqual([]);
    expect(page.tracker.changeCount).toBe(0);
  });

  //: PLG-4:按撤销队列的长度判「记没记下那一步」,队列满 50 步时 push 再 shift 长度不变 —— 退不回去,画布停在改了一半
  it("这张图上已经改过 50 步(撤销队列满了)时改到一半出错:照样退回改之前", async () => {
    const page = await installed();
    for (let n = 0; n < 50; n += 1) page.tracker.undoQueue.push(`用户的第 ${n + 1} 步`);
    const before = page.tracker.activeState;
    page.root.refuseNextLink = true;
    const result = await apply(page, [
      { op: "set_widget", layer: null, node: "3", widget: "steps", value: 31 },
      { op: "connect", layer: null, from: { node: "4", name: "MODEL" }, to: { node: "3", name: "model" } },
    ]);
    expect(result).toMatchObject({ error: "failed" });
    expect(page.tracker.undo).toHaveBeenCalledTimes(1);
    expect(page.tracker.activeState, "画布回到改之前").toBe(before);
    expect(page.tracker.redoQueue).toEqual([]);
    expect(page.tracker.undoQueue.at(-1), "用户自己的步数还在(最早那一步是前端自己挤掉的)").toBe("用户的第 50 步");
  });

  it("什么都没改成就出错:没记下那一步,就不退 —— 不能把用户自己的上一步退掉", async () => {
    const page = await installed();
    page.tracker.undoQueue.push("用户自己的上一步");
    page.root.refuseNextLink = true;
    const result = await apply(page, [{ op: "connect", layer: null, from: { node: "4", name: "MODEL" }, to: { node: "3", name: "model" } }]);
    expect(result).toMatchObject({ error: "failed" });
    expect(page.tracker.undo).not.toHaveBeenCalled();
    expect(page.tracker.undoQueue).toEqual(["用户自己的上一步"]);
  });

  it("子图改的是定义:里面加节点连线、边界上加口并从里面接出来、提升一格控件、收回、删口 —— 一批跨几样仍只一步撤销", async () => {
    const page = await installed();
    const layer = page.subgraph.id;
    const result = await apply(page, [
      { op: "add_node", layer, id: "$p", type: "VAEDecode", widgets: {} },
      { op: "connect", layer, from: { node: "5", name: "LATENT" }, to: { node: "$p", name: "samples" } },
      { op: "add_io", layer, side: "output", name: "LATENT", type: "LATENT" },
      { op: "connect", layer, from: { node: "5", name: "LATENT" }, to: { node: "@out", name: "LATENT" } },
      { op: "promote", layer, node: "5", widget: "cfg", name: "cfg" },
      { op: "connect", layer, from: { node: "@in", name: "cfg" }, to: { node: "5", name: "denoise" } },
      { op: "unpromote", layer, node: "5", widget: "steps" },
    ]);
    expect(result).toEqual({ ok: true, created: { $p: "21" } });
    const sub = page.subgraph;
    expect(sub.getNodeById(21)?.type, "新节点在子图里,不在根图上").toBe("VAEDecode");
    expect(page.root.getNodeById(21)).toBeNull();
    expect(sub.outputs.map((io) => [io.name, io.linkIds.length])).toEqual([["LATENT", 1]]);
    expect(sub.inputs.map((io) => io.name), "steps 收回去了(那个口删掉),cfg 提升出来").toEqual(["cfg"]);
    expect(linkInto(sub, page.innerSampler, "cfg")?.origin_id, "提升 = 边界上的口接到里面那一格").toBe(-10);
    expect(page.innerSampler.inputs.find((one) => one.name === "steps")!.link).toBeNull();
    expect(page.tracker.undoQueue).toHaveLength(1);
  });

  it("子图边界的口:@in / @out 只在子图里;同名的口加两次、不存在的口删不掉都算说不通", async () => {
    const page = await installed();
    const layer = page.subgraph.id;
    const result = await apply(page, [
      { op: "connect", layer: null, from: { node: "@in", name: "steps" }, to: { node: "3", name: "steps" } },
      { op: "add_io", layer, side: "input", name: "steps", type: "INT" },
      { op: "remove_io", layer, side: "output", name: "nope" },
      { op: "promote", layer, node: "5", widget: "steps", name: "steps_1" },
    ]);
    expect((result as { problems: string[] }).problems).toEqual([
      "#1 connect: @in / @out only inside a subgraph",
      "#2 add_io: already has input steps",
      "#3 remove_io: no output nope",
      "#4 promote: steps is already connected",
    ]);
    expect(page.tracker.undoQueue).toEqual([]);
  });

  it("打包、拆开交给前端自己的 convertToSubgraph / unpackSubgraph;打包出来的节点号叫 @subgraph", async () => {
    const page = await installed();
    const packed = await apply(page, [{ op: "to_subgraph", layer: null, nodes: ["3", "8"], name: "采样和解码" }]);
    expect(packed).toEqual({ ok: true, created: { "@subgraph": "21" } });
    //: 那个 Set 是页面里(vm 的另一个 realm)造的:比里面装的是谁
    const items = (page.root.convertToSubgraph as ReturnType<typeof vi.fn>).mock.calls[0][0] as Set<FakeNode>;
    expect([...items]).toEqual([page.sampler, page.decode]);
    const unpacked = await apply(page, [{ op: "unpack", layer: null, node: "12" }]);
    expect(unpacked).toEqual({ ok: true, created: {} });
    expect(page.root.unpackSubgraph).toHaveBeenCalledWith(page.instance);
    expect(await apply(page, [{ op: "unpack", layer: null, node: "4" }])).toEqual({ error: "invalid", problems: ["#1 unpack: node 4 is not a subgraph"] });
  });

  //: PLG-17:后端重读画布、插件对着读到的那份算这一批、再交给桥 —— 中间这一下换到另一张(同一个模板改出来的,节点号一样),此前照改
  it("交给桥之前画布上换了一张(otherWorkflow)、那一张读过之后又改过(changed):一样都不改,撤销里也不留一步", async () => {
    const page = await installed();
    const steps = page.sampler.widgets.find((one) => one.name === "steps")!;
    const ops: WorkbenchEditOp[] = [{ op: "set_widget", layer: null, node: "3", widget: "steps", value: 30 }];
    const read = await here(page);
    page.store.activeWorkflow = { path: "workflows/人像/古风 2.json", filename: "古风 2", isTemporary: false, isModified: false,
                                  changeTracker: page.tracker };
    expect(await call(page, { op: "applyOps", ops, expect: read })).toEqual({ error: "otherWorkflow" });
    page.store.activeWorkflow = page.store.getWorkflowByPath("workflows/人像/古风.json") as Record<string, unknown>;
    const again = await here(page);
    page.tracker.activeState = { nodes: [], links: [], edited: true };
    expect(await call(page, { op: "applyOps", ops, expect: again })).toEqual({ error: "changed" });
    expect(steps.value, "一样都没改").toBe(20);
    expect(page.tracker.beforeChange).not.toHaveBeenCalled();
    expect(page.tracker.undoQueue).toEqual([]);
    expect(await call(page, { op: "applyOps", ops, expect: await here(page) })).toEqual({ ok: true, created: {} });
    expect(steps.value).toBe(30);
  });

  it("这版前端没有改动跟踪的 beforeChange / undo(一批一步撤销做不到):不改,说不支持", async () => {
    const page = editingPage();
    delete (page.tracker as Partial<typeof page.tracker>).beforeChange;
    expect(await page.run(workbenchInstallScript(ORIGIN))).toBe("installed");
    expect(await apply(page, [{ op: "set_widget", layer: null, node: "3", widget: "steps", value: 1 }]))
      .toEqual({ error: "unsupported", message: "applyOps" });
    expect(page.sampler.widgets.find((one) => one.name === "steps")!.value).toBe(20);
  });
});

describe("桥第 5 版:在新标签页开一张", () => {
  const graph = { nodes: [{ id: 4, type: "CheckpointLoaderSimple" }, { id: 3, type: "KSampler" }], links: [] };

  it("开一个临时标签载进那张图,和开着的不重名;**从不存盘**", async () => {
    const page = await installed();
    const result = await call(page, { op: "openWorkflow", graph, name: "Qwen 编辑", path: null, ops: [] });
    expect(result).toEqual({ ok: true, workflow: { path: "workflows/Qwen 编辑 (2).json", name: "Qwen 编辑 (2)", temporary: true } });
    expect(page.loadGraphData).toHaveBeenCalledWith(graph, true, true, "Qwen 编辑 (2)", { checkForRerouteMigration: false });
    expect(page.execute, "不执行保存命令").not.toHaveBeenCalled();
    expect(page.store.activeWorkflow).toMatchObject({ isTemporary: true });
  });

  it("名字里带路径分隔、控制字符的换成空格;没给名字叫 Mosael", async () => {
    const page = await installed();
    expect(await call(page, { op: "openWorkflow", graph, name: "", path: null, ops: [] }))
      .toMatchObject({ workflow: { path: "workflows/Mosael.json" } });
  });

  it("开好再改一批(从节点搭、在模板上改几格):同一套查法,新标签页里只一步撤销;查不过就说清楚,标签页留着原图", async () => {
    const page = await installed();
    const built = await call(page, { op: "openWorkflow", graph, name: "搭的", path: null, ops: [
      { op: "add_node", layer: null, id: "$d", type: "VAEDecode", widgets: {} },
      { op: "connect", layer: null, from: { node: "3", name: "LATENT" }, to: { node: "$d", name: "samples" } },
    ] });
    expect(built).toEqual({ ok: true, workflow: { path: "workflows/搭的.json", name: "搭的", temporary: true }, created: { $d: "21" } });
    expect(page.tracker.undoQueue).toHaveLength(1);
    const canvas = page.app.canvas as { ds: { fitToBounds: ReturnType<typeof vi.fn> } };
    expect(canvas.ds.fitToBounds, "画面移到搭出来的那几个节点上").toHaveBeenCalledTimes(1);
    expect(page.execute).not.toHaveBeenCalled();
    const refused = await call(page, { op: "openWorkflow", graph, name: "又一张", path: null, ops: [
      { op: "connect", layer: null, from: { node: "3", name: "LATENT" }, to: { node: "77", name: "samples" } },
    ] });
    expect(refused).toEqual({ error: "invalid", problems: ["#1 connect: no node 77"],
                              workflow: { path: "workflows/又一张.json", name: "又一张", temporary: true } });
  });

  it("给 path 就打开存着的那一张(和工作流库「在工作台里打开」同一条路);那台机器上没有就说没有", async () => {
    const page = await installed();
    const saved = { path: "workflows/人像/古风.json", isLoaded: false, load: vi.fn(async () => undefined), activeState: graph };
    page.store.getWorkflowByPath = (path: string) => (path === saved.path ? saved : null);
    page.loadGraphData.mockImplementationOnce(async () => {
      page.store.activeWorkflow = { path: saved.path, filename: "古风", isTemporary: false };
      return true;
    });
    expect(await call(page, { op: "openWorkflow", graph: null, name: "", path: "人像/古风.json", ops: [] }))
      .toEqual({ ok: true, workflow: { path: "workflows/人像/古风.json", name: "古风", temporary: false } });
    expect(saved.load).toHaveBeenCalled();
    expect(await call(page, { op: "openWorkflow", graph: null, name: "", path: "没有.json", ops: [] })).toEqual({ error: "noWorkflow" });
  });
});
