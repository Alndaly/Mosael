import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

//: 官网社区「无限画布浏览」的验收契约。
//:
//: 详情页此前只有一张静态 SVG 缩略图 —— 看得见结构,但没法平移、缩放、凑近看。
//: 这里把「真正可浏览的无限画布」钉住:
//:
//: ① `toFlowGraph(kind, payload)` 把 payload 变成 xyflow 的 nodes / edges,几何和
//:    `buildSharePreview` 是**同一份**(同一份解析、同一个 200 上限),不是第二套;
//: ② 超过 200 个只画前 200 个,`total` / `hidden` 说清还剩多少,指向没画节点的边丢掉;
//: ③ `share-canvas.tsx` 是 client component,用 `@xyflow/react`,只读(不可拖、不可连)、
//:    打开就 fitView、有平移缩放和最小/最大缩放;
//: ④ 详情页在静态预览旁边给出「在画布里看」入口,只把最小 nodes/edges 传给 client,
//:    插件(没有坐标)没有这个入口;
//: ⑤ 关掉后焦点回触发按钮,Esc 走原生 `<dialog>` 的 cancel。
//:
//: 工作流 fixture 用仓库里真实的一份工程文件(`public/workflows/account_analysis.*`),
//: 29 个节点 / 43 条边就是那份文件的真实数字。
const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");

const CANVAS_COMPONENT = "src/components/community/share-canvas.tsx";
const PREVIEW_COMPONENT = "src/components/community/share-preview.tsx";
const MODEL = "src/components/community/share-preview-model.ts";
const DETAIL_PAGE = "src/app/[locale]/(site)/community/[id]/page.tsx";
const WORKFLOW_FIXTURE = "public/workflows/account_analysis.en.mosael-workflow.json";

const { buildSharePreview, toFlowGraph } = await import("../src/components/community/share-preview-model.ts");

const workflowPayload = JSON.parse(read(WORKFLOW_FIXTURE));

/** 画布 fixture:字段形状照 `frontend/src/api/domains/boards.ts` 的 BoardCanvas / BoardItem / BoardEdge。 */
const BOARD_FIXTURE = {
  items: [
    { id: "a", kind: "note", title: "开场", x: 0, y: 0, width: 220, height: 140 },
    // 没写宽高:要按该 kind 的默认尺寸补(frontend 的 DEFAULT_SIZE)。
    { id: "b", kind: "image", x: 320, y: 40 },
    { id: "c", kind: "video", x: 60, y: 260, width: 320, height: 200 },
    { id: "d", kind: "audio", x: 420, y: 300 },
  ],
  edges: [
    { id: "e1", source: "a", target: "b" },
    { id: "e2", source: "b", target: "c" },
    { id: "e3", source: "c", target: "d" },
  ],
  markers: [{ id: "m1", name: "Intro", x: 10, y: 10 }],
};

test("① 工作流 fixture → 29 个节点 / 43 条边,坐标与 source/target 来自 payload", () => {
  const graph = toFlowGraph("workflow", workflowPayload);
  assert.ok(graph, "真实工作流 fixture 没有生成画布图");
  assert.equal(graph.kind, "workflow");
  assert.equal(graph.nodes.length, 29, "节点数不对");
  assert.equal(graph.nodes.length, workflowPayload.graph.nodes.length);
  assert.equal(graph.edges.length, 43, "边数不对");
  assert.equal(graph.edges.length, workflowPayload.graph.edges.length);
  assert.equal(graph.total, 29);
  assert.equal(graph.hidden, 0);

  // 坐标就是 payload 里的 position;尺寸是工作流节点的默认框。
  const first = graph.nodes[0];
  const payloadNode = workflowPayload.graph.nodes[0];
  assert.equal(first.id, payloadNode.id);
  assert.deepEqual(first.position, { x: payloadNode.position.x, y: payloadNode.position.y });
  assert.equal(first.type, "share", "没有走自定义节点类型(会用默认方块)");
  assert.ok(first.width > 0 && first.height > 0, "节点没有尺寸,fitView 算不出来");
  assert.equal(first.data.label, payloadNode.name, "节点没有名字");
  assert.equal(typeof first.data.kind, "string");

  // 边用 payload 的 source / target,且两端都真的画了。
  const ids = new Set(graph.nodes.map((node) => node.id));
  for (const edge of graph.edges) {
    assert.ok(edge.id, "边没有 id");
    assert.ok(ids.has(edge.source), `边的 source 不在节点里:${edge.source}`);
    assert.ok(ids.has(edge.target), `边的 target 不在节点里:${edge.target}`);
  }
  const payloadEdge = workflowPayload.graph.edges[0];
  const firstEdge = graph.edges[0];
  assert.equal(firstEdge.source, payloadEdge.source);
  assert.equal(firstEdge.target, payloadEdge.target);

  // 同类同色:tint 只看 kind(和 SVG 预览同一套)。
  const seen = new Map();
  for (const node of graph.nodes) {
    if (seen.has(node.data.kind)) assert.equal(node.data.tint, seen.get(node.data.kind));
    else seen.set(node.data.kind, node.data.tint);
  }
});

test("① 画布 fixture(裸的与工程文件两种形状)→ 节点 / 边 / 默认宽高", () => {
  const graph = toFlowGraph("board", BOARD_FIXTURE);
  assert.ok(graph, "画布 fixture 没有生成画布图");
  assert.equal(graph.kind, "board");
  assert.equal(graph.nodes.length, 4, "格子数不对");
  assert.equal(graph.edges.length, 3, "连线数不对");
  assert.deepEqual(graph.nodes[0].position, { x: 0, y: 0 });
  assert.deepEqual({ width: graph.nodes[0].width, height: graph.nodes[0].height }, { width: 220, height: 140 });
  // 宽高缺省:image 默认 260×180。
  assert.deepEqual(
    { x: graph.nodes[1].position.x, y: graph.nodes[1].position.y, width: graph.nodes[1].width, height: graph.nodes[1].height },
    { x: 320, y: 40, width: 260, height: 180 },
  );
  assert.equal(graph.nodes[0].data.kind, "note");
  // 画布 kinds 用不同淡色。
  assert.notEqual(graph.nodes[0].data.tint, graph.nodes[1].data.tint, "note 和 image 用了同一个淡色");
  // 画布格子的名字:payload 里有 title 就显示 title。
  assert.equal(graph.nodes[0].data.label, "开场");

  // 真实上传的是画板工程文件,items/edges 在 canvas 里。
  const fromFile = toFlowGraph("board", {
    format: "mosael.board",
    version: 1,
    name: "demo",
    canvas: BOARD_FIXTURE,
  });
  assert.ok(fromFile, "画板工程文件没有生成画布图");
  assert.equal(fromFile.nodes.length, 4);
  assert.equal(fromFile.edges.length, 3);

  // 不改已有行为:SVG 预览依旧不给画布格子画标签(它负责结构,名字交给画布)。
  const preview = buildSharePreview("board", BOARD_FIXTURE);
  assert.equal(preview.rects[0].label, null, "SVG 预览的画布标签行为被改了");
});

test("② 200 上限:只画前 200 个,total/hidden 正确,指向没画节点的边丢掉", () => {
  const nodes = Array.from({ length: 205 }, (_, index) => ({
    id: `n${index}`,
    type: "llm",
    name: `Node ${index}`,
    position: { x: index * 300, y: (index % 3) * 200 },
  }));
  const workflow = toFlowGraph("workflow", {
    graph: {
      nodes,
      edges: [
        { id: "keep", source: "n1", target: "n2" },
        { id: "drop", source: "n1", target: "n204" },
      ],
    },
  });
  assert.ok(workflow);
  assert.equal(workflow.nodes.length, 200, "没有卡在 200 个节点");
  assert.equal(workflow.total, 205);
  assert.equal(workflow.hidden, 5, "没算出还有几个节点没画");
  assert.deepEqual(
    workflow.edges.map((edge) => edge.id),
    ["keep"],
    "指向没画节点的边没有丢掉",
  );

  const board = toFlowGraph("board", {
    items: Array.from({ length: 201 }, (_, index) => ({ id: `i${index}`, kind: "note", x: index * 10, y: 0 })),
    edges: [],
  });
  assert.ok(board);
  assert.equal(board.nodes.length, 200, "没有卡在 200 个格子");
  assert.equal(board.hidden, 1);

  // 和 SVG 预览同一个上限常量。
  const model = read(MODEL);
  assert.match(model, /PREVIEW_LIMIT/);
  assert.match(model, /export function toFlowGraph/);
});

test("② 空内容 / 插件 / 未知 kind / 拿反形状 → null", () => {
  assert.equal(toFlowGraph("workflow", { graph: { nodes: [], edges: [] } }), null);
  assert.equal(toFlowGraph("board", { items: [], edges: [] }), null);
  assert.equal(toFlowGraph("workflow", BOARD_FIXTURE), null, "画布形状被当成了工作流");
  assert.equal(toFlowGraph("board", workflowPayload), null, "工作流形状被当成了画布");
  assert.equal(toFlowGraph("workflow", null), null);
  assert.equal(toFlowGraph("board", { items: "nope" }), null);
  assert.equal(toFlowGraph("plugin", { name: "demo", version: "1.0.0" }), null, "插件没有坐标,不该有画布");
  assert.equal(toFlowGraph("unknown", BOARD_FIXTURE), null);
});

test("③ share-canvas.tsx:client component、用 @xyflow/react、只读、fitView + 缩放上下限", () => {
  const component = read(CANVAS_COMPONENT);
  assert.ok(component.length > 0, "缺少 share-canvas.tsx");
  assert.match(component, /^["']use client["'];?/m, "不是 client component（xyflow 只能在浏览器里跑）");
  assert.match(component, /from ["']@xyflow\/react["']/, "没有用 @xyflow/react");
  assert.match(component, /@xyflow\/react\/dist\/style\.css/, "没有引 xyflow 的 CSS");
  // 只读:节点不可拖、不可连;没有编辑回调,没有工具条。
  assert.match(component, /nodesDraggable=\{false\}/);
  assert.match(component, /nodesConnectable=\{false\}/);
  assert.doesNotMatch(component, /onNodesChange/, "画布在受控编辑节点");
  assert.doesNotMatch(component, /addNode|deleteNode|onConnect=/, "画布能新增/删除节点或连线");
  // 无限浏览:打开即 fitView,平移 + 缩放,缩放有上下限。
  assert.match(component, /fitView/);
  assert.match(component, /panOnDrag/);
  assert.match(component, /zoomOnScroll/);
  assert.match(component, /minZoom=/);
  assert.match(component, /maxZoom=/);
  // 性能:节点多时只渲染视口内的。
  assert.match(component, /onlyRenderVisibleElements/);
  // 自定义节点(圆角框 + 名字),不是默认方块。
  assert.match(component, /nodeTypes/);
  assert.match(component, /type:\s*["']share["']|nodeTypes\s*=\s*\{/);
  // 边用共享几何里的 edges。
  assert.match(component, /graph\.edges/);
  // 上限提示画在角落。
  assert.match(component, /previewHidden/);
  assert.match(component, /hidden/);
});

test("④ 详情页有「在画布里看」入口,且只把最小 nodes/edges 传给 client", () => {
  const page = read(DETAIL_PAGE);
  // 静态 SVG 预览保留(首屏快 / SEO),画布是它旁边的第二个入口。
  assert.match(page, /<SharePreview\b/, "静态 SVG 预览被删了");
  assert.match(page, /<ShareCanvasDialog\b/, "详情页没有画布入口");
  assert.match(page, /toFlowGraph\(/, "详情页没有把 payload 变成最小画布图");
  assert.match(page, /\{flowGraph && \(?\s*<ShareCanvasDialog/, "没有按「有几何才给入口」渲染(插件会多出入口)");
  assert.match(page, /graph=\{flowGraph\}/, "没有把最小图传给 client");
  assert.doesNotMatch(page, /<ShareCanvasDialog[^>]*payload=/, "把原始 payload 塞进 RSC 了");
  // 插件(没有坐标)不取 payload,也就不会有画布入口。
  assert.match(page, /share\.kind === "workflow" \|\| share\.kind === "board"/);

  // 文案两边都要有。
  const messages = read("src/i18n/messages.ts");
  for (const key of ["canvasOpen", "canvasTitle", "canvasHint", "canvasClose"]) {
    const hits = messages.match(new RegExp(`${key}:`, "g")) ?? [];
    assert.equal(hits.length, 2, `文案 ${key} 不是中英各一份`);
  }
});

test("⑤ 关掉后焦点回触发按钮;Esc 由原生 <dialog> 的 cancel 处理", () => {
  const component = read(CANVAS_COMPONENT);
  assert.match(component, /<dialog\b/, "没有用原生 dialog(焦点圈定 / Esc / 背景 inert 都靠它)");
  assert.match(component, /showModal\(\)/, "没有以模态方式打开");
  assert.match(component, /onCancel=/, "没有处理 Esc(cancel)");
  assert.match(component, /onClose=/, "没有处理关闭事件");
  assert.match(component, /triggerRef\.current\?\.focus\(\)/, "关掉后没有把焦点还给触发按钮");
  assert.match(component, /ref=\{triggerRef\}/, "触发按钮没有 ref,焦点还不回来");
  // 静态预览依旧不是 client component(首屏 / SEO 靠它)。
  assert.doesNotMatch(read(PREVIEW_COMPONENT), /["']use client["']/);
});
