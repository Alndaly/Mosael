import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import zlib from "node:zlib";

import "./support/alias.mjs";

const { toE164, safeNext, normalizeUserCode, parseTags, validHandle } = await import("../src/lib/community/input.ts");
const { inspectPluginArchive, escapesRoot, manifestSummary } = await import("../src/lib/community/zip.ts");
const { readWorkflowEnvelope, layoutGraph, hasCodeNodes, NODE_WIDTH } = await import("../src/lib/community/workflow-graph.ts");
const { diffLines, stableJson } = await import("../src/lib/community/diff.ts");
const { fillDays, scalePoints, heatmapCells, niceTicks } = await import("../src/lib/community/charts.ts");
const { toFlow, safeMediaUrl, noteColor } = await import("../src/lib/community/board.ts");
const { ENDPOINTS, REQUESTED, withQuery } = await import("../src/lib/community/endpoints.ts");

// ── 输入 ────────────────────────────────────────────────────────────────

test("手机号收成 E.164:国内 11 位补 +86,带 + 的原样收,认不出的给 null", () => {
  assert.equal(toE164("138 0013 8000"), "+8613800138000");
  assert.equal(toE164("8613800138000"), "+8613800138000");
  assert.equal(toE164("+1 (415) 555-2671"), "+14155552671");
  assert.equal(toE164("12345"), null);
  assert.equal(toE164("23800138000"), null);
});

test("登录后跳回:只收本站同语言的相对路径,不做开放跳转", () => {
  assert.equal(safeNext("/zh/device?code=ABCD-EFGH", "zh"), "/zh/device?code=ABCD-EFGH");
  assert.equal(safeNext("//evil.com/zh/", "zh"), "/zh/account");
  assert.equal(safeNext("/zh/\\evil.com", "zh"), "/zh/account");
  assert.equal(safeNext("https://evil.com/zh/x", "zh"), "/zh/account");
  assert.equal(safeNext("/en/account", "zh"), "/zh/account");
  assert.equal(safeNext(null, "en"), "/en/account");
});

test("设备码、标签、handle 的规整", () => {
  assert.equal(normalizeUserCode("abcd efgh"), "ABCD-EFGH");
  assert.equal(normalizeUserCode("ab-cd"), "ABCD");
  assert.deepEqual(parseTags("视频, #剪辑，视频 3D、 "), ["视频", "剪辑", "3d"]);
  assert.equal(validHandle("kinda_h"), true);
  assert.equal(validHandle("1kinda"), false);
  assert.equal(validHandle("Kinda"), false);
});

// ── 插件包 ──────────────────────────────────────────────────────────────

/** 写一个最小的 zip:每项 `{name, data, deflate?, mode?}`。 */
function makeZip(files) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const file of files) {
    const name = Buffer.from(file.name);
    const raw = Buffer.from(file.data ?? "");
    const body = file.deflate ? zlib.deflateRawSync(raw) : raw;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(file.deflate ? 8 : 0, 8);
    local.writeUInt32LE(body.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(name.length, 26);
    locals.push(local, name, body);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(file.deflate ? 8 : 0, 10);
    central.writeUInt32LE(body.length, 20);
    central.writeUInt32LE(raw.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(((file.mode ?? 0o100644) << 16) >>> 0, 38);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, name);
    offset += 30 + name.length + body.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  const bytes = Buffer.concat([...locals, directory, end]);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

const MANIFEST = JSON.stringify({
  id: "dev.example.shout",
  name: { zh: "大声", en: "Shout" },
  version: "1.2.0",
  runtime: { kind: "script" },
  permissions: ["network", "files.read"],
  tools: { declare: [{ name: "shout", description: { en: "Make it loud" } }] },
});

test("插件包:找到最浅的清单(外面套一层目录也行),读出权限与工具", async () => {
  const archive = await inspectPluginArchive(
    makeZip([
      { name: "shout-main/", data: "", mode: 0o040755 },
      { name: "shout-main/mosael.plugin.json", data: MANIFEST, deflate: true },
      { name: "shout-main/examples/mosael.plugin.json", data: "{}" },
      { name: "shout-main/main.py", data: "print('hi')" },
    ]),
  );
  assert.deepEqual(archive.problems, []);
  assert.equal(archive.root, "shout-main/");
  const summary = manifestSummary(archive.manifest, "en");
  assert.equal(summary.id, "dev.example.shout");
  assert.equal(summary.name, "Shout");
  assert.deepEqual(summary.permissions, ["network", "files.read"]);
  assert.deepEqual(summary.tools, [{ name: "shout", description: "Make it loud" }]);
});

test("插件包:符号链接、越界路径、没有清单、不是 zip 都指出来", async () => {
  const bad = await inspectPluginArchive(
    makeZip([
      { name: "mosael.plugin.json", data: MANIFEST },
      { name: "link", data: "/etc/passwd", mode: 0o120777 },
      { name: "../escape.py", data: "" },
    ]),
  );
  assert.deepEqual(
    bad.problems.map((problem) => problem.code),
    ["symlink", "path_escape"],
  );
  const empty = await inspectPluginArchive(makeZip([{ name: "main.py", data: "" }]));
  assert.deepEqual(empty.problems, [{ code: "no_manifest" }]);
  const notZip = await inspectPluginArchive(new TextEncoder().encode("hello").buffer);
  assert.deepEqual(notZip.problems, [{ code: "not_zip" }]);
  assert.equal(escapesRoot("C:/windows"), true);
  assert.equal(escapesRoot("a/b/c.txt"), false);
});

// ── 工作流文件与节点图 ────────────────────────────────────────────────────

const WORKFLOWS = path.resolve(import.meta.dirname, "..", "public", "workflows");

test("应用导出的工作流文件认得出来,照文件里的坐标画图", () => {
  const text = fs.readFileSync(path.join(WORKFLOWS, "highlight_shorts.en.mosael-workflow.json"), "utf8");
  const read = readWorkflowEnvelope(text);
  assert.equal(read.ok, true);
  const layout = layoutGraph(read.envelope.graph);
  assert.equal(layout.nodes.length, read.envelope.graph.nodes.length);
  assert.ok(layout.edges.length > 0);
  //: 平移到从 (0,0) 起,坐标之间的关系不变。
  assert.equal(Math.min(...layout.nodes.map((node) => node.x)), 0);
  assert.equal(Math.min(...layout.nodes.map((node) => node.y)), 0);
  assert.equal(hasCodeNodes(read.envelope.graph), false);
});

test("选错文件给出原因;缺坐标时按依赖分层,环也不死循环", () => {
  assert.deepEqual(readWorkflowEnvelope("not json"), { ok: false, problem: "not_json" });
  assert.deepEqual(readWorkflowEnvelope(JSON.stringify({ format: "other" })), { ok: false, problem: "not_workflow" });
  const graph = {
    nodes: [
      { id: "a", type: "start" },
      { id: "b", type: "code" },
      { id: "c", type: "llm" },
      { id: "d", type: "output" },
    ],
    edges: [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
      { source: "a", target: "c" },
      { source: "c", target: "d" },
      { source: "d", target: "b" },
    ],
  };
  const layout = layoutGraph(graph);
  const x = Object.fromEntries(layout.nodes.map((node) => [node.id, node.x]));
  assert.ok(x.a < x.b && x.b < x.c && x.c < x.d, JSON.stringify(x));
  assert.equal(layout.nodes.find((node) => node.id === "b").code, true);
  assert.equal(hasCodeNodes(graph), true);
  assert.ok(layout.width >= NODE_WIDTH);
});

// ── 审核差异 ────────────────────────────────────────────────────────────

test("清单逐行比,键序不同不算差异", () => {
  assert.equal(stableJson({ b: 1, a: [2] }), stableJson({ a: [2], b: 1 }));
  const lines = diffLines("a\nb\nc", "a\nc\nd");
  assert.deepEqual(lines, [
    { kind: "same", text: "a" },
    { kind: "removed", text: "b" },
    { kind: "same", text: "c" },
    { kind: "added", text: "d" },
  ]);
});

// ── 图表几何 ────────────────────────────────────────────────────────────

test("逐日计数补齐成连续的日子,空着的算 0", () => {
  const days = fillDays([{ date: "2026-09-25", count: 3 }], 3, "2026-09-26");
  assert.deepEqual(days, [
    { date: "2026-09-24", count: 0 },
    { date: "2026-09-25", count: 3 },
    { date: "2026-09-26", count: 0 },
  ]);
  const scaled = scalePoints(days, 100, 20, 0);
  assert.equal(scaled[1].y, 0);
  assert.equal(scaled[0].y, 20);
  assert.equal(scaled[2].x, 100);
  assert.deepEqual(niceTicks(7, 4), [0, 2, 4, 6, 8]);
});

test("热力图:最后一列停在截止那天,颜色按非零值分档", () => {
  const cells = heatmapCells(
    [
      { date: "2026-09-26", count: 1 },
      { date: "2026-09-25", count: 30 },
    ],
    "2026-09-26",
    2,
  );
  const last = cells.at(-1);
  assert.equal(last.date, "2026-09-26");
  assert.equal(last.weekday, new Date("2026-09-26T00:00:00Z").getUTCDay());
  assert.equal(cells.find((cell) => cell.date === "2026-09-25").level, 4);
  assert.equal(last.level, 1);
  assert.equal(cells.filter((cell) => cell.level === 0).length, cells.length - 2);
});

// ── 画板快照 ────────────────────────────────────────────────────────────

test("快照变成只读画布:缺尺寸用应用默认值,分组框垫底,媒体按哈希找地址", () => {
  const { nodes, edges } = toFlow({
    media: {
      aaa: { url: "/files/aaa.png", content_type: "image/png" },
      ttt: { url: "/files/ttt.webp", content_type: "image/webp" },
      evil: { url: "javascript:alert(1)", content_type: "image/png" },
    },
    snapshot: {
      schema: "mosael.board-snapshot/1",
      items: [
        { id: "f", kind: "frame", x: -20, y: -20, width: 600, height: 400, title: "组" },
        { id: "i", kind: "image", x: 0, y: 0, media: { sha256: "aaa", thumb_sha256: "ttt", content_type: "image/png" } },
        { id: "x", kind: "image", x: 0, y: 0, media: { sha256: "evil", content_type: "image/png" } },
        { id: "n", kind: "note", x: 300, y: 0, text: "hi", color: "teal" },
        { id: "z", kind: "hologram", x: 0, y: 500 },
      ],
      edges: [
        { id: "e1", source: "n", target: "i" },
        { id: "e2", source: "n", target: "gone" },
      ],
    },
  });
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  assert.equal(byId.f.zIndex, -1);
  assert.equal(byId.i.width, 260);
  assert.equal(byId.i.data.media.thumb, "/files/ttt.webp");
  assert.equal(byId.i.data.media.src, "/files/aaa.png");
  assert.equal(byId.x.data.media, null, "不安全的地址不进页面");
  assert.equal(byId.z.type, "unknown");
  assert.equal(noteColor(byId.n.data.item.color), "yellow");
  assert.deepEqual(edges, [{ id: "e1", source: "n", target: "i" }]);
  assert.equal(safeMediaUrl("//evil.com/x.png"), null);
  assert.equal(safeMediaUrl("https://cdn.example.com/x.png"), "https://cdn.example.com/x.png");
});

// ── 分享页 CSP ──────────────────────────────────────────────────────────

test("分享页 CSP:脚本只认 nonce,不许嵌入;存储域名只收合法的 https origin", async () => {
  const { shareCsp, mediaOrigins } = await import("../src/lib/community/csp.ts");
  const media = mediaOrigins("https://cdn.example.com/path, javascript:alert(1) http://plain.example.com not-a-url https://cdn.example.com");
  assert.deepEqual(media, ["https://cdn.example.com"]);
  const policy = shareCsp({ nonce: "abc", media, dev: false });
  assert.match(policy, /script-src 'self' 'nonce-abc' 'strict-dynamic'(;|$)/);
  assert.doesNotMatch(policy, /unsafe-eval/);
  assert.doesNotMatch(policy, /script-src[^;]*unsafe-inline/);
  assert.match(policy, /img-src 'self' data: blob: https:\/\/cdn\.example\.com/);
  assert.match(policy, /frame-ancestors 'none'/);
  assert.match(policy, /object-src 'none'/);
  assert.match(shareCsp({ nonce: "x", media: [], dev: true }), /'unsafe-eval'/);
  assert.deepEqual(mediaOrigins("http://localhost:9000", true), ["http://localhost:9000"]);
});

// ── 路径 ────────────────────────────────────────────────────────────────

test("接口路径照 ADR 拼,空参数不进查询串", () => {
  assert.equal(ENDPOINTS.items.list("workflow", { q: "视频", sort: "new", tag: "", cursor: null }), "/workflows?q=%E8%A7%86%E9%A2%91&sort=new");
  assert.equal(ENDPOINTS.items.download("plugin", "baidu-pan"), "/plugins/baidu-pan/download");
  assert.equal(ENDPOINTS.admin.hide("plugin", "x"), "/admin/items/plugin/x/hide");
  assert.equal(ENDPOINTS.stats.timeseries("users", 30), "/stats/timeseries?metric=users&days=30");
  assert.equal(REQUESTED.publicShares({ author: "kinda" }), "/shares?author=kinda");
  assert.equal(withQuery("/x"), "/x");
});
