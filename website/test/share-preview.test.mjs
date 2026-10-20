import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

//: 官网社区「分享内容预览」的验收契约。
//:
//: 详情页此前只有文字说明和文件信息 —— 想判断「这值不值得下载」得先下下来打开。
//: 这里把预览的几何规则钉住:
//:
//: ① 工作流:`graph.nodes` 的 `position` 画成矩形,`graph.edges` 的 source/target 画成线;
//: ② 画布:`items` 按 x/y/宽高画矩形(宽高缺省时按 frontend 的 DEFAULT_SIZE 补),
//:    `edges` 按 BoardEdge 的 source/target 连线;
//: ③ viewBox 覆盖到内容最远处(不写死画布尺寸);
//: ④ 超过 200 个节点 / 格子只画前 200 个,并给出「还有 N 个没画」;
//: ⑤ 空内容 / 形状不对 / 未知 kind / plugin 一律返回 null(详情页据此不画预览块);
//: ⑥ 详情页在「这是什么」上方渲染预览,且预览组件是 server component(没有 "use client")。
//:
//: 工作流 fixture 用的是仓库里真实的一份工程文件(`public/workflows/account_analysis.*`),
//: 不是手搓的形状 —— 29 个节点 / 43 条边就是那份文件的真实数字。
const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");

const PREVIEW_COMPONENT = "src/components/community/share-preview.tsx";
const DETAIL_PAGE = "src/app/[locale]/(site)/community/[id]/page.tsx";
const WORKFLOW_FIXTURE = "public/workflows/account_analysis.en.mosael-workflow.json";

const { buildSharePreview } = await import("../src/components/community/share-preview-model.ts");

const workflowPayload = JSON.parse(read(WORKFLOW_FIXTURE));

/** 一份构造的画布:字段形状照 `frontend/src/api/domains/boards.ts` 的 BoardCanvas / BoardItem / BoardEdge。 */
const BOARD_FIXTURE = {
  items: [
    { id: "a", kind: "note", x: 0, y: 0, width: 220, height: 140 },
    // 没写宽高:预览要按该 kind 的默认尺寸补(看 frontend 的 DEFAULT_SIZE)。
    { id: "b", kind: "image", x: 320, y: 40 },
    { id: "c", kind: "video", x: 60, y: 260, width: 320, height: 200 },
    { id: "d", kind: "audio", x: 420, y: 300 },
  ],
  edges: [
    { id: "e1", source: "a", target: "b" },
    { id: "e2", source: "b", target: "c" },
    { id: "e3", source: "c", target: "d" },
  ],
  // 旗子不是画板项,也不连线:预览不画它。
  markers: [{ id: "m1", name: "Intro", x: 10, y: 10 }],
};

/** 解析 viewBox 的四个数。 */
function viewBoxOf(model) {
  const parts = model.viewBox.split(/\s+/).map(Number);
  assert.equal(parts.length, 4, "viewBox 不是四个数");
  assert.ok(parts.every(Number.isFinite), "viewBox 里有非数字");
  return { x: parts[0], y: parts[1], width: parts[2], height: parts[3] };
}

test("① 工作流:29 个节点画成 29 个矩形,43 条边画成 43 条线", () => {
  const model = buildSharePreview("workflow", workflowPayload);
  assert.ok(model, "真实工作流 fixture 没有生成预览");
  assert.equal(model.kind, "workflow");
  assert.equal(model.rects.length, workflowPayload.graph.nodes.length, "矩形数不等于节点数");
  assert.equal(model.rects.length, 29, "真实 fixture 的节点数变了");
  assert.equal(model.lines.length, workflowPayload.graph.edges.length, "线数不等于边数");
  assert.equal(model.lines.length, 43, "真实 fixture 的边数变了");
  assert.equal(model.hidden, 0, "29 个节点不该触发上限");

  // 位置来自节点的 position;尺寸用工作流节点的默认框(见 source 里的注释)。
  const start = model.rects[0];
  assert.equal(start.x, workflowPayload.graph.nodes[0].position.x);
  assert.equal(start.y, workflowPayload.graph.nodes[0].position.y);
  assert.ok(start.width > 0 && start.height > 0, "节点矩形没有尺寸");
  // 节点名只给前几个字,不能把一整句塞进去。
  const labels = model.rects.map((rect) => rect.label).filter(Boolean);
  assert.ok(labels.length > 0, "工作流节点没有名字");
  for (const label of labels) {
    assert.ok(Array.from(label).length <= 12, `节点名没有截断:${label}`);
  }
  // 同类同色:tint 只看 kind。
  const seen = new Map();
  for (const rect of model.rects) {
    if (seen.has(rect.kind)) assert.equal(rect.tint, seen.get(rect.kind), `${rect.kind} 的颜色不一致`);
    else seen.set(rect.kind, rect.tint);
  }

  // 边连的是两端矩形的中心点。
  const byId = new Map(model.rects.map((rect, index) => [workflowPayload.graph.nodes[index].id, rect]));
  const edge = workflowPayload.graph.edges[0];
  const source = byId.get(edge.source);
  const target = byId.get(edge.target);
  const line = model.lines[0];
  assert.equal(line.x1, source.x + source.width / 2);
  assert.equal(line.y1, source.y + source.height / 2);
  assert.equal(line.x2, target.x + target.width / 2);
  assert.equal(line.y2, target.y + target.height / 2);
});

test("② 画布:items 按 x/y/宽高画矩形,edges 按真实 source/target 连线", () => {
  const model = buildSharePreview("board", BOARD_FIXTURE);
  assert.ok(model, "画布 fixture 没有生成预览");
  assert.equal(model.kind, "board");
  assert.equal(model.rects.length, 4, "格子数不对");
  assert.equal(model.lines.length, 3, "连线数不对");

  const [a, b, c] = model.rects;
  assert.deepEqual({ x: a.x, y: a.y, width: a.width, height: a.height }, { x: 0, y: 0, width: 220, height: 140 });
  // 宽高缺省:image 默认 260×180(frontend/src/features/boards/boardNodes.ts 的 DEFAULT_SIZE)。
  assert.deepEqual({ x: b.x, y: b.y, width: b.width, height: b.height }, { x: 320, y: 40, width: 260, height: 180 });
  assert.deepEqual({ x: c.x, y: c.y, width: c.width, height: c.height }, { x: 60, y: 260, width: 320, height: 200 });
  // 不同 kind 的淡色不同(同类同色由 ① 覆盖)。
  assert.notEqual(a.tint, b.tint, "note 和 image 用了同一个淡色");

  const first = model.lines[0];
  assert.equal(first.x1, 0 + 220 / 2);
  assert.equal(first.y1, 0 + 140 / 2);
  assert.equal(first.x2, 320 + 260 / 2);
  assert.equal(first.y2, 40 + 180 / 2);

  // 旗子没有混进矩形,也没有多出线。
  assert.ok(!model.rects.some((rect) => rect.kind === "marker"), "marker 被当成画板项画了");

  // 真实上传上来的是画板工程文件:`items` / `edges` 在 `canvas` 里面
  // (见 frontend/src/features/boards/boardTransfer.ts)。两种形状都要认。
  const fromFile = buildSharePreview("board", {
    format: "mosael.board",
    version: 1,
    name: "demo",
    canvas: BOARD_FIXTURE,
  });
  assert.ok(fromFile, "画板工程文件(带 canvas 外层)没有生成预览");
  assert.equal(fromFile.rects.length, 4);
  assert.equal(fromFile.lines.length, 3);
});

test("③ viewBox 自动适应内容,覆盖到最远坐标", () => {
  const workflow = buildSharePreview("workflow", workflowPayload);
  const box = viewBoxOf(workflow);
  const maxX = Math.max(...workflowPayload.graph.nodes.map((node) => node.position.x)) + workflow.rects[0].width;
  const maxY = Math.max(...workflowPayload.graph.nodes.map((node) => node.position.y)) + workflow.rects[0].height;
  const minX = Math.min(...workflowPayload.graph.nodes.map((node) => node.position.x));
  const minY = Math.min(...workflowPayload.graph.nodes.map((node) => node.position.y));
  assert.ok(box.x <= minX, "viewBox 左边没盖住最左节点");
  assert.ok(box.y <= minY, "viewBox 上边没盖住最上节点");
  assert.ok(box.x + box.width >= maxX, "viewBox 右边没盖住最远节点");
  assert.ok(box.y + box.height >= maxY, "viewBox 下边没盖住最远节点");
  // 不是写死的画布尺寸:换一份内容范围不同的 payload,viewBox 就得跟着变。
  const tiny = buildSharePreview("board", { items: [{ id: "only", kind: "note", x: 5000, y: 5000 }], edges: [] });
  const tinyBox = viewBoxOf(tiny);
  assert.ok(tinyBox.x > 4000, "viewBox 没有跟着内容走(像是写死的)");
  assert.ok(tinyBox.width < box.width, "小内容的 viewBox 不该和 29 节点的工作流一样宽");
});

test("④ 超过 200 个只画前 200 个,并写出还有多少个没画", () => {
  const many = {
    graph: {
      nodes: Array.from({ length: 205 }, (_, index) => ({
        id: `n${index}`,
        type: "llm",
        name: `Node ${index}`,
        position: { x: index * 300, y: (index % 3) * 200 },
      })),
      edges: [],
    },
  };
  const workflow = buildSharePreview("workflow", many);
  assert.equal(workflow.rects.length, 200, "没有卡在 200 个节点");
  assert.equal(workflow.total, 205);
  assert.equal(workflow.hidden, 5, "没算出还有几个节点没画");

  const board = buildSharePreview("board", {
    items: Array.from({ length: 201 }, (_, index) => ({ id: `i${index}`, kind: "note", x: index * 10, y: 0 })),
    edges: [],
  });
  assert.equal(board.rects.length, 200, "没有卡在 200 个格子");
  assert.equal(board.hidden, 1);

  const component = read(PREVIEW_COMPONENT);
  assert.match(component, /previewHidden/, "预览组件没有「还有 N 个没画」这句");
  assert.match(component, /figcaption/, "「还有 N 个没画」没有画在 SVG 外面的一行小字里");
});

test("⑤ 空内容 / 形状不对 / 未知 kind / plugin 都返回 null", () => {
  assert.equal(buildSharePreview("workflow", { graph: { nodes: [], edges: [] } }), null, "空工作流应返回 null");
  assert.equal(buildSharePreview("board", { items: [], edges: [] }), null, "空画布应返回 null");
  // 200 了但不是预期形状:拿反了、缺了 graph / items、payload 不是对象。
  assert.equal(buildSharePreview("workflow", BOARD_FIXTURE), null, "画布形状被当成了工作流");
  assert.equal(buildSharePreview("board", workflowPayload), null, "工作流形状被当成了画布");
  assert.equal(buildSharePreview("workflow", null), null);
  assert.equal(buildSharePreview("board", { items: "nope" }), null);
  // 插件 manifest 没有坐标,不做预览。
  assert.equal(buildSharePreview("plugin", { name: "demo", version: "1.0.0" }), null, "plugin 不该有预览");
  assert.equal(buildSharePreview("unknown", BOARD_FIXTURE), null, "未知 kind 不该有预览");
});

test("⑥ 详情页在「这是什么」上方渲染预览;预览组件是 server component", () => {
  const page = read(DETAIL_PAGE);
  assert.match(page, /loadSharePayload/, "详情页没有在服务端取 payload");
  assert.match(page, /<SharePreview\b/, "详情页没有渲染预览块");
  const previewAt = page.indexOf("<SharePreview");
  const aboutAt = page.indexOf('id="about"');
  assert.ok(previewAt !== -1 && aboutAt !== -1, "找不到预览块或「这是什么」");
  assert.ok(previewAt < aboutAt, "预览块没有放在「这是什么」上方");

  const component = read(PREVIEW_COMPONENT);
  assert.ok(component, "缺少 share-preview.tsx");
  assert.doesNotMatch(component, /["']use client["']/, "预览组件不该是 client component");
  assert.match(component, /role="img"/, "预览没有 role=img");
  assert.match(component, /aria-label/, "预览没有 aria-label");
  assert.match(component, /aspect-\[16\/10\]/, "预览没有固定宽高比的容器");
  assert.match(component, /buildSharePreview/, "预览组件没有走纯函数");
  assert.match(component, /model\.rects\.map/, "预览没有把矩形画出来");
  assert.match(component, /<rect\b/, "预览没有 <rect>");
  assert.match(component, /model\.lines\.map/, "预览没有把连线画出来");
  assert.match(component, /<line\b/, "预览没有 <line>");
  assert.doesNotMatch(component, /<image\b|href=|src=/, "预览里塞了外部图片 / 素材 URL");
});
