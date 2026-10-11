import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// CommonJS is intentional: main.cjs and preload.cjs load this exact runtime contract.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const contract = require("./ipc-contract.cjs") as {
  IPC: {
    invoke: Record<string, string>;
    send: Record<string, string>;
    event: Record<string, string>;
  };
  parsePublishTarget: (value: unknown, channel: string) => { accountId: string; platform: string };
  parseBrowserLogin: (value: unknown) => {
    partition: string;
    url: string;
    name: string;
    proxy: string | null;
    resume: boolean;
  };
  parseBrowserProfile: (value: unknown) => { partition: string };
  parseComfyNavigation: (value: unknown) => { partition: string; mode: string };
  parseComfyWorkbenchOpen: (value: unknown) => { partition: string; url: string; name: string; path: string | null; fresh: boolean };
  parseComfyWorkbenchCall: (value: unknown) => { partition: string; call: Record<string, unknown> };
  parsePanelLayout: (value: unknown) => Record<string, number | string>;
  parsePanelMuted: (value: unknown) => { id: string; muted: boolean };
  parseAuthToken: (value: unknown, channel: string) => { token: string };
  parseRestoreStage: (value: unknown) => { stageId: string };
  parseLocale: (value: unknown) => { locale: string };
  parseCaptureMode: (value: unknown) => { mode: string };
  parseRegionSelection: (value: unknown) => { selection: Record<string, number> | null };
  parseImageUrls: (value: unknown) => { urls: string[] };
  parseReadMode: (value: unknown) => { mode: string };
  parseToolsInset: (value: unknown) => { right: number };
  parseSaveDownload: (value: unknown) => Record<string, string | null>;
  parsePageId: (value: unknown, channel: string) => { id: string };
  parsePageOrder: (value: unknown) => { ids: string[] };
  parseNewPage: (value: unknown) => { url: string };
  parsePagesInset: (value: unknown) => { left: number };
  parseCoverPage: (value: unknown) => { covered: boolean };
  parseOverlay: (value: unknown) => { up: boolean };
  parseFloatShow: (value: unknown) => {
    id: string;
    html: string;
    rect: { x: number; y: number; width: number; height: number };
    root: { className: string; style: string; attributes: Record<string, string> };
  };
  parseFloatHide: (value: unknown) => { id: string | null };
  parseToastsShow: (value: unknown) => {
    html: string;
    rect: { x: number; y: number; width: number; height: number };
    root: { className: string; style: string; attributes: Record<string, string> };
  };
};

const ROOT = path.resolve(__dirname);

describe("Electron IPC contract", () => {
  it("assigns every channel one name and one direction", () => {
    const channels = Object.values(contract.IPC).flatMap((group) => Object.values(group));

    expect(new Set(channels).size).toBe(channels.length);
    expect(channels).toContain("recording-permissions:request");
    expect(channels).toContain("publish:panels");
    expect(channels).toContain("data:exportDiagnostics");
    expect(channels).toContain("data:createBackup");
    expect(channels).toContain("data:applyRestore");
    expect(channels).not.toContain("publish:exit");
  });

  it("keeps raw IPC names out of process-boundary product code", () => {
    const files = [
      "main.cjs",
      "preload.cjs",
      "system/customCss.ts",
      "system/notify.ts",
      "system/protocol.ts",
    ];
    const rawCall = /(?:ipcMain\.(?:handle|on)|ipcRenderer\.(?:invoke|send|on)|webContents\.send)\(\s*["']/;

    for (const file of files) {
      expect(fs.readFileSync(path.join(ROOT, file), "utf8"), file).not.toMatch(rawCall);
    }
  });

  it("rejects malformed publish identity payloads before handlers see them", () => {
    expect(contract.parsePublishTarget({ accountId: " account ", platform: " youtube " }, "publish:login"))
      .toEqual({ accountId: "account", platform: "youtube" });
    expect(() => contract.parsePublishTarget({ accountId: "", platform: "youtube" }, "publish:login"))
      .toThrow(/accountId/);
    expect(() => contract.parsePublishTarget(null, "publish:login")).toThrow(/publish:login/);
  });

  it("validates browser-login and panel-layout payloads", () => {
    expect(contract.parseBrowserLogin({
      partition: "persist:pool-user",
      url: "https://example.com/login",
      name: " Example ",
    })).toEqual({
      partition: "persist:pool-user",
      url: "https://example.com/login",
      name: "Example",
      proxy: null,
      resume: false,
    });
    expect(() => contract.parseBrowserLogin({ partition: "persist:publish-user", url: "https://example.com" }))
      .toThrow(/partition/);
    expect(() => contract.parseBrowserLogin({ partition: "persist:pool-user", url: "file:\/\/\/tmp/x" }))
      .toThrow(/http/);

    // 清登录数据是破坏性的:只许碰通用档案的分区,发布账号走 publish:signOut。
    expect(contract.parseBrowserProfile({ partition: "persist:pool-user" })).toEqual({ partition: "persist:pool-user" });
    expect(() => contract.parseBrowserProfile({ partition: "persist:mosael-account" })).toThrow(/partition/);

    // 操控方式:分区照样由契约按连接 id 拼;只认两种方式,不收别的字段(比如一个设置键、一段脚本)。
    expect(contract.parseComfyNavigation({ connectionId: "c1", mode: "trackpad" }))
      .toEqual({ partition: "persist:pool-comfyui-c1", mode: "trackpad" });
    expect(contract.parseComfyNavigation({ connectionId: "c1", mode: "mouse" }).mode).toBe("mouse");
    expect(() => contract.parseComfyNavigation({ connectionId: "c1", mode: "standard" })).toThrow(/mode/);
    expect(() => contract.parseComfyNavigation({ connectionId: "c1", mode: "mouse", key: "Comfy.X" })).toThrow(/unexpected/);
    expect(() => contract.parseComfyNavigation({ connectionId: "../c1", mode: "mouse" })).toThrow(/connectionId/);

    // 工作台:开(工作流库里打开一张、「新建」都走这里)。分区由契约按连接 id 拼 —— 渲染层点不了别的分区(发布账号、
    // 别的档案);路径和宿主同一套规矩;新建和打开一张只能选一样;多一个字段(比如想塞一段脚本、点名一个分区)就拒。
    expect(contract.parseComfyWorkbenchOpen({
      connectionId: "c0ffee-1",
      url: "http://192.168.3.15:8188",
      name: " 我的 ComfyUI ",
      path: "人像/古风 女孩.json",
    })).toEqual({
      partition: "persist:pool-comfyui-c0ffee-1",
      url: "http://192.168.3.15:8188",
      name: "我的 ComfyUI",
      path: "人像/古风 女孩.json",
      fresh: false,
    });
    const bench = { connectionId: "c1", url: "http://127.0.0.1:8188", name: "本机" };
    expect(contract.parseComfyWorkbenchOpen(bench)).toEqual({ partition: "persist:pool-comfyui-c1", url: bench.url, name: "本机",
                                                              path: null, fresh: false });
    expect(contract.parseComfyWorkbenchOpen({ ...bench, path: "人像/a.json" }).path).toBe("人像/a.json");
    expect(contract.parseComfyWorkbenchOpen({ ...bench, fresh: true }).fresh).toBe(true);
    for (const path of ["../a.json", "/a.json", "a\\b.json", "a", ".hidden/a.json", "a/.b.json", "a\nb.json", "a//b.json"]) {
      expect(() => contract.parseComfyWorkbenchOpen({ ...bench, path }), path).toThrow(/path/);
    }
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, path: 42 })).toThrow(/path/);
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, path: "a.json", fresh: true })).toThrow(/exclusive/);
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, fresh: "yes" })).toThrow(/fresh/);
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, partition: "persist:mosael-x" })).toThrow(/unexpected/);
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, script: "alert(1)" })).toThrow(/unexpected/);
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, connectionId: "../x" })).toThrow(/connectionId/);
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, connectionId: "a b" })).toThrow(/connectionId/);
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, url: "file:\/\/\/tmp/x" })).toThrow(/http/);
    expect(() => contract.parseComfyWorkbenchOpen({ ...bench, url: "javascript:alert(1)" })).toThrow(/http/);

    // 工作台:面板要桥做的事 —— 只认这几种,每种逐项校验;渲染层送不进代码、点不了别的分区。
    const callOf = (call: unknown) => contract.parseComfyWorkbenchCall({ connectionId: "c1", call });
    expect(callOf({ op: "setWidget", node: "4", widget: "ckpt_name", value: "sdxl.safetensors" })).toEqual({
      partition: "persist:pool-comfyui-c1", call: { op: "setWidget", node: "4", widget: "ckpt_name", value: "sdxl.safetensors" },
    });
    expect(callOf({ op: "setWidget", node: "-3", widget: "steps", value: 30 }).call.value).toBe(30);
    for (const op of ["refreshCombos", "export", "save"]) expect(callOf({ op })).toEqual({ partition: "persist:pool-comfyui-c1", call: { op } });
    expect(() => callOf({ op: "poll" }), "轮询是主进程自己的").toThrow(/op/);
    expect(() => callOf({ op: "eval", code: "alert(1)" })).toThrow(/op/);
    expect(() => callOf({ op: "save", script: "alert(1)" })).toThrow(/unexpected/);
    expect(() => callOf({ op: "setWidget", node: "4; alert(1)", widget: "w", value: 1 })).toThrow(/node/);
    expect(() => callOf({ op: "setWidget", node: "4", widget: "a\nb", value: 1 })).toThrow(/widget/);
    expect(() => callOf({ op: "setWidget", node: "4", widget: "w", value: { toString: "x" } })).toThrow(/value/);
    expect(() => callOf({ op: "setWidget", node: "4", widget: "w", value: Number.NaN })).toThrow(/value/);
    expect(() => callOf({ op: "setWidget", node: "4", widget: "w", value: "x".repeat(4001) })).toThrow(/value/);
    const marks = { nodes: { "4": { expose: { ckpt_name: { order: 0 } } } }, extra: { version: 1 } };
    const expect_ = { key: "workflows/人像/古风.json", revision: 3 };
    expect(callOf({ op: "setMarks", marks, expect: expect_ }).call).toEqual({ op: "setMarks", marks, expect: expect_ });
    expect(callOf({ op: "setMarks", marks: { nodes: {}, extra: null }, expect: expect_ }).call)
      .toEqual({ op: "setMarks", marks: { nodes: {}, extra: null }, expect: expect_ });
    expect(() => callOf({ op: "setMarks", marks: { nodes: { "12:5": {} }, extra: null }, expect: expect_ }), "只认根图上的节点").toThrow(/top-level/);
    expect(() => callOf({ op: "setMarks", marks: { nodes: { "4": "x" }, extra: null }, expect: expect_ })).toThrow(/object/);
    expect(() => callOf({ op: "setMarks", marks: { nodes: {}, extra: null, more: 1 }, expect: expect_ })).toThrow(/unexpected/);
    // PLG-17:写进画布的两样都得说写给哪一张(桥在页面里比);不说就不写
    expect(() => callOf({ op: "setMarks", marks }), "不说写给哪一张").toThrow(/object/);
    expect(() => callOf({ op: "setMarks", marks, expect: { key: "", revision: 1 } })).toThrow(/expect.key/);
    expect(() => callOf({ op: "setMarks", marks, expect: { key: "a\nb", revision: 1 } })).toThrow(/expect.key/);
    expect(() => callOf({ op: "setMarks", marks, expect: { key: "k", revision: -1 } })).toThrow(/expect.revision/);
    expect(() => callOf({ op: "setMarks", marks, expect: { key: "k", revision: 1.5 } })).toThrow(/expect.revision/);
    expect(() => callOf({ op: "setMarks", marks, expect: { ...expect_, path: "x" } })).toThrow(/unexpected/);
    expect(callOf({ op: "locate", node: "12" }).call, "根图上的节点").toEqual({ op: "locate", node: "12", subgraph: null });
    expect(callOf({ op: "locate", node: "-3", subgraph: "8f1c0e2a-9b7d-4c51" }).call)
      .toEqual({ op: "locate", node: "-3", subgraph: "8f1c0e2a-9b7d-4c51" });
    expect(() => callOf({ op: "locate", node: "12; alert(1)" })).toThrow(/node/);
    expect(() => callOf({ op: "locate", node: "12", subgraph: 'x"); alert(1)' })).toThrow(/subgraph/);
    expect(() => callOf({ op: "locate", node: "12", zoom: 3 })).toThrow(/unexpected/);
    // 智能体指节点的写法(ADR 0042):从根图往里走的路径,桥一层层打开子图;和子图 id 一起给就只认那一层里的编号
    expect(callOf({ op: "locate", node: "12:5" }).call).toEqual({ op: "locate", node: "12:5", subgraph: null });
    expect(callOf({ op: "locate", node: "459:12:5", subgraph: null }).call.node).toBe("459:12:5");
    expect(() => callOf({ op: "locate", node: "12:5", subgraph: "8f1c0e2a" }), "路径和子图 id 不能一起给").toThrow(/node/);
    expect(() => callOf({ op: "locate", node: "12:" })).toThrow(/node/);
    expect(() => callOf({ op: "locate", node: "12:-5" }), "子图里没有负的编号").toThrow(/node/);
    expect(() => callOf({ op: "locate", node: Array.from({ length: 18 }, () => "1").join(":") }), "最多 16 层").toThrow(/node/);
    expect(() => callOf({ op: "locate", node: 12 })).toThrow(/node/);
    expect(callOf({ op: "readGraph" })).toEqual({ partition: "persist:pool-comfyui-c1", call: { op: "readGraph" } });
    expect(() => callOf({ op: "readGraph", depth: 2 })).toThrow(/unexpected/);
    expect(callOf({ op: "runControls", phase: "before" }).call).toEqual({ op: "runControls", phase: "before" });
    expect(callOf({ op: "runControls", phase: "after" }).call).toEqual({ op: "runControls", phase: "after" });
    expect(() => callOf({ op: "runControls", phase: "during" })).toThrow(/phase/);
    expect(() => callOf({ op: "runControls" })).toThrow(/phase/);
    expect(() => callOf({ op: "runControls", phase: "after", hook: "alert(1)" })).toThrow(/unexpected/);
    expect(() => contract.parseComfyWorkbenchCall({ connectionId: "../x", call: { op: "save" } })).toThrow(/connectionId/);

    // 智能体改图(ADR 0042 第二步):插件规整过的一批,每一种只认那几个字段;节点是编号或临时名字,值只收标量
    const sub = "8f1c0e2a-9b7d-4c51";
    const ops = [
      { op: "add_node", layer: null, id: "$l", type: "LoraLoader", widgets: { strength_model: 0.6 }, near: "4" },
      { op: "connect", layer: null, from: { node: "4", name: "MODEL" }, to: { node: "$l", name: "model" } },
      { op: "connect", layer: sub, from: { node: "@in", name: "seed" }, to: { node: "5", name: "seed" } },
      { op: "disconnect", layer: sub, to: { node: "@out", name: "IMAGE" } },
      { op: "set_widget", layer: null, node: "3", widget: "steps", value: 30 },
      { op: "set_title", layer: null, node: "3", title: "采样" },
      { op: "set_position", layer: null, node: "3", x: 240.5, y: -80 },
      { op: "set_group", layer: null, group: "g1", title: "采样", x: 200, y: -100, width: 600, height: 400, color: "#2457AA" },
      { op: "add_group", layer: sub, title: "输出", x: 900, y: 0, width: 300, height: 200, color: "#3f789e" },
      { op: "remove_group", layer: sub, group: "g2" },
      { op: "mode", layer: null, node: "8", mode: 4 },
      { op: "add_io", layer: sub, side: "output", name: "LATENT", type: "LATENT" },
      { op: "remove_io", layer: sub, side: "input", name: "negative" },
      { op: "promote", layer: sub, node: "5", widget: "cfg", name: "cfg" },
      { op: "unpromote", layer: sub, node: "5", widget: "steps" },
      { op: "to_subgraph", layer: null, nodes: ["3", "8"], name: "采样" },
      { op: "unpack", layer: null, node: "12" },
    ];
    expect(callOf({ op: "applyOps", ops, expect: expect_ }).call).toEqual({ op: "applyOps", ops, expect: expect_ });
    expect(callOf({ op: "applyOps", ops: [{ op: "remove_node", node: "7" }], expect: expect_ }).call.ops, "不给 layer 就是根图")
      .toEqual([{ op: "remove_node", layer: null, node: "7" }]);
    expect(() => callOf({ op: "applyOps", ops }), "不说改给哪一张").toThrow(/object/);
    expect(() => callOf({ op: "applyOps", ops: [] })).toThrow(/empty/);
    expect(() => callOf({ op: "applyOps", ops: Array.from({ length: 201 }, () => ops[4]) })).toThrow(/at most/);
    expect(() => callOf({ op: "applyOps", ops: [{ op: "eval", layer: null }] })).toThrow(/op/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[4], script: "alert(1)" }] })).toThrow(/unexpected/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[4], node: "3; alert(1)" }] })).toThrow(/node/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[4], value: { evil: true } }] })).toThrow(/value/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[4], layer: 'x"); alert(1)' }] })).toThrow(/layer/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[0], id: "l" }] }), "临时名字以 $ 开头").toThrow(/temporary/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[1], to: { node: "$l", name: "model", slot: 0 } }] })).toThrow(/unexpected/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[10], mode: 1 }] })).toThrow(/mode/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[7], group: "1" }] })).toThrow(/group/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[7], width: 0 }] })).toThrow(/width/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[7], color: "blue" }] })).toThrow(/color/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[11], side: "both" }] })).toThrow(/side/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[6], x: Number.NaN }] })).toThrow(/coordinate/);
    expect(() => callOf({ op: "applyOps", ops: [{ ...ops[6], y: 1_000_001 }] })).toThrow(/coordinate/);
    // 在新标签页开一张:整图 + 名字(+ 一批改动),或者存着的那一张的路径
    const graph = { nodes: [{ id: 3, type: "KSampler" }], links: [] };
    expect(callOf({ op: "openWorkflow", graph, name: "Qwen 编辑" }).call)
      .toEqual({ op: "openWorkflow", graph, name: "Qwen 编辑", path: null, ops: [] });
    expect(callOf({ op: "openWorkflow", graph, name: "搭的", ops: [ops[4]] }).call.ops).toEqual([ops[4]]);
    expect(callOf({ op: "openWorkflow", path: "人像/古风.json" }).call)
      .toEqual({ op: "openWorkflow", graph: null, name: "", path: "人像/古风.json", ops: [] });
    expect(() => callOf({ op: "openWorkflow", graph, path: "a.json" }), "两样只能给一样").toThrow(/either/);
    expect(() => callOf({ op: "openWorkflow", name: "x" })).toThrow(/either/);
    expect(() => callOf({ op: "openWorkflow", graph: { links: [] } })).toThrow(/UI workflow/);
    expect(() => callOf({ op: "openWorkflow", graph, name: "../escape" })).toThrow(/separator/);
    expect(() => callOf({ op: "openWorkflow", path: "../x.json" })).toThrow(/path/);
    expect(() => callOf({ op: "openWorkflow", path: "a.json", ops: [ops[4]] }), "存着的那一张不在这里改").toThrow(/ops/);
    expect(() => callOf({ op: "openWorkflow", graph, save: true })).toThrow(/unexpected/);
    expect(callOf({ op: "openWorkflow", path: "a.json", openedBy: "0f3c9a2b7d4e4c51a3e8b6d2c1f0e9a7" }).call.openedBy,
           "是哪段对话开的(ADR 0044 §6)").toBe("0f3c9a2b7d4e4c51a3e8b6d2c1f0e9a7");
    expect(callOf({ op: "openWorkflow", path: "a.json" }).call, "不是智能体开的就没有这一项").not.toHaveProperty("openedBy");
    for (const openedBy of ["", "a b", 'x"; alert(1)', "x".repeat(65), 7]) {
      expect(() => callOf({ op: "openWorkflow", path: "a.json", openedBy }), String(openedBy)).toThrow(/openedBy/);
    }

    // 挪位置:只有 x/y。
    expect(contract.parsePanelLayout({ x: 10, y: 20 })).toEqual({ x: 10, y: 20 });
    // 认不出的字段一律拒收,不能「半懂地执行」:开发时渲染层热更新、主进程不重启,两边常常不是同一版。
    // 旧版解析器悄悄丢掉了新字段 handle,把缩放当成「挪到这里 + 改宽」,拖角时整张卡片跟着平移。
    expect(() => contract.parsePanelLayout({ x: 10, y: 20, width: 300 })).toThrow(/width/);
    expect(() => contract.parsePanelLayout({ handle: "se", x: 1, y: 2, width: 3, height: 4, anchor: "nw" }))
      .toThrow(/anchor/);
    expect(() => contract.parsePanelLayout({ x: 10 })).toThrow(/y/);
    // 缩放:手柄 + 指针要的整块矩形,缺一不可。
    expect(contract.parsePanelLayout({ handle: "nw", x: 1, y: 2, width: 300, height: 200 }))
      .toEqual({ handle: "nw", x: 1, y: 2, width: 300, height: 200 });
    expect(() => contract.parsePanelLayout({ handle: "se", x: 1, y: 2, width: Number.NaN, height: 200 }))
      .toThrow(/width/);
    expect(() => contract.parsePanelLayout({ handle: "se", x: 1, y: 2, width: 300 })).toThrow(/height/);
    expect(() => contract.parsePanelLayout({ handle: "middle", x: 1, y: 2, width: 300, height: 200 }))
      .toThrow(/handle/);
    expect(contract.parsePanelMuted({ id: " browser-1 ", muted: false })).toEqual({ id: "browser-1", muted: false });
    expect(() => contract.parsePanelMuted({ id: "browser-1", muted: "false" })).toThrow(/muted/);
  });

  it("accepts only a bounded authentication token for privileged data IPC", () => {
    expect(contract.parseAuthToken({ token: " bearer-token " }, "data:createBackup"))
      .toEqual({ token: "bearer-token" });
    expect(() => contract.parseAuthToken({ token: "" }, "data:createBackup")).toThrow(/token/);
    expect(() => contract.parseAuthToken({ token: "x".repeat(16_385) }, "data:createBackup"))
      .toThrow(/token/);
  });

  it("accepts only opaque restore stage identifiers", () => {
    expect(contract.parseRestoreStage({ stageId: "a".repeat(32) })).toEqual({ stageId: "a".repeat(32) });
    expect(() => contract.parseRestoreStage({ stageId: "../live" })).toThrow(/stageId/);
  });

  it("accepts only a language tag as the interface locale", () => {
    expect(contract.parseLocale({ locale: " en-US " })).toEqual({ locale: "en-US" });
    expect(contract.parseLocale({ locale: "zh-Hant-TW" })).toEqual({ locale: "zh-Hant-TW" });
    expect(() => contract.parseLocale({ locale: "" })).toThrow(/locale/);
    expect(() => contract.parseLocale({ locale: "en US; rm -rf" })).toThrow(/locale/);
    expect(() => contract.parseLocale("en")).toThrow(/mosael:locale/);
  });

  it("validates page-tool payloads before handlers see them: closed option lists, bounded values, no unexpected fields", () => {
    expect(contract.parseCaptureMode({ mode: "full" })).toEqual({ mode: "full" });
    expect(() => contract.parseCaptureMode({ mode: "region" })).toThrow(/mode/);
    expect(() => contract.parseCaptureMode({ mode: "visible", target: "pool-other" })).toThrow(/unexpected field target/);

    expect(contract.parseRegionSelection({ selection: null })).toEqual({ selection: null });
    expect(contract.parseRegionSelection({ selection: { x: 0.1, y: 0.2, width: 0.5, height: 0.3 } })).toEqual({
      selection: { x: 0.1, y: 0.2, width: 0.5, height: 0.3 },
    });
    expect(() => contract.parseRegionSelection({ selection: { x: 0.8, y: 0, width: 0.5, height: 0.5 } })).toThrow(/inside the frame/);
    expect(() => contract.parseRegionSelection({ selection: { x: -1, y: 0, width: 0.5, height: 0.5 } })).toThrow(/selection.x/);
    expect(() => contract.parseRegionSelection({ selection: { x: 0, y: 0, width: 400, height: 300 } })).toThrow(/selection.width/);

    expect(contract.parseImageUrls({ urls: ["https://example.com/a.png"] })).toEqual({ urls: ["https://example.com/a.png"] });
    expect(() => contract.parseImageUrls({ urls: [] })).toThrow(/urls/);
    expect(() => contract.parseImageUrls({ urls: ["file:///etc/passwd"] })).toThrow(/http/);
    expect(() => contract.parseImageUrls({ urls: Array.from({ length: 121 }, (_, i) => `https://e.com/${i}.png`) })).toThrow(/urls/);

    expect(contract.parseReadMode({ mode: "selection" })).toEqual({ mode: "selection" });
    expect(() => contract.parseReadMode({ mode: "html" })).toThrow(/mode/);

    expect(contract.parseToolsInset({ right: 360 })).toEqual({ right: 360 });
    expect(() => contract.parseToolsInset({ right: -1 })).toThrow(/right/);
    expect(() => contract.parseToolsInset({ right: Number.NaN })).toThrow(/right/);
  });

  it("decodes the page list's requests: page ids are the main process's numbers, the order is a list of them", () => {
    expect(contract.parsePageId({ id: "42" }, "publish:switchPage")).toEqual({ id: "42" });
    expect(() => contract.parsePageId({ id: "../x" }, "publish:switchPage")).toThrow(/page id/);
    expect(() => contract.parsePageId({ id: "1", accountId: "x" }, "publish:switchPage")).toThrow(/unexpected field accountId/);
    expect(contract.parsePageOrder({ ids: ["3", "1", "2"] })).toEqual({ ids: ["3", "1", "2"] });
    expect(() => contract.parsePageOrder({ ids: [] })).toThrow(/ids/);
    expect(() => contract.parsePageOrder({ ids: [1, 2] })).toThrow(/page id/);
    expect(contract.parseNewPage({ url: "bilibili.com" })).toEqual({ url: "bilibili.com" });
    expect(() => contract.parseNewPage({ url: "" })).toThrow(/url/);
    expect(contract.parsePagesInset({ left: 220 })).toEqual({ left: 220 });
    expect(() => contract.parsePagesInset({ left: -1 })).toThrow(/left/);
    expect(contract.parseOverlay({ up: true })).toEqual({ up: true });
    expect(() => contract.parseOverlay({ up: 1 })).toThrow(/up/);
    expect(() => contract.parseOverlay({ up: false, x: 0 })).toThrow(/unexpected field x/);
    expect(contract.parseCoverPage({ covered: true })).toEqual({ covered: true });
    expect(() => contract.parseCoverPage({ covered: "yes" })).toThrow(/covered/);
    expect(() => contract.parseCoverPage({ covered: false, left: 1 })).toThrow(/unexpected field left/);
  });

  it("decodes a hint for the float layer: bounded markup and rectangle, only theme-ish attributes of the root", () => {
    const hint = {
      id: "hint-1",
      html: '<div data-tooltip="">截屏</div>',
      rect: { x: 900, y: 60, width: 140, height: 40 },
      root: { className: "dark", style: "--font-sans: Inter", attributes: { "data-theme": "dark", lang: "zh-CN" } },
    };
    expect(contract.parseFloatShow(hint)).toEqual(hint);
    expect(() => contract.parseFloatShow({ ...hint, html: "x".repeat(70_000) })).toThrow(/html/);
    expect(() => contract.parseFloatShow({ ...hint, rect: { ...hint.rect, width: Number.NaN } })).toThrow(/rect/);
    expect(() => contract.parseFloatShow({ ...hint, rect: { ...hint.rect, height: 50_000 } })).toThrow(/rect/);
    expect(() => contract.parseFloatShow({ ...hint, root: { ...hint.root, attributes: { onclick: "x" } } })).toThrow(/attribute/);
    expect(() => contract.parseFloatShow({ ...hint, extra: 1 })).toThrow(/unexpected field extra/);
    expect(contract.parseFloatHide({ id: "hint-1" })).toEqual({ id: "hint-1" });
    expect(contract.parseFloatHide({})).toEqual({ id: null });
  });

  it("decodes the toasts drawn over a native view (ADR 0051): same bounds as a hint, room for a stack of toasts, no id", () => {
    const toasts = {
      html: "<section><ol data-sonner-toaster></ol></section>",
      rect: { x: 1040, y: 760, width: 400, height: 140 },
      root: { className: "dark", style: "", attributes: { "data-theme": "dark" } },
    };
    expect(contract.parseToastsShow(toasts)).toEqual(toasts);
    expect(contract.parseToastsShow({ ...toasts, html: "x".repeat(200_000) }).html).toHaveLength(200_000);
    expect(() => contract.parseToastsShow({ ...toasts, html: "x".repeat(300_000) })).toThrow(/toasts:show.*html/);
    expect(() => contract.parseToastsShow({ ...toasts, rect: { ...toasts.rect, x: Number.POSITIVE_INFINITY } })).toThrow(/toasts:show.*rect/);
    expect(() => contract.parseToastsShow({ ...toasts, root: { ...toasts.root, attributes: { onload: "x" } } })).toThrow(/attribute/);
    expect(() => contract.parseToastsShow({ ...toasts, id: "toasts" })).toThrow(/unexpected field id/);
  });

  it("decodes saving a finished download: an http(s) server, a token, a workspace, nothing else", () => {
    const request = {
      id: "0f8fad5b-d9cb-469f-a165-70867728950e",
      server: "http://127.0.0.1:8800",
      token: "tok",
      workspaceId: "ws1",
      projectId: null,
    };
    expect(contract.parseSaveDownload(request)).toEqual(request);
    expect(contract.parseSaveDownload({ ...request, projectId: "p1" }).projectId).toBe("p1");
    expect(() => contract.parseSaveDownload({ ...request, id: "../etc" })).toThrow(/id/);
    expect(() => contract.parseSaveDownload({ ...request, server: "file:///tmp" })).toThrow(/server/);
    expect(() => contract.parseSaveDownload({ ...request, token: "" })).toThrow(/token/);
    expect(() => contract.parseSaveDownload({ ...request, token: "x".repeat(20_000) })).toThrow(/token/);
    expect(() => contract.parseSaveDownload({ ...request, path: "/etc/passwd" })).toThrow(/unexpected field path/);
  });
});
